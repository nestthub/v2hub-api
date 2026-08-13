import secrets
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from v2hub_api.db.models import (
    ConfigComment,
    Source,
    Subscription,
)
from v2hub_api.db.repositories.base import BaseRepository

# ═══════════════════════════════════════════════════════════════════════════
# Subscription Repository
# ═══════════════════════════════════════════════════════════════════════════


class SubscriptionRepository(BaseRepository[Subscription]):
    """Repository for Subscription model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Subscription, session)

    async def get_by_token(
        self,
        token: str,
        provider_hash: str | None = None,
        load_sources: bool = False,
        load_provider: bool = False,
    ) -> Subscription | None:
        """
        Get subscription by token.

        Args:
            token: Subscription token.
            provider_hash: Provider identifier. If specified, only returns
                subscriptions created by this provider.
            load_sources: Whether to eagerly load sources.
            load_provider: Whether to eagerly load the provider.
        """
        stmt = select(Subscription).where(
            Subscription.token == token,
        )

        if provider_hash is not None:
            stmt = stmt.where(
                Subscription.provider_hash == provider_hash,
            )

        if load_sources:
            stmt = stmt.options(
                selectinload(Subscription.sources).selectinload(
                    Source.proxy_config,
                ),
                selectinload(Subscription.config_comments).selectinload(
                    ConfigComment.proxy_config,
                ),
            ).execution_options(populate_existing=True)

        if load_provider:
            stmt = stmt.options(
                joinedload(Subscription.provider),
            )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        *,
        user_hash: str,
        name: str,
        provider_hash: str | None = None,
    ) -> Subscription | None:
        """
        Get subscription by user, provider and name.

        Args:
            user_hash: User identifier.
            name: Subscription name.
            provider_hash: Provider identifier.
                If None, searches user-owned subscriptions only.
        """
        stmt = select(Subscription).where(
            Subscription.user_hash == user_hash,
            Subscription.name == name,
        )

        if provider_hash is None:
            stmt = stmt.where(
                Subscription.provider_hash.is_(None),
            )
        else:
            stmt = stmt.where(
                Subscription.provider_hash == provider_hash,
            )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_hash: str,
        load_sources: bool = False,
        include_provider_subscriptions: bool = False,
        load_provider: bool = False,
    ) -> list[Subscription]:
        """
        List subscriptions available for a user.

        Args:
            user_hash: User identifier.
            load_sources: Load related sources and comments.
            include_provider_subscriptions: Include subscriptions created by providers.
            load_provider: Load related providers.
        """
        stmt = (
            select(Subscription)
            .where(Subscription.user_hash == user_hash)
            .order_by(Subscription.created_at.desc())
        )

        if not include_provider_subscriptions:
            stmt = stmt.where(
                Subscription.provider_hash.is_(None),
            )

        if load_sources:
            stmt = stmt.options(
                selectinload(Subscription.sources).selectinload(
                    Source.proxy_config,
                ),
                selectinload(Subscription.config_comments).selectinload(
                    ConfigComment.proxy_config,
                ),
            )

        if load_provider:
            stmt = stmt.options(
                joinedload(Subscription.provider),
            )

        result = await self.session.execute(stmt)
        subscriptions = list(result.scalars().all())

        from sqlalchemy import inspect
        from sqlalchemy.orm import NO_VALUE

        for subscription in subscriptions:
            state = inspect(subscription)

            print(
                f"subscription={subscription.token} "
                f"provider_hash={subscription.provider_hash} "
                f"unloaded={state.unloaded} "
                f"expired={state.expired_attributes}"
            )

            provider = state.attrs.provider.loaded_value

            print(f"provider_loaded={provider is not NO_VALUE} provider={provider!r}")

        return subscriptions

    async def list_by_provider(
        self,
        provider_hash: str,
        user_hash: str | None = None,
        load_sources: bool = False,
        load_provider: bool = False,
    ) -> list[Subscription]:
        """
        List subscriptions created by a provider.

        Args:
            provider_hash: Provider identifier.
            user_hash: Optional target user identifier.
            load_sources: Load related sources and comments.
            load_provider: Load related provider.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.provider_hash == provider_hash,
            )
            .order_by(Subscription.created_at.desc())
        )

        if user_hash is not None:
            stmt = stmt.where(
                Subscription.user_hash == user_hash,
            )

        if load_sources:
            stmt = stmt.options(
                selectinload(Subscription.sources).selectinload(
                    Source.proxy_config,
                ),
                selectinload(Subscription.config_comments).selectinload(
                    ConfigComment.proxy_config,
                ),
            )

        if load_provider:
            stmt = stmt.options(
                joinedload(Subscription.provider),
            )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_subscription(
        self,
        *,
        token: str,
        name: str,
        user_hash: str,
        provider_hash: str | None = None,
        description: str | None = None,
    ) -> Subscription:
        """
        Create a new subscription.

        Args:
            token: Generated subscription token.
            name: Subscription name.
            user_hash: Target user identifier.
            provider_hash: Provider identifier.
                If None, subscription belongs directly to the user.
            description: Optional subscription description.
        """
        return await self.create(
            token=token,
            name=name,
            user_hash=user_hash,
            provider_hash=provider_hash,
            description=description,
        )

    async def generate_unique_token(
        self,
        length: int = 32,
    ) -> str:
        """Generate a unique subscription token."""
        while True:
            token = secrets.token_urlsafe(length)

            if not await self.exists(token=token):
                return token

    async def delete_by_provider(
        self,
        *,
        provider_hash: str,
        user_hash: str | None = None,
    ) -> int:
        """
        Delete subscriptions created by a provider.

        Args:
            provider_hash: Provider identifier.
            user_hash: Optional target user identifier.

        Returns:
            Number of deleted subscriptions.
        """
        stmt = delete(Subscription).where(
            Subscription.provider_hash == provider_hash,
        )

        if user_hash is not None:
            stmt = stmt.where(
                Subscription.user_hash == user_hash,
            )

        result: CursorResult[Any] = cast("CursorResult[Any]", await self.session.execute(stmt))
        return result.rowcount or 0
