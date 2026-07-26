from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.models import ConfigComment
from v2hub_api.db.repositories.base import BaseRepository

# ═══════════════════════════════════════════════════════════════════════════
# ConfigComment Repository
# ═══════════════════════════════════════════════════════════════════════════


class ConfigCommentRepository(BaseRepository[ConfigComment]):
    """Repository for ConfigComment model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ConfigComment, session)

    async def get_comment(self, subscription_token: str, config_hash: str) -> ConfigComment | None:
        """Get comment for a specific config in a subscription."""
        stmt = select(ConfigComment).where(
            ConfigComment.subscription_token == subscription_token,
            ConfigComment.config_hash == config_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_for_subscription(self, subscription_token: str) -> list[ConfigComment]:
        """Get all comments for a subscription."""
        stmt = select(ConfigComment).where(ConfigComment.subscription_token == subscription_token)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_comment(
        self, subscription_token: str, config_hash: str, comment: str
    ) -> ConfigComment:
        """Create or update a config comment."""
        existing = await self.get_comment(subscription_token, config_hash)

        if existing:
            return await self.update(existing, comment=comment)

        return await self.create(
            subscription_token=subscription_token, config_hash=config_hash, comment=comment
        )

    async def delete_for_subscription(
        self, subscription_token: str, config_hash: str | None = None
    ) -> int:
        """
        Delete comments for a subscription.

        Args:
            subscription_token: Subscription token
            config_hash: Specific config hash (if None, deletes all)

        Returns:
            Number of deleted records
        """
        stmt = delete(ConfigComment).where(ConfigComment.subscription_token == subscription_token)

        if config_hash:
            stmt = stmt.where(ConfigComment.config_hash == config_hash)

        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast("CursorResult[Any]", result).rowcount or 0
