from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.models import Source
from v2hub_api.db.repositories.base import BaseRepository

# ═══════════════════════════════════════════════════════════════════════════
# Source Repository
# ═══════════════════════════════════════════════════════════════════════════


class SourceRepository(BaseRepository[Source]):
    """Repository for Source model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Source, session)

    async def get_by_subscription(self, subscription_token: str) -> list[Source]:
        """Get all sources for a subscription, ordered."""
        stmt = (
            select(Source)
            .where(Source.subscription_token == subscription_token)
            .order_by(Source.order_index, Source.created_at)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_existing_ids(self, subscription_token: str) -> list[str]:
        """Get list of existing source IDs for a subscription."""
        stmt = select(Source.id).where(Source.subscription_token == subscription_token)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_source(
        self,
        source_id: str,
        subscription_token: str,
        source_type: str,
        config_hash: str | None = None,
        internal_token: str | None = None,
        external_url: str | None = None,
        is_hidden: bool | None = False,
        max_depth: int | None = 3,
        order_index: int = 0,
    ) -> Source:
        """Create a new source."""
        return await self.create(
            id=source_id,
            subscription_token=subscription_token,
            source_type=source_type,
            config_hash=config_hash,
            internal_token=internal_token,
            external_url=external_url,
            is_hidden=is_hidden,
            max_depth=max_depth,
            order_index=order_index,
        )

    async def get_config(self, subscription_token: str, config_hash: str) -> Source | None:
        """Get specific config in a subscription."""
        stmt = select(Source).where(
            Source.subscription_token == subscription_token, Source.id == config_hash
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_config(
        self,
        subscription_token: str,
        config_hash: str,
        is_hidden: bool | None = None,
        max_depth: int | None = None,
        order_index: int | None = None,
    ) -> Source | None:
        """Update a config."""

        config = await self.get_config(
            subscription_token=subscription_token, config_hash=config_hash
        )

        if not config:
            return None

        kwargs: dict[str, Any] = {}

        if is_hidden is not None:
            kwargs["is_hidden"] = is_hidden

        if max_depth is not None:
            kwargs["max_depth"] = max_depth

        if order_index is not None:
            kwargs["order_index"] = order_index

        if kwargs:
            await self.update(config, **kwargs)
            return config

        return None

    async def delete_all_for_subscription(self, subscription_token: str) -> int:
        """Delete all sources for a subscription."""
        stmt = delete(Source).where(Source.subscription_token == subscription_token)
        result = await self.session.execute(stmt)
        await self.session.flush()
        if result:
            return cast("CursorResult[Any]", result).rowcount or 0
        return 0

    async def delete_by_ids(self, subscription_token: str, source_ids: list[str]) -> int:
        """Delete specific sources by IDs."""
        stmt = delete(Source).where(
            Source.subscription_token == subscription_token, Source.id.in_(source_ids)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast("CursorResult[Any]", result).rowcount or 0

    async def delete_internal_references(self, token: str) -> None:
        await self.session.execute(delete(Source).where(Source.internal_token == token))

    async def get_unique_ids(self, ids: set[str]) -> set[str]:
        stmt = (
            select(Source.id)
            .where(Source.id.in_(ids))
            .group_by(Source.id)
            .having(func.count() == 1)
        )

        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}
