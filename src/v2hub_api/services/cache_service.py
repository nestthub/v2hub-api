"""
Cache service for external subscription URLs.

Implements two-tier caching:
- L1 (Redis): Fast in-memory cache with TTL
- L2 (PostgreSQL): Persistent cache for external URLs

Cache flow:
1. Check Redis (L1)
2. If miss, check PostgreSQL (L2) and restore to Redis
3. If miss, fetch from URL and store in both caches
"""

import logging
from typing import TYPE_CHECKING, Any, cast

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.exceptions import ExternalFetchError
from v2hub_api.db.repositories import ExternalCacheRepository, SourceRepository
from v2hub_api.utils.config_parser import get_url_hash
from v2hub_api.utils.http_client import SubscriptionHTTPClient, get_http_client

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)


class CacheService:
    """
    Service for caching external subscription content.

    Provides transparent two-tier caching with automatic fallback
    and fetch-on-miss behavior.
    """

    def __init__(
        self,
        session: AsyncSession,
        redis_client: redis.Redis | None = None,
        http_client: SubscriptionHTTPClient | None = None,
    ) -> None:
        """
        Initialize cache service.

        Args:
            session: Database session for L2 cache
            redis_client: Redis client for L1 cache (optional)
        """
        self.session = session
        self.redis = redis_client
        self.cache_repo = ExternalCacheRepository(session)
        self.source_repo = SourceRepository(session)
        self.http_client = http_client if http_client else get_http_client()

        self.redis_ttl = settings.redis_ttl
        self.redis_prefix = "sub:"

    async def get_or_fetch(self, url: str, refresh: bool = False) -> str | None:
        """
        Get cached content, or fetch fresh content if:
        - `refresh=True` (force bypass cache)
        """
        url_hash = get_url_hash(url)

        if not refresh:
            return await self.get_from_cache_only(url)

        return await self._fetch_and_cache(url, url_hash)

    async def get_from_cache_only(self, url: str) -> str | None:
        """
        Get subscription content ONLY from cache (no HTTP fetch).

        Used during normal resolution - returns cached data without
        making external requests.

        Cache strategy:
        1. Try Redis (L1)
        2. Try PostgreSQL (L2), restore to Redis
        3. Return None if not cached

        Args:
            url: External subscription URL

        Returns:
            Cached content or None if not cached
        """
        url_hash = get_url_hash(url)

        # Try L1 cache (Redis)
        if self.redis:
            try:
                cached = await self._get_from_redis(url_hash)
                if cached is not None:
                    logger.debug(f"Cache hit (L1) for {url}")
                    return cached
            except Exception as e:
                logger.warning(f"Redis error: {e}")

        # Try L2 cache (PostgreSQL)
        try:
            cached = await self._get_from_db(url_hash)
            if cached is not None:
                logger.debug(f"Cache hit (L2) for {url}")

                # Restore to L1
                if self.redis:
                    try:
                        await self._set_to_redis(url_hash, cached)
                    except Exception as e:
                        logger.warning(f"Failed to restore to Redis: {e}")

                return cached
        except Exception as e:
            logger.warning(f"Database cache error: {e}")

        # Not in cache - return None (no fetch)
        logger.debug(f"No cache for {url}")
        return None

    async def invalidate(self, url: str) -> None:
        """
        Invalidate cache for a specific URL.

        Args:
            url: URL to invalidate
        """
        url_hash = get_url_hash(url)

        # Remove from Redis
        if self.redis:
            try:
                await self.redis.delete(self._redis_key(url_hash))
            except Exception as e:
                logger.warning(f"Failed to invalidate Redis cache: {e}")

        # Remove from database
        try:
            cache_entry = await self.cache_repo.get_by_url_hash(url_hash)
            if cache_entry:
                await self.cache_repo.delete(cache_entry)
        except Exception as e:
            logger.warning(f"Failed to invalidate DB cache: {e}")

    async def refresh(self, url: str) -> str | None:
        """
        Force refresh cache by fetching from URL.

        Args:
            url: URL to refresh

        Returns:
            Fresh content
        """
        url_hash = get_url_hash(url)
        return await self._fetch_and_cache(url, url_hash)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal Methods
    # ═══════════════════════════════════════════════════════════════════════

    def _redis_key(self, url_hash: str) -> str:
        """Generate Redis key from URL hash."""
        return f"{self.redis_prefix}{url_hash}"

    async def _get_from_redis(self, url_hash: str) -> str | None:
        """Get content from Redis cache."""
        if not self.redis:
            return None

        key = self._redis_key(url_hash)
        content = await self.redis.get(key)

        if content:
            return str(content.decode("utf-8"))

        return None

    async def _set_to_redis(self, url_hash: str, content: str) -> None:
        """Store content in Redis cache."""
        if not self.redis:
            return

        key = self._redis_key(url_hash)
        await self.redis.setex(key, self.redis_ttl, content.encode("utf-8"))

    async def _get_from_db(self, url_hash: str) -> str | None:
        """Get content from PostgreSQL cache."""
        cache_entry = await self.cache_repo.get_by_url_hash(url_hash)

        if cache_entry and cache_entry.has_content:
            # Return newline-separated configs
            return cache_entry.raw_content

        return None

    async def _fetch_and_cache(self, url: str, url_hash: str) -> str | None:
        """
        Fetch content from URL and store in both caches.

        Args:
            url: URL to fetch
            url_hash: Pre-calculated URL hash

        Returns:
            Fetched content

        Raises:
            ExternalFetchError: If fetch fails
        """
        try:
            # Fetch from URL
            content = await self.http_client.fetch(url)

            # Store in L2 (PostgreSQL)
            await self.cache_repo.create_or_update_cache(
                url_hash=url_hash,
                url=url,
                raw_content=content,
                last_error=None,
            )

            # Store in L1 (Redis)
            if self.redis and content:
                try:
                    await self._set_to_redis(url_hash, content)
                except Exception as e:
                    logger.warning(f"Failed to cache in Redis: {e}")

            logger.info(f"Successfully fetched and cached {url}")
            return content

        except ExternalFetchError as e:
            # Store error in database
            try:
                await self.cache_repo.create_or_update_cache(
                    url_hash=url_hash,
                    url=url,
                    last_error=e.message,
                )
            except Exception as db_error:
                logger.error(f"Failed to store fetch error: {db_error}")

            raise

    # ═══════════════════════════════════════════════════════════════════
    # Cache Invalidation Methods
    # ═══════════════════════════════════════════════════════════════════

    async def delete_cache(self, url_hash: str) -> None:
        """
        Delete cached content for a URL from both Redis and PostgreSQL.

        Args:
            url: URL to invalidate
        """
        # Delete from Redis (L1)
        if self.redis:
            try:
                key = self._redis_key(url_hash)
                deleted = await self.redis.delete(key)
                if deleted:
                    logger.info(f"Deleted cache (L1) for {url_hash}")
            except Exception as e:
                logger.warning(f"Failed to delete from Redis: {e}")

        # Delete from PostgreSQL (L2)
        try:
            await self.cache_repo.delete_by_url_hash(url_hash)
            logger.info(f"Deleted cache (L2) for {url_hash}")
        except Exception as e:
            logger.warning(f"Failed to delete from database: {e}")

    async def delete_multiple_caches(self, url_hashes: list[str] | set[str]) -> None:
        """
        Delete cached content for multiple URLs.

        Args:
            urls: List of URLs to invalidate
        """
        for url_hash in url_hashes:
            try:
                await self.delete_cache(url_hash)
            except Exception as e:
                logger.error(f"Error deleting cache for {url_hash}: {e}")

    async def clear_all_cache(self) -> None:
        """
        Clear ALL cached content (use with caution).

        This deletes all external URL caches from both Redis and PostgreSQL.
        """
        # Clear Redis
        if self.redis:
            try:
                pattern = f"{self.redis_prefix}*"
                cursor = 0
                deleted_count = 0

                while True:
                    cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=100)

                    if keys:
                        deleted = await self.redis.delete(*keys)
                        deleted_count += deleted

                    if cursor == 0:
                        break

                logger.info(f"Cleared {deleted_count} keys from Redis")
            except Exception as e:
                logger.error(f"Error clearing Redis cache: {e}")

        # Clear PostgreSQL
        try:
            await self.cache_repo.delete_all()
            logger.info("Cleared all cache entries from database")
        except Exception as e:
            logger.error(f"Error clearing database cache: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Redis Client Factory
# ═══════════════════════════════════════════════════════════════════════════

_redis_client: redis.Redis | None = None


async def get_redis_client() -> redis.Redis | None:
    """
    Get or create Redis client.

    Returns:
        Redis client or None if Redis is not configured
    """
    global _redis_client

    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                settings.redis_url_str,
                encoding="utf-8",
                decode_responses=False,  # We handle encoding manually
                socket_timeout=5,  # Таймаут на операцию (сек) — предотвращает вечное ожидание
                socket_connect_timeout=3,  # Таймаут на установку соединения
                retry_on_timeout=True,  # Один автоматический ретрай при таймауте
                health_check_interval=30,  # Проверка живости соединения каждые 30 сек
            )

            await cast("Awaitable[Any]", _redis_client.ping())
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
            _redis_client = None

    return _redis_client


async def close_redis_client() -> None:
    """Close Redis client."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
