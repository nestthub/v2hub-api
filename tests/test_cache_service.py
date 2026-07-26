"""Tests for v2hub_api.services.cache_service.CacheService.

Redis and the HTTP client are mocked; the PostgreSQL (L2) layer uses the
real ExternalCacheRepository against an in-memory SQLite database.
"""

from unittest.mock import AsyncMock

import pytest

from v2hub_api.core.exceptions import ExternalFetchError
from v2hub_api.services.cache_service import CacheService
from v2hub_api.utils.config_parser import get_url_hash

pytestmark = pytest.mark.asyncio


def _make_mock_redis():
    """A mock redis client with in-memory dict-backed get/setex/delete/scan."""
    store: dict[str, bytes] = {}
    redis_mock = AsyncMock()

    async def _get(key):
        return store.get(key)

    async def _setex(key, ttl, value):
        store[key] = value

    async def _delete(*keys):
        count = 0
        for k in keys:
            if k in store:
                del store[k]
                count += 1
        return count

    async def _scan(cursor, match=None, count=100):
        import fnmatch

        pattern = match or "*"
        matched = [k for k in store if fnmatch.fnmatch(k, pattern)]
        return 0, matched

    redis_mock.get.side_effect = _get
    redis_mock.setex.side_effect = _setex
    redis_mock.delete.side_effect = _delete
    redis_mock.scan.side_effect = _scan
    redis_mock._store = store  # expose for assertions
    return redis_mock


def _make_mock_http_client(responses: dict[str, str] | None = None, error: Exception | None = None):
    client = AsyncMock()
    responses = responses or {}

    async def _fetch(url):
        if error:
            raise error
        return responses[url]

    client.fetch.side_effect = _fetch
    return client


class TestGetFromCacheOnly:
    async def test_returns_none_when_nothing_cached(self, db_session):
        service = CacheService(db_session, redis_client=None)
        result = await service.get_from_cache_only("https://example.com/sub")
        assert result is None

    async def test_returns_l1_redis_hit(self, db_session):
        redis = _make_mock_redis()
        service = CacheService(db_session, redis_client=redis)
        url = "https://example.com/sub"
        url_hash = get_url_hash(url)
        redis._store[f"sub:{url_hash}"] = b"vless://uuid@host:443"

        result = await service.get_from_cache_only(url)
        assert result == "vless://uuid@host:443"

    async def test_falls_back_to_l2_db_and_restores_to_redis(self, db_session):
        redis = _make_mock_redis()
        service = CacheService(db_session, redis_client=redis)
        url = "https://example.com/sub"

        await service.cache_repo.create_or_update_cache(
            url_hash=get_url_hash(url), url=url, raw_content="trojan://pass@host:443"
        )

        result = await service.get_from_cache_only(url)
        assert result == "trojan://pass@host:443"

        # Restored into redis (L1)
        url_hash = get_url_hash(url)
        assert redis._store[f"sub:{url_hash}"] == b"trojan://pass@host:443"

    async def test_no_redis_client_still_uses_db(self, db_session):
        service = CacheService(db_session, redis_client=None)
        url = "https://example.com/sub"
        await service.cache_repo.create_or_update_cache(
            url_hash=get_url_hash(url), url=url, raw_content="vless://x@host:443"
        )

        result = await service.get_from_cache_only(url)
        assert result == "vless://x@host:443"


class TestGetOrFetch:
    async def test_returns_cached_content_without_fetching(self, db_session):
        redis = _make_mock_redis()
        http_client = _make_mock_http_client()
        service = CacheService(db_session, redis_client=redis, http_client=http_client)
        url = "https://example.com/sub"
        url_hash = get_url_hash(url)
        redis._store[f"sub:{url_hash}"] = b"cached-content"

        result = await service.get_or_fetch(url)

        assert result == "cached-content"
        http_client.fetch.assert_not_called()

    async def test_fetches_and_caches_on_miss(self, db_session):
        redis = _make_mock_redis()
        url = "https://example.com/sub"
        http_client = _make_mock_http_client({url: "vless://fresh@host:443"})
        service = CacheService(db_session, redis_client=redis, http_client=http_client)

        result = await service.get_or_fetch(url)

        assert result == "vless://fresh@host:443"
        http_client.fetch.assert_called_once_with(url)

        # Persisted to DB (L2)
        db_entry = await service.cache_repo.get_by_url(url)
        assert db_entry is not None
        assert db_entry.raw_content == "vless://fresh@host:443"

        # Persisted to Redis (L1)
        url_hash = get_url_hash(url)
        assert redis._store[f"sub:{url_hash}"] == b"vless://fresh@host:443"

    async def test_raises_external_fetch_error_and_records_it(self, db_session):
        url = "https://example.com/sub"
        fetch_error = ExternalFetchError(url=url, reason="connection refused")
        http_client = _make_mock_http_client(error=fetch_error)
        service = CacheService(db_session, redis_client=None, http_client=http_client)

        with pytest.raises(ExternalFetchError):
            await service.get_or_fetch(url)

        db_entry = await service.cache_repo.get_by_url(url)
        assert db_entry is not None
        assert db_entry.last_error is not None


class TestInvalidate:
    async def test_removes_from_both_caches(self, db_session):
        redis = _make_mock_redis()
        service = CacheService(db_session, redis_client=redis)
        url = "https://example.com/sub"
        url_hash = get_url_hash(url)

        await service.cache_repo.create_or_update_cache(
            url_hash=url_hash, url=url, raw_content="data"
        )
        redis._store[f"sub:{url_hash}"] = b"data"

        await service.invalidate(url)

        assert f"sub:{url_hash}" not in redis._store
        assert await service.cache_repo.get_by_url_hash(url_hash) is None


class TestRefresh:
    async def test_forces_new_fetch_even_if_cached(self, db_session):
        redis = _make_mock_redis()
        url = "https://example.com/sub"
        url_hash = get_url_hash(url)
        redis._store[f"sub:{url_hash}"] = b"stale-data"

        http_client = _make_mock_http_client({url: "fresh-data"})
        service = CacheService(db_session, redis_client=redis, http_client=http_client)

        result = await service.refresh(url)

        assert result == "fresh-data"
        http_client.fetch.assert_called_once_with(url)


class TestDeleteCache:
    async def test_deletes_by_url_hash_from_both_layers(self, db_session):
        redis = _make_mock_redis()
        service = CacheService(db_session, redis_client=redis)
        url = "https://example.com/sub"
        url_hash = get_url_hash(url)

        await service.cache_repo.create_or_update_cache(
            url_hash=url_hash, url=url, raw_content="data"
        )
        redis._store[f"sub:{url_hash}"] = b"data"

        await service.delete_cache(url_hash)

        assert f"sub:{url_hash}" not in redis._store
        assert await service.cache_repo.get_by_url_hash(url_hash) is None


class TestClearAllCache:
    async def test_clears_db_entries(self, db_session):
        service = CacheService(db_session, redis_client=None)
        await service.cache_repo.create_or_update_cache(
            url_hash="h1", url="https://a.com", raw_content="a"
        )
        await service.cache_repo.create_or_update_cache(
            url_hash="h2", url="https://b.com", raw_content="b"
        )

        await service.clear_all_cache()

        assert await service.cache_repo.get_by_url_hash("h1") is None
        assert await service.cache_repo.get_by_url_hash("h2") is None
