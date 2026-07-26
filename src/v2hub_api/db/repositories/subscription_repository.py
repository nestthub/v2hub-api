import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def get_by_token(self, token: str, load_sources: bool = False) -> Subscription | None:
        """
        Get subscription by token.

        Args:
            token: Subscription token
            load_sources: Whether to eagerly load sources
        """
        stmt = select(Subscription).where(Subscription.token == token)

        if load_sources:
            stmt = stmt.options(
                selectinload(Subscription.sources).selectinload(Source.proxy_config),
                selectinload(Subscription.config_comments).selectinload(ConfigComment.proxy_config),
            ).execution_options(populate_existing=True)

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, user_hash: str, name: str) -> Subscription | None:
        """Get subscription by user and name."""
        stmt = select(Subscription).where(
            Subscription.user_hash == user_hash, Subscription.name == name
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_hash: str, load_sources: bool = False) -> list[Subscription]:
        """List all subscriptions for a user."""
        stmt = (
            select(Subscription)
            .where(Subscription.user_hash == user_hash)
            .order_by(Subscription.created_at.desc())
        )

        if load_sources:
            # Загружаем sources с proxy_config и config_comments
            stmt = stmt.options(
                selectinload(Subscription.sources).selectinload(Source.proxy_config),
                selectinload(Subscription.config_comments).selectinload(ConfigComment.proxy_config),
            )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_subscription(
        self, token: str, name: str, user_hash: str, description: str | None = None
    ) -> Subscription:
        """Create new subscription."""
        return await self.create(
            token=token, name=name, user_hash=user_hash, description=description
        )

    async def generate_unique_token(self, length: int = 32) -> str:
        """Generate a unique subscription token."""
        while True:
            token = secrets.token_urlsafe(length)
            if not await self.exists(token=token):
                return token
