"""
Resolver service - recursively resolves subscriptions to flat config lists.

Key features:
- Resolves INTERNAL_TOKEN sources recursively
- Fetches EXTERNAL_URL sources via cache
- Merges config data with subscription-specific comments
- Enforces depth and config count limits
- Returns fully resolved configs ready for client consumption

Performance:
- Sources within a subscription are fetched concurrently (I/O: cache reads,
  DB lookups for nested subscriptions/comments). Only the actual mutation of
  the shared `ResolveResult` (append/dedup/limit-check) happens sequentially,
  in the original source order, so dedup/truncation semantics are unchanged.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.enums import SourceType
from v2hub_api.db.models import Source
from v2hub_api.db.models.base import utcnow
from v2hub_api.db.repositories import (
    ConfigCommentRepository,
    SubscriptionRepository,
)
from v2hub_api.db.repositories.external_cache_repository import ExternalCacheRepository
from v2hub_api.schemas import ResolvedConfig
from v2hub_api.services.cache_service import CacheService
from v2hub_api.utils.config_parser import get_config_hash, parse_subscription_content

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


@dataclass
class _ExternalFetchOutcome:
    """Intermediate result of fetching an EXTERNAL_URL source (pure I/O, no shared state)."""

    source: Source
    configs: list[str] = field(default_factory=list)
    error: Exception | None = None


@dataclass
class _InternalFetchOutcome:
    """Intermediate result of loading data needed to recurse into an INTERNAL_TOKEN source."""

    source: Source
    comment_map: dict[str, str] = field(default_factory=dict)
    error: Exception | None = None


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
        self.external_repo = ExternalCacheRepository(session)

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
            resolved_subscriptions=set(),
            depth=0,
            result=result,
            root_comment_map=comment_map,
            current_subscription_token=subscription_token,
        )

        return result

    async def _resolve_recursive(
        self,
        token: str,
        resolved_subscriptions: set[str],
        depth: int,
        result: ResolveResult,
        root_comment_map: dict[str, str],
        current_subscription_token: str,
    ) -> None:
        """
        Recursively resolve subscription.

        Args:
            token: Subscription token to resolve
            resolved_subscriptions: Set of already visited tokens (cycle detection)
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
        if token in resolved_subscriptions:
            logger.error(f"Cycle detected at token {token}")
            return

        resolved_subscriptions.add(token)

        # Load subscription with sources
        subscription = await self.subscription_repo.get_by_token(token, load_sources=True)

        if not subscription:
            logger.warning(f"Subscription {token} not found")
            return

        if subscription.description and result.description == settings.domain:
            result.description = subscription.description

        # Filter sources that would even be eligible (cheap, sync checks) while
        # preserving original order — depth/hidden checks don't touch shared
        # mutable state so they're safe to do up front.
        eligible_sources = [
            source
            for source in subscription.sources
            if not (source.max_depth < depth) and not (depth == 0 and source.is_hidden)
        ]

        # Split by type: CONFIG sources are pure in-memory work (no I/O), so
        # handle them immediately. EXTERNAL_URL / INTERNAL_TOKEN involve I/O
        # (cache reads, DB queries) and are fetched concurrently below.
        config_sources: list[Source] = []
        external_sources: list[Source] = []
        internal_sources: list[Source] = []

        for source in eligible_sources:
            if len(result.configs) >= self.max_configs:
                result.truncated = True
                return
            if source.source_type == SourceType.CONFIG.value:
                config_sources.append(source)
            elif source.source_type == SourceType.EXTERNAL_URL.value:
                external_sources.append(source)
            elif source.source_type == SourceType.INTERNAL_TOKEN.value:
                internal_sources.append(source)

        # CONFIG sources: cheap, sequential (no I/O, must respect limits/order)
        for source in config_sources:
            if len(result.configs) >= self.max_configs:
                result.truncated = True
                return
            self._apply_config_source(source, result, root_comment_map)

        # EXTERNAL_URL sources: fetch from cache concurrently. Fetching is
        # pure I/O with no shared-state mutation, so it's safe to parallelize.
        now = utcnow()
        cooldown = timedelta(seconds=settings.refresh_cooldown)

        if external_sources:
            external_update_date = {
                data.url_hash: data.updated_at
                for data in await self.external_repo.get_all_by_field(
                    self.external_repo.model.url_hash,
                    [source.external_url for source in external_sources],
                )
            }

            fetch_tasks = []

            for source in external_sources:
                updated_at = external_update_date.get(source.id)
                should_refresh = False
                if updated_at is None or now - updated_at >= cooldown:
                    should_refresh = True

                fetch_tasks.append(
                    self._fetch_external_source(
                        source,
                        refresh=should_refresh,
                    )
                )

            fetch_external_results = await asyncio.gather(*fetch_tasks)

            # Apply sequentially, in original order, to preserve dedup/limit semantics.
            for ext_outcome in fetch_external_results:
                if len(result.configs) >= self.max_configs:
                    result.truncated = True
                    return

                self._apply_external_outcome(ext_outcome, result)

        # INTERNAL_TOKEN sources: first concurrently load each nested
        # subscription's comments (pure I/O, independent of shared state),
        # then recurse sequentially so that cycle-detection / depth / config
        # limits and comment-map merges behave exactly as before (recursion
        # itself mutates shared `resolved_subscriptions` and `result`, so it
        # cannot be parallelized without changing semantics).
        if internal_sources:
            fetch_internal_results = await asyncio.gather(
                *(self._fetch_internal_source_comments(source) for source in internal_sources)
            )
            for int_outcome in fetch_internal_results:
                if len(result.configs) >= self.max_configs:
                    result.truncated = True
                    return
                await self._apply_internal_outcome(
                    int_outcome,
                    resolved_subscriptions,
                    depth,
                    result,
                    root_comment_map,
                    current_subscription_token,
                )

    # ------------------------------------------------------------------
    # CONFIG sources
    # ------------------------------------------------------------------

    def _apply_config_source(
        self,
        source: Source,
        result: ResolveResult,
        root_comment_map: dict[str, str],
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

    # ------------------------------------------------------------------
    # EXTERNAL_URL sources
    # ------------------------------------------------------------------

    async def _fetch_external_source(
        self, source: Source, refresh: bool = False
    ) -> _ExternalFetchOutcome:
        """
        Fetch + parse an EXTERNAL_URL source's content. Pure I/O + parsing,
        does not touch `result`, so safe to run concurrently with siblings.
        """
        url = source.external_url
        if not url:
            logger.warning(f"Source {source.id} has no external_url")
            return _ExternalFetchOutcome(source=source, configs=[])

        try:
            content = await self.cache.get_or_fetch(url, refresh)

            if content is None:
                # No cached content available
                logger.warning(f"No cached content for {url}")
                return _ExternalFetchOutcome(source=source, configs=[])

            configs = parse_subscription_content(content)
            return _ExternalFetchOutcome(source=source, configs=configs)

        except Exception as e:
            logger.error(f"Failed to fetch external URL {url}: {e}")
            return _ExternalFetchOutcome(source=source, configs=[], error=e)

    def _apply_external_outcome(
        self,
        outcome: _ExternalFetchOutcome,
        result: ResolveResult,
    ) -> None:
        """Apply a previously-fetched EXTERNAL_URL result to the shared accumulator."""
        if outcome.error is not None or not outcome.configs:
            return

        source = outcome.source
        configs = outcome.configs

        remaining = self.max_configs - len(result.configs)
        for config in configs[:remaining]:
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

    # ------------------------------------------------------------------
    # INTERNAL_TOKEN sources
    # ------------------------------------------------------------------

    async def _fetch_internal_source_comments(self, source: Source) -> _InternalFetchOutcome:
        """
        Load the comment map for a nested subscription referenced by an
        INTERNAL_TOKEN source. Pure I/O (DB read), no shared-state mutation,
        safe to run concurrently with siblings.
        """
        token = source.internal_token
        if not token:
            logger.warning(f"Source {source.id} has no internal_token")
            return _InternalFetchOutcome(source=source, comment_map={})

        try:
            comments = await self.comment_repo.get_all_for_subscription(token)
            comment_map = {c.config_hash: c.comment for c in comments}
            return _InternalFetchOutcome(source=source, comment_map=comment_map)
        except Exception as e:
            logger.error(f"Failed to load comments for internal token {token}: {e}")
            return _InternalFetchOutcome(source=source, comment_map={}, error=e)

    async def _apply_internal_outcome(
        self,
        outcome: _InternalFetchOutcome,
        resolved_subscriptions: set[str],
        depth: int,
        result: ResolveResult,
        root_comment_map: dict[str, str],
        current_subscription_token: str,
    ) -> None:
        """
        Merge the fetched comment map and recurse into the nested subscription.

        Recursion mutates shared state (`resolved_subscriptions`, `result`,
        `root_comment_map`) and depends on cycle/depth/limit bookkeeping, so
        it is run sequentially per source, in original order.
        """
        if outcome.error is not None:
            return

        source = outcome.source
        token = source.internal_token
        if not token:
            return

        for key, value in outcome.comment_map.items():
            if not root_comment_map.get(key):
                root_comment_map[key] = value

        await self._resolve_recursive(
            token=token,
            resolved_subscriptions=resolved_subscriptions,
            depth=depth + 1,
            result=result,
            root_comment_map=root_comment_map,
            current_subscription_token=current_subscription_token,
        )
