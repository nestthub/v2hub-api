"""
Subscription service - core business logic layer.

Handles all subscription-related operations including:
- CRUD operations for subscriptions
- Source management (add, replace, remove)
- Config comment handling
- Validation and authorization
- Reference cycle detection
"""

import asyncio
import logging
from datetime import timedelta
from typing import Annotated, Any

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.enums import SourceType
from v2hub_api.core.exceptions import (
    AuthorizationError,
    CircularReferenceError,
    DuplicateNameError,
    InvalidConfigError,
    InvalidURLError,
    NestingTooDeepError,
    NotFoundError,
    SubscriptionNotFoundError,
    TooManySourcesError,
    TooManySubscriptionsError,
)
from v2hub_api.db.models import Subscription
from v2hub_api.db.models.base import utcnow
from v2hub_api.db.repositories import (
    ConfigCommentRepository,
    ExternalCacheRepository,
    ProviderAuthorizationRepository,
    ProxyConfigRepository,
    SourceRepository,
    SubscriptionRepository,
    UserRepository,
)
from v2hub_api.schemas import RefreshSubscriptionResponse, SourceCreateRequest
from v2hub_api.services.cache_service import CacheService
from v2hub_api.utils.config_parser import (
    detect_protocol,
    get_config_hash,
    get_url_hash,
    is_http_url,
    is_valid_proxy_uri,
    split_config_and_comment,
    validate_proxy_config,
)
from v2hub_api.utils.http_client import get_http_client
from v2hub_api.utils.url_validator import is_internal, validate_external_url

logger = logging.getLogger(__name__)


class SubscriptionService:
    """
    Service layer for subscription management.

    Enforces business rules:
    - Unique subscription names per user
    - Maximum sources per subscription
    - Maximum nesting depth for references
    - No circular references
    - Proper ownership validation
    """

    def __init__(self, session: AsyncSession, cache_service: CacheService | None = None) -> None:
        """Initialize service with database session."""
        self.session = session
        self.subscription_repo = SubscriptionRepository(session)
        self.source_repo = SourceRepository(session)
        self.config_repo = ProxyConfigRepository(session)
        self.comment_repo = ConfigCommentRepository(session)
        self.external_repo = ExternalCacheRepository(session)
        self.user_repo = UserRepository(session)
        self.provider_authorization_repo = ProviderAuthorizationRepository(session)
        self.cache_service = cache_service
        self._http_client = get_http_client()

    # ═══════════════════════════════════════════════════════════════════════
    # Subscription CRUD
    # ═══════════════════════════════════════════════════════════════════════

    async def create_subscription(
        self,
        *,
        user_hash: str,
        provider_hash: str | None = None,
        name: str,
        description: str | None = None,
        sources: list[SourceCreateRequest] | None = None,
    ) -> Subscription:
        """
        Create a new subscription.

        Args:
            user_hash: Owner's user hash
            provider_hash: Owner's provider hash (scopes uniqueness/limits per provider)
            name: Subscription name (unique per user)
            description: Optional description
            sources: Initial sources to add

        Returns:
            Created subscription

        Raises:
            DuplicateNameError: If name already exists for user
        """
        if provider_hash:
            curr_subs = await self.subscription_repo.list_by_provider(
                user_hash=user_hash,
                provider_hash=provider_hash,
            )
        else:
            curr_subs = await self.subscription_repo.list_by_user(user_hash=user_hash)

        max_subs = settings.max_subscriptions_per_user
        if len(curr_subs) >= max_subs:
            raise TooManySubscriptionsError(len(curr_subs), max_subs)

        # Check name uniqueness
        existing = await self.subscription_repo.get_by_name(
            user_hash=user_hash, provider_hash=provider_hash, name=name
        )
        if existing:
            raise DuplicateNameError(name)

        # Generate unique token
        token = await self.subscription_repo.generate_unique_token()

        # Create subscription
        subscription = await self.subscription_repo.create_subscription(
            token=token,
            name=name,
            user_hash=user_hash,
            provider_hash=provider_hash,
            description=description,
        )

        # Add initial sources if provided
        if sources:
            await self._add_sources_internal(
                subscription=subscription,
                sources=sources,
            )

        await self.session.commit()

        # Reload with sources
        return_sub = await self.subscription_repo.get_by_token(token, load_sources=True)

        if return_sub:
            return return_sub

        raise SubscriptionNotFoundError(token)

    async def _load_subscription(
        self,
        token: str,
    ) -> Subscription:
        subscription = await self.subscription_repo.get_by_token(
            token,
            load_sources=True,
        )

        if not subscription:
            raise SubscriptionNotFoundError(token)

        return subscription

    async def get_subscription(
        self,
        *,
        token: str,
        user_hash: str,
    ) -> Subscription:
        """
        Get subscription available to the user for reading.
        """
        subscription = await self._load_subscription(token)

        if subscription.user_hash != user_hash:
            raise AuthorizationError("You don't have permission to access this subscription")

        if subscription.provider_hash and not await self.provider_authorization_repo.get_approved(
            provider_hash=subscription.provider_hash, user_hash=user_hash
        ):
            raise SubscriptionNotFoundError(token)

        return subscription

    async def get_managed_subscription(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None,
    ) -> Subscription:
        """
        Get subscription that can be managed by the current actor.
        """
        subscription = await self._load_subscription(token)

        if subscription.user_hash != user_hash or subscription.provider_hash != provider_hash:
            raise AuthorizationError("You don't have permission to access this subscription")

        return subscription

    async def list_subscriptions(
        self,
        *,
        user_hash: str,
        provider_hash: str | None = None,
    ) -> list[Subscription]:
        """
        List all subscriptions available to the current user.
        """
        if provider_hash:
            return await self.subscription_repo.list_by_provider(
                user_hash=user_hash,
                provider_hash=provider_hash,
                load_sources=True,
            )

        subscriptions = await self.subscription_repo.list_by_user(
            user_hash,
            load_sources=True,
            include_provider_subscriptions=True,
        )

        if all(subscription.provider_hash is None for subscription in subscriptions):
            return subscriptions

        approved = await self.provider_authorization_repo.get_approved_provider_hashes(
            user_hash,
        )

        return [
            subscription
            for subscription in subscriptions
            if subscription.provider_hash is None or subscription.provider_hash in approved
        ]

    async def update_subscription(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> Subscription:
        """
        Update subscription metadata.

        Args:
            token: Subscription token
            user_hash: Requesting user's hash
            provider_hash: Requesting user's provider hash
            name: New name (if changing)
            description: New description

        Returns:
            Updated subscription

        Raises:
            DuplicateNameError: If new name conflicts
        """
        subscription = await self.get_managed_subscription(
            token=token,
            user_hash=user_hash,
            provider_hash=provider_hash,
        )

        update_data: dict[str, Any] = {}

        if name and name != subscription.name:
            # Check name uniqueness
            existing = await self.subscription_repo.get_by_name(
                user_hash=user_hash, provider_hash=provider_hash, name=name
            )
            if existing:
                raise DuplicateNameError(name)
            update_data["name"] = name

        if description is not None:
            update_data["description"] = description

        update_data["updated_at"] = utcnow()

        if update_data:
            subscription = await self.subscription_repo.update(subscription, **update_data)

        await self.session.commit()

        return subscription

    async def delete_subscription(
        self,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
    ) -> None:
        """
        Delete a subscription.

        Cascading deletion:
        - Deletes all sources
        - Clears cache for all external URL sources
        - Deletes all config comments

        Args:
            token: Subscription token
            user_hash: Requesting user's hash
            provider_hash: Requesting user's provider hash
        """
        subscription = await self.get_managed_subscription(
            token=token,
            user_hash=user_hash,
            provider_hash=provider_hash,
        )

        if not subscription:
            raise SubscriptionNotFoundError(token)

        if self.cache_service:
            external_ids = {
                s.id for s in subscription.sources if s.source_type == SourceType.EXTERNAL_URL.value
            }

            await self._delete_from_cache(subscription, external_ids)

        # Delete subscription (cascade deletes sources and comments)
        await self.subscription_repo.delete(subscription)
        await self.source_repo.delete_internal_references(token)

        await self.session.commit()

    async def _delete_from_cache(self, subscription: Subscription, external_ids: set[str]) -> None:
        if self.cache_service:
            unique_ids = await self.source_repo.get_unique_ids(external_ids)

            # Delete cache for external URLs
            if unique_ids:
                logger.info(
                    f"Deleting cache for {len(unique_ids)} external URLs "
                    f"from subscription {subscription.token}"
                )
                await self.cache_service.delete_multiple_caches(unique_ids)

    # ═══════════════════════════════════════════════════════════════════════
    # Source Management
    # ═══════════════════════════════════════════════════════════════════════

    async def add_sources(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
        sources: list[SourceCreateRequest],
    ) -> Subscription:
        """
        Add sources to subscription.

        Args:
            token: Subscription token
            user_hash: Requesting user's hash
            provider_hash: Requesting user's provider hash
            sources: Source configurations to add

        Returns:
            Updated subscription
        """
        subscription = await self.get_managed_subscription(
            token=token, user_hash=user_hash, provider_hash=provider_hash
        )
        await self._add_sources_internal(
            subscription=subscription,
            sources=sources,
        )

        await self.session.commit()

        return_sub = await self.subscription_repo.get_by_token(token, load_sources=True)

        if return_sub:
            return return_sub

        raise SubscriptionNotFoundError(token)

    async def replace_sources(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
        sources: list[SourceCreateRequest],
    ) -> Subscription:
        """
        Replace all sources in subscription.
        """

        subscription = await self.get_managed_subscription(
            token=token, user_hash=user_hash, provider_hash=provider_hash
        )

        existing_source_ids = {source.id for source in subscription.sources}
        preserved_source_ids = set()

        for source in sources:
            source_type = await self._detect_source_type(source.data)

            if source_type in (
                SourceType.EXTERNAL_URL,
                SourceType.INTERNAL_TOKEN,
            ):
                source_id = get_url_hash(source.data)
            else:
                config, _ = split_config_and_comment(source.data)
                source_id = get_config_hash(config)

            preserved_source_ids.add(source_id)

        # чистый diff
        source_ids_to_remove = existing_source_ids - preserved_source_ids

        # удаление
        if source_ids_to_remove:
            await self.remove_sources(
                token=token,
                user_hash=user_hash,
                provider_hash=provider_hash,
                source_ids=list(source_ids_to_remove),
            )

        # добавление
        await self._add_sources_internal(
            subscription=subscription,
            sources=sources,
            reset_indexes=True,
        )

        await self.session.commit()

        return_sub = await self.subscription_repo.get_by_token(
            token,
            load_sources=True,
        )

        if return_sub:
            return return_sub

        raise SubscriptionNotFoundError(token)

    async def remove_sources(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
        source_ids: list[str],
    ) -> Subscription:
        """
        Remove specific sources from subscription.

        Cascading deletion:
        - Deletes specified sources
        - Clears cache for removed external URL sources

        Args:
            token: Subscription token
            user_hash: Requesting user's hash
            provider_hash: Requesting user's provider hash
            source_ids: Source IDs to remove

        Returns:
            Updated subscription
        """
        subscription = await self.get_managed_subscription(
            token=token, user_hash=user_hash, provider_hash=provider_hash
        )

        # Get sources to be deleted (for cache cleanup)
        if self.cache_service and source_ids:
            # Get all sources
            all_sources = {src.id: src for src in subscription.sources}

            # Find external URL sources that will be deleted
            external_ids = {
                all_sources[sid].id
                for sid in source_ids
                if sid in all_sources
                and all_sources[sid].source_type == SourceType.EXTERNAL_URL.value
                and all_sources[sid].id
            }

            if external_ids:
                await self._delete_from_cache(subscription, external_ids)

        deleted = await self.source_repo.delete_by_ids(token, source_ids)
        if deleted == 0:
            logger.warning(f"No sources deleted for IDs: {source_ids}")

        subscription.updated_at = utcnow()

        await self.session.commit()

        return_sub = await self.subscription_repo.get_by_token(
            token,
            load_sources=True,
        )

        if return_sub:
            return return_sub

        raise SubscriptionNotFoundError(token)

    async def check_source(
        self,
        subscription: Subscription,
        config_hash: str,
    ) -> bool:
        hashes = [hash.id for hash in subscription.sources]

        if config_hash in hashes:
            return True

        raise NotFoundError(config_hash)

    # ═══════════════════════════════════════════════════════════════════════
    # Config Comment Management
    # ═══════════════════════════════════════════════════════════════════════

    async def update_config_comment(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
        config_hash: str,
        comment: str,
    ) -> None:
        """
        Update comment for a specific config in subscription.

        Args:
            token: Subscription token
            user_hash: Requesting user's hash
            provider_hash: Requesting user's provider hash
            config_hash: Config hash to update comment for
            comment: New comment text
        """
        # Verify ownership
        subscription = await self.get_managed_subscription(
            token=token, user_hash=user_hash, provider_hash=provider_hash
        )

        await self.check_source(subscription, config_hash)

        # Upsert comment
        await self.comment_repo.upsert_comment(
            subscription_token=token,
            config_hash=config_hash,
            comment=comment,
        )

        source = await self.source_repo.get_by_pk(
            token,
            config_hash,
        )

        if source:
            await self.source_repo.update(
                source,
                updated_at=utcnow(),
            )

        subscription.updated_at = utcnow()

        await self.session.commit()

    async def _update_config(self, token: str, config_hash: str, **kwargs: Any) -> bool:

        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        was_updated = bool(kwargs)

        if kwargs.get("comment") is not None:
            await self.comment_repo.upsert_comment(
                subscription_token=token,
                config_hash=config_hash,
                comment=kwargs.pop("comment"),
            )

        await self.source_repo.upsert_config(
            subscription_token=token, config_hash=config_hash, **kwargs
        )

        return was_updated

    async def update_config(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
        config_hash: str,
        comment: str | None = None,
        is_hidden: bool | None = None,
        max_depth: Annotated[
            int | None,
            Field(ge=0, le=settings.max_nesting_depth),
        ] = None,
    ) -> None:
        """Update source settings.

        Allows partial updates of a source associated with a subscription.
        Only the parameters explicitly provided are modified.
        """

        # Verify ownership
        subscription = await self.get_managed_subscription(
            token=token, user_hash=user_hash, provider_hash=provider_hash
        )
        await self.check_source(subscription, config_hash)

        updated = await self._update_config(
            token=token,
            config_hash=config_hash,
            comment=comment,
            is_hidden=is_hidden,
            max_depth=max_depth,
        )

        if updated:
            source = await self.source_repo.get_by_pk(
                token,
                config_hash,
            )

            if source:
                await self.source_repo.update(
                    source,
                    updated_at=utcnow(),
                )

            subscription.updated_at = utcnow()

            await self.session.commit()

    # ═══════════════════════════════════════════════════════════════════════
    # Subscription Refresh (manual update of external URLs)
    # ═══════════════════════════════════════════════════════════════════════

    async def refresh_subscription(
        self,
        *,
        token: str,
        user_hash: str,
        provider_hash: str | None = None,
    ) -> RefreshSubscriptionResponse:
        """
        Manually refresh all external URLs in subscription.
        Fetches fresh content from all EXTERNAL_URL sources and updates cache.
        Does NOT affect CONFIG or INTERNAL_TOKEN sources.
        """
        subscription = await self.get_managed_subscription(
            token=token,
            user_hash=user_hash,
            provider_hash=provider_hash,
        )

        from v2hub_api.services.cache_service import CacheService, get_redis_client

        redis = await get_redis_client()
        cache_service = CacheService(self.session, redis)

        external_urls = {
            source.id: source.external_url
            for source in subscription.sources
            if source.source_type == SourceType.EXTERNAL_URL and source.external_url
        }

        cooldown = timedelta(minutes=1)
        now = utcnow()
        skipped = 0

        external_update_date = {
            data.url_hash: data.updated_at
            for data in await self.external_repo.get_all_by_field(
                self.external_repo.model.url_hash, list(external_urls.keys())
            )
        }

        to_remove = []

        for h in external_urls:
            updated_at = external_update_date.get(h)

            if updated_at and now - updated_at < cooldown:
                skipped += 1
                to_remove.append(h)

        for h in to_remove:
            external_urls.pop(h)

        refreshed = 0
        failed = 0
        errors = []
        incorrect_links = set()

        semaphore = asyncio.Semaphore(10)

        async def refresh_one(source_hash: str, url: str) -> tuple[str, bool, str | None]:
            async with semaphore:
                try:
                    await cache_service.refresh(url)
                    logger.info("Refreshed %s", url)
                    return source_hash, True, None

                except Exception as e:
                    logger.error("Failed to refresh %s: %s", url, e)
                    return source_hash, False, f"{url}: {e!s}"

        results = await asyncio.gather(*(refresh_one(h, url) for h, url in external_urls.items()))

        for source_hash, success, error in results:
            if success:
                refreshed += 1
            else:
                failed += 1
                incorrect_links.add(source_hash)
                errors.append(error)

        if incorrect_links:
            await self.remove_sources(
                token=token,
                user_hash=user_hash,
                provider_hash=provider_hash,
                source_ids=list(incorrect_links),
            )

        subscription.updated_at = utcnow()

        await self.session.commit()

        return RefreshSubscriptionResponse(
            refreshed=refreshed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            message=None,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Internal Helpers
    # ═══════════════════════════════════════════════════════════════════════

    async def _add_sources_internal(
        self,
        *,
        subscription: Subscription,
        sources: list[SourceCreateRequest],
        reset_indexes: bool = False,
    ) -> None:
        """
        Internal method to add sources to subscription.

        Handles:
        - Type detection (CONFIG, EXTERNAL_URL, INTERNAL_TOKEN)
        - Deduplication
        - Validation
        - Circular reference checking
        - Config comment extraction
        """
        # Get existing source IDs for deduplication
        existing_ids = await self.source_repo.get_existing_ids(subscription.token)
        seen_ids = set(existing_ids)

        # Check source limit
        current_count = len(existing_ids)
        max_sources = settings.max_sources_per_subscription

        if current_count >= max_sources:
            raise TooManySourcesError(current_count, max_sources)

        # Calculate order index for new sources
        order_index = 0 if reset_indexes else current_count

        for source in sources:
            raw_source = source.data.strip()
            if not raw_source:
                continue

            # Check limit before adding each source
            if len(seen_ids) >= max_sources:
                raise TooManySourcesError(len(seen_ids), max_sources)

            # Detect source type and process
            source_type = await self._detect_source_type(raw_source)

            if source_type == SourceType.CONFIG:
                await self._add_config_source(
                    subscription_token=subscription.token,
                    source=source,
                    seen_ids=seen_ids,
                    order_index=order_index,
                )

            elif source_type == SourceType.EXTERNAL_URL:
                await self._add_external_source(
                    subscription_token=subscription.token,
                    source=source,
                    seen_ids=seen_ids,
                    order_index=order_index,
                )

            elif source_type == SourceType.INTERNAL_TOKEN:
                await self._add_internal_source(
                    subscription_token=subscription.token,
                    source=source,
                    seen_ids=seen_ids,
                    order_index=order_index,
                )

            order_index += 1

        subscription.updated_at = utcnow()

    async def _detect_source_type(self, source: str) -> SourceType:
        """Detect the type of source."""
        if is_internal(source, settings.domain):
            return SourceType.INTERNAL_TOKEN
        # Check if it's an HTTP URL
        if is_http_url(source):
            self._http_client.validate_url_static(source)
            return SourceType.EXTERNAL_URL

        # Check if it's a valid proxy config
        if is_valid_proxy_uri(source):
            return SourceType.CONFIG

        raise InvalidConfigError(source)

    async def _add_config_source(
        self,
        *,
        subscription_token: str,
        source: SourceCreateRequest,
        seen_ids: set[str],
        order_index: int,
    ) -> None:
        """
        Add a CONFIG type source.

        If config already exists in this subscription:
        - Update comment (if changed)
        - Update updated_at
        - Do NOT change created_at
        """
        # Validate config
        is_valid, error = validate_proxy_config(source.data)
        if not is_valid:
            raise InvalidConfigError(source.data, [error] if error else None)

        # Split config and comment
        base_config, comment = split_config_and_comment(source.data)
        config_hash = get_config_hash(base_config)

        # Check if this config already exists in this subscription
        source_id = config_hash

        # Check if source already exists
        existing_source = await self.source_repo.get_by_pk(subscription_token, source_id)

        if existing_source and existing_source.subscription_token == subscription_token:
            # Config already exists in this subscription
            # Only update comment if it changed
            updated = await self._update_config(
                token=existing_source.subscription_token,
                config_hash=config_hash,
                comment=comment,
                is_hidden=source.is_hidden,
                max_depth=source.max_depth,
                order_index=order_index,
            )

            if updated:
                # Update updated_at on the source
                await self.source_repo.update(existing_source, updated_at=utcnow())

            # Add to seen_ids to prevent processing again
            seen_ids.add(source_id)
            return

        if source_id in seen_ids:
            return  # Skip duplicate in current batch

        # Detect protocol
        protocol = detect_protocol(base_config)
        if not protocol:
            raise InvalidConfigError(source.data, ["Unknown protocol"])

        # Create or get proxy config (idempotent)
        await self.config_repo.get_or_create(
            config_hash=config_hash,
            config_data=base_config,
            protocol=protocol.value,
        )

        # Save comment if provided
        if not comment:
            comment = settings.domain

        await self.source_repo.create_source(
            source_id=source_id,
            subscription_token=subscription_token,
            source_type=SourceType.CONFIG.value,
            config_hash=config_hash,
            is_hidden=source.is_hidden,
            max_depth=source.max_depth,
            order_index=order_index,
        )

        await self.comment_repo.upsert_comment(
            subscription_token=subscription_token,
            config_hash=config_hash,
            comment=comment,
        )

        seen_ids.add(source_id)

    async def _add_external_source(
        self,
        *,
        subscription_token: str,
        source: SourceCreateRequest,
        seen_ids: set[str],
        order_index: int,
    ) -> None:
        """
        Add an EXTERNAL_URL type source.

        Validates URL to prevent SSRF attacks by blocking:
        - localhost/127.x.x.x
        - Private IPs (10.x, 192.168.x, 172.16-31.x)
        - Link-local addresses
        """

        url = source.data

        if not is_http_url(url):
            raise InvalidURLError(url)

        # Validate URL for security (block local addresses)
        validate_external_url(url)

        # Use URL hash as source ID
        source_id = get_url_hash(url)

        existing_source = await self.source_repo.get_by_pk(
            subscription_token,
            source_id,
        )

        if existing_source:
            updated = await self._update_config(
                token=subscription_token,
                config_hash=source_id,
                is_hidden=source.is_hidden,
                max_depth=source.max_depth,
                order_index=order_index,
            )

            if updated:
                await self.source_repo.update(
                    existing_source,
                    updated_at=utcnow(),
                )

            seen_ids.add(source_id)
            return

        if source_id in seen_ids:
            # дубликат в текущем запросе
            return

        if not await self.source_repo.exists(id=source_id):
            from v2hub_api.services.cache_service import CacheService, get_redis_client

            redis = await get_redis_client()
            cache_service = CacheService(self.session, redis)
            await cache_service.refresh(url)

        # Create source
        await self.source_repo.create_source(
            source_id=source_id,
            subscription_token=subscription_token,
            source_type=SourceType.EXTERNAL_URL.value,
            external_url=url,
            is_hidden=source.is_hidden,
            max_depth=source.max_depth,
            order_index=order_index,
        )

        seen_ids.add(source_id)

    @staticmethod
    def extract_token(url: str) -> str:
        parts = url.split("/sub/")
        if len(parts) < 2 or not parts[-1]:
            raise SubscriptionNotFoundError(url)
        return parts[-1]

    async def _add_internal_source(
        self,
        *,
        subscription_token: str,
        source: SourceCreateRequest,
        seen_ids: set[str],
        order_index: int,
    ) -> None:
        """Add an INTERNAL type source."""

        url = source.data

        internal_token = self.extract_token(url)

        if not internal_token:
            raise SubscriptionNotFoundError(url)

        sub = await self.subscription_repo.get_by_token(internal_token)
        if not sub:
            raise SubscriptionNotFoundError(url)

        # Check for circular references
        await self._check_circular_reference(
            target_token=internal_token,
            visited={subscription_token},
        )

        source_id = get_url_hash(url)

        existing_source = await self.source_repo.get_by_pk(
            subscription_token,
            source_id,
        )

        if existing_source:
            updated = await self._update_config(
                token=subscription_token,
                config_hash=source_id,
                is_hidden=source.is_hidden,
                max_depth=source.max_depth,
                order_index=order_index,
            )

            if updated:
                await self.source_repo.update(
                    existing_source,
                    updated_at=utcnow(),
                )

            seen_ids.add(source_id)
            return

        if source_id in seen_ids:
            # дубликат в текущем запросе
            return

        await self.source_repo.create_source(
            source_id=source_id,
            subscription_token=subscription_token,
            source_type=SourceType.INTERNAL_TOKEN.value,
            internal_token=internal_token,
            is_hidden=source.is_hidden,
            max_depth=source.max_depth,
            order_index=order_index,
        )

        seen_ids.add(source_id)

    async def _check_circular_reference(
        self,
        *,
        target_token: str,
        visited: set[str],
        checked: dict[str, int] | None = None,  # token -> max depth-budget it was verified for
        depth: int = 0,
    ) -> None:
        """
        Check for circular references using DFS.
        `checked` memoizes subtrees already verified acyclic, keyed by the
        remaining depth-budget they were checked with (max_depth - depth).
        A memoized result is reused only if it covers at least as much
        remaining budget as the current call needs — otherwise we couldn't
        guarantee NestingTooDeepError would still fire correctly.
        """
        if checked is None:
            checked = {}
        max_depth = settings.max_nesting_depth

        if depth > max_depth:
            raise NestingTooDeepError(depth, max_depth)

        if target_token in visited:
            chain = [*visited, target_token]
            raise CircularReferenceError(chain)

        remaining_budget = max_depth - depth
        if checked.get(target_token, -1) >= remaining_budget:
            return

        target = await self.subscription_repo.get_by_token(
            target_token,
            load_sources=True,
        )

        if not target:
            checked[target_token] = remaining_budget
            return

        visited.add(target_token)

        try:
            for source in target.sources:
                if source.source_type == SourceType.INTERNAL_TOKEN.value and source.internal_token:
                    await self._check_circular_reference(
                        target_token=source.internal_token,
                        visited=visited,
                        checked=checked,
                        depth=depth + 1,
                    )
        finally:
            visited.remove(target_token)

        checked[target_token] = remaining_budget
