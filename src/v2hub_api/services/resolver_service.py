"""
Resolver service - recursively resolves subscriptions to flat config lists.

Key features:
- Resolves INTERNAL_TOKEN sources recursively
- Fetches EXTERNAL_URL sources via cache
- Merges config data with subscription-specific comments
- Enforces depth and config count limits
- Returns fully resolved configs ready for client consumption
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.enums import SourceType
from v2hub_api.db.models import Source
from v2hub_api.db.repositories import (
    ConfigCommentRepository,
    SubscriptionRepository,
)
from v2hub_api.schemas import ResolvedConfig
from v2hub_api.services.cache_service import CacheService
from v2hub_api.utils.config_parser import parse_subscription_content

logger = logging.getLogger(__name__)


@dataclass
class ResolveResult:
    """Result of subscription resolution."""

    configs: list[ResolvedConfig] = field(default_factory=list)
    seen_hashes: set[str] = field(default_factory=set)  # O(1) dedup вместо O(n) any()
    description: str = settings.domain
    truncated: bool = False  # Hit max_configs limit
    depth_exceeded: bool = False  # Hit max_depth limit
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def count(self) -> int:
        """Get number of resolved configs."""
        return len(self.configs)


class ResolverService:
    """
    Service for resolving subscriptions to flat configuration lists.

    Resolution rules:
    - CONFIG sources: Include directly with subscription-specific comment
    - EXTERNAL_URL sources: Fetch via cache, parse configs
    - INTERNAL_TOKEN sources: Resolve recursively

    Limits enforced:
    - max_nesting_depth: Maximum recursion depth
    - max_configs_per_subscription: Maximum total configs
    """

    def __init__(
        self,
        session: AsyncSession,
        cache_service: CacheService,
    ) -> None:
        """
        Initialize resolver service.

        Args:
            session: Database session
            cache_service: Cache service for external URLs
        """
        self.session = session
        self.cache = cache_service
        self.subscription_repo = SubscriptionRepository(session)
        self.comment_repo = ConfigCommentRepository(session)

        self.max_depth = settings.max_nesting_depth
        self.max_configs = settings.max_configs_per_subscription

    async def resolve(
        self,
        subscription_token: str,
    ) -> ResolveResult:
        """
        Resolve subscription to flat list of configs.

        Args:
            subscription_token: Token of subscription to resolve

        Returns:
            ResolveResult with all resolved configs
        """
        result = ResolveResult()

        # Load subscription-specific comments
        comments = await self.comment_repo.get_all_for_subscription(subscription_token)
        comment_map = {c.config_hash: c.comment for c in comments}

        # Start recursive resolution
        await self._resolve_recursive(
            token=subscription_token,
            visited=frozenset(),
            depth=0,
            result=result,
            root_comment_map=comment_map,
            current_subscription_token=subscription_token,
        )

        return result

    async def _resolve_recursive(
        self,
        token: str,
        visited: frozenset[str],
        depth: int,
        result: ResolveResult,
        root_comment_map: dict[str, str],
        current_subscription_token: str,
    ) -> None:
        """
        Recursively resolve subscription.

        Args:
            token: Subscription token to resolve
            visited: Set of already visited tokens (cycle detection)
            depth: Current recursion depth
            result: Accumulator for results
            root_comment_map: Comments from root subscription
            current_subscription_token: Token of the subscription being resolved
        """
        # Check limits
        if len(result.configs) >= self.max_configs:
            result.truncated = True
            return

        if depth > self.max_depth:
            logger.warning(f"Depth limit exceeded at token {token}")
            result.depth_exceeded = True
            return

        # Check for cycles
        if token in visited:
            logger.error(f"Cycle detected at token {token}")
            return

        visited = visited | {token}

        # Load subscription with sources
        subscription = await self.subscription_repo.get_by_token(token, load_sources=True)

        if not subscription:
            logger.warning(f"Subscription {token} not found")
            return

        if subscription.description and result.description == settings.domain:
            result.description = subscription.description

        # Process each source
        for source in subscription.sources:
            remaining = self.max_configs - len(result.configs)
            if remaining <= 0:
                result.truncated = True
                return

            await self._process_source(
                source=source,
                visited=visited,
                depth=depth,
                result=result,
                root_comment_map=root_comment_map,
                current_subscription_token=current_subscription_token,
            )

    async def _process_source(
        self,
        source: Source,
        visited: frozenset[str],
        depth: int,
        result: ResolveResult,
        root_comment_map: dict[str, str],
        current_subscription_token: str,
    ) -> None:
        """Process a single source based on its type."""

        # Check current depth limit for the source
        if source.max_depth < depth:
            return

        if depth == 0 and source.is_hidden:
            return

        if source.source_type == SourceType.CONFIG.value:
            await self._process_config_source(
                source,
                result,
                root_comment_map,
                current_subscription_token,
            )

        elif source.source_type == SourceType.EXTERNAL_URL.value:
            await self._process_external_source(
                source,
                result,
            )

        elif source.source_type == SourceType.INTERNAL_TOKEN.value:
            await self._process_internal_source(
                source,
                visited,
                depth,
                result,
                root_comment_map,
                current_subscription_token,
            )

    async def _process_config_source(
        self,
        source: Source,
        result: ResolveResult,
        root_comment_map: dict[str, str],
        _current_subscription_token: str,
    ) -> None:
        """
        Process CONFIG type source.

        Merges config data with subscription-specific comment.
        """
        if not source.proxy_config or not source.config_hash:
            logger.warning(f"Source {source.id} has no proxy_config loaded")
            return

        config_hash = source.config_hash
        base_config = source.proxy_config.config_data

        # Get comment for THIS subscription
        comment = root_comment_map.get(config_hash)

        # Build full config with comment
        full_config = f"{base_config}#{comment}" if comment else base_config

        # Add to results (deduplicate by hash — O(1) через seen_hashes set)
        if config_hash not in result.seen_hashes:
            result.seen_hashes.add(config_hash)
            result.configs.append(
                ResolvedConfig(
                    hash=config_hash,
                    config=full_config,
                    is_hidden=source.is_hidden,
                    max_depth=source.max_depth,
                )
            )

    async def _process_external_source(
        self,
        source: Source,
        result: ResolveResult,
    ) -> None:
        """
        Process EXTERNAL_URL type source.

        Fetches content ONLY from cache (no HTTP requests).
        Content should be updated separately via refresh endpoint or Celery task.
        """
        url = source.external_url
        if not url:
            logger.warning(f"Source {source.id} has no external_url")
            return

        try:
            # Get from cache only (no HTTP fetch)
            content = await self.cache.get_from_cache_only(url)

            if content is None:
                # No cached content available
                logger.warning(f"No cached content for {url}")
                return

            # Parse configs from content
            configs = parse_subscription_content(content)

            # Add configs (up to remaining limit)
            remaining = self.max_configs - len(result.configs)
            for config in configs[:remaining]:
                from v2hub_api.utils.config_parser import get_config_hash

                config_hash = get_config_hash(config)

                # Deduplicate — O(1) через seen_hashes set
                if config_hash not in result.seen_hashes:
                    result.seen_hashes.add(config_hash)
                    result.configs.append(
                        ResolvedConfig(
                            hash=config_hash,
                            config=config,
                            is_hidden=source.is_hidden,
                            max_depth=source.max_depth,
                        )
                    )

            if len(configs) > remaining:
                result.truncated = True

        except Exception as e:
            logger.error(f"Failed to fetch external URL {url}: {e}")
            # Continue processing other sources

    async def _process_internal_source(
        self,
        source: Source,
        visited: frozenset[str],
        depth: int,
        result: ResolveResult,
        root_comment_map: dict[str, str],
        current_subscription_token: str,
    ) -> None:
        """
        Process INTERNAL_TOKEN type source.

        Recursively resolves referenced subscription.
        """
        token = source.internal_token
        if not token:
            logger.warning(f"Source {source.id} has no internal_token")
            return

        comments = await self.comment_repo.get_all_for_subscription(token)
        comment_map = {c.config_hash: c.comment for c in comments}

        for key, value in comment_map.items():
            if not root_comment_map.get(key):
                root_comment_map[key] = value

        # Recursively resolve
        await self._resolve_recursive(
            token=token,
            visited=visited,
            depth=depth + 1,
            result=result,
            root_comment_map=root_comment_map,
            current_subscription_token=current_subscription_token,
        )
