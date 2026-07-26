from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.models import ExternalCache
from v2hub_api.db.repositories.base import BaseRepository

# ═══════════════════════════════════════════════════════════════════════════
# ExternalCache Repository
# ═══════════════════════════════════════════════════════════════════════════


class ExternalCacheRepository(BaseRepository[ExternalCache]):
    """Repository for ExternalCache model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExternalCache, session)

    async def get_by_url_hash(self, url_hash: str) -> ExternalCache | None:
        """Get cache entry by URL hash."""
        return await self.get_by_id(url_hash)

    async def get_by_url(self, url: str) -> ExternalCache | None:
        """Get cache entry by URL."""
        stmt = select(ExternalCache).where(ExternalCache.url == url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update_cache(
        self, url_hash: str, url: str, raw_content: str | None = None, last_error: str | None = None
    ) -> ExternalCache:
        """Create or update cache entry."""
        existing = await self.get_by_url_hash(url_hash)

        if existing:
            update_data: dict[str, Any] = {"url": url}
            if raw_content is not None:
                update_data.update({"raw_content": raw_content, "fetched_at": datetime.now(tz=UTC)})
            elif last_error is not None:
                update_data.update(
                    {"last_error": last_error, "error_count": existing.error_count + 1}
                )

            return await self.update(existing, **update_data)

        return await self.create(
            url_hash=url_hash,
            url=url,
            raw_content=raw_content,
            last_error=last_error,
            error_count=1 if last_error else 0,
        )

    async def delete_by_url_hash(self, url_hash: str) -> bool:
        """
        Delete cache entry by URL hash.

        Args:
            url_hash: Hash of the URL

        Returns:
            True if deleted, False if not found
        """
        cache_entry = await self.get_by_url_hash(url_hash)
        if cache_entry:
            await self.delete(cache_entry)
            return True
        return False

    async def delete_all(self) -> int:
        """
        Delete all cache entries.

        Returns:
            Number of deleted entries
        """
        from sqlalchemy import delete as sql_delete

        stmt = sql_delete(ExternalCache)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast("CursorResult[Any]", result).rowcount or 0
