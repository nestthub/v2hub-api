"""Tests for v2hub_api.db.repositories.external_cache_repository.ExternalCacheRepository."""

import pytest

from v2hub_api.db.repositories.external_cache_repository import ExternalCacheRepository

pytestmark = pytest.mark.asyncio


class TestCreateOrUpdateCache:
    async def test_creates_new_entry_with_content(self, db_session):
        repo = ExternalCacheRepository(db_session)

        entry = await repo.create_or_update_cache(
            url_hash="h1", url="https://example.com/sub", raw_content="vless://a@host:443"
        )

        assert entry.url_hash == "h1"
        assert entry.raw_content == "vless://a@host:443"
        assert entry.error_count == 0
        assert entry.last_error is None

    async def test_creates_new_entry_with_error(self, db_session):
        repo = ExternalCacheRepository(db_session)

        entry = await repo.create_or_update_cache(
            url_hash="h1", url="https://example.com/sub", last_error="timeout"
        )

        assert entry.raw_content is None
        assert entry.last_error == "timeout"
        assert entry.error_count == 1

    async def test_updates_existing_entry_with_fresh_content(self, db_session):
        repo = ExternalCacheRepository(db_session)
        await repo.create_or_update_cache(
            url_hash="h1", url="https://example.com/sub", last_error="timeout"
        )

        updated = await repo.create_or_update_cache(
            url_hash="h1", url="https://example.com/sub", raw_content="vless://a@host:443"
        )

        assert updated.raw_content == "vless://a@host:443"
        assert updated.fetched_at is not None

    async def test_updates_existing_entry_increments_error_count(self, db_session):
        repo = ExternalCacheRepository(db_session)
        await repo.create_or_update_cache(
            url_hash="h1", url="https://example.com/sub", last_error="timeout"
        )
        updated = await repo.create_or_update_cache(
            url_hash="h1", url="https://example.com/sub", last_error="timeout again"
        )

        assert updated.error_count == 2
        assert updated.last_error == "timeout again"


class TestGetByUrlHash:
    async def test_returns_entry(self, db_session):
        repo = ExternalCacheRepository(db_session)
        await repo.create_or_update_cache(url_hash="h1", url="https://a.com", raw_content="data")

        found = await repo.get_by_url_hash("h1")
        assert found is not None
        assert found.url == "https://a.com"

    async def test_returns_none_when_missing(self, db_session):
        repo = ExternalCacheRepository(db_session)
        assert await repo.get_by_url_hash("missing") is None


class TestGetByUrl:
    async def test_returns_entry(self, db_session):
        repo = ExternalCacheRepository(db_session)
        await repo.create_or_update_cache(url_hash="h1", url="https://a.com", raw_content="data")

        found = await repo.get_by_url("https://a.com")
        assert found is not None
        assert found.url_hash == "h1"

    async def test_returns_none_when_missing(self, db_session):
        repo = ExternalCacheRepository(db_session)
        assert await repo.get_by_url("https://missing.com") is None


class TestDeleteByUrlHash:
    async def test_deletes_existing_entry(self, db_session):
        repo = ExternalCacheRepository(db_session)
        await repo.create_or_update_cache(url_hash="h1", url="https://a.com", raw_content="data")

        deleted = await repo.delete_by_url_hash("h1")
        assert deleted is True
        assert await repo.get_by_url_hash("h1") is None

    async def test_returns_false_when_entry_missing(self, db_session):
        repo = ExternalCacheRepository(db_session)
        assert await repo.delete_by_url_hash("missing") is False


class TestDeleteAll:
    async def test_removes_all_entries(self, db_session):
        repo = ExternalCacheRepository(db_session)
        await repo.create_or_update_cache(url_hash="h1", url="https://a.com", raw_content="a")
        await repo.create_or_update_cache(url_hash="h2", url="https://b.com", raw_content="b")

        deleted_count = await repo.delete_all()
        assert deleted_count == 2
        assert await repo.get_by_url_hash("h1") is None
        assert await repo.get_by_url_hash("h2") is None

    async def test_no_op_when_empty(self, db_session):
        repo = ExternalCacheRepository(db_session)
        assert await repo.delete_all() == 0


class TestModelProperties:
    async def test_has_content_true_when_content_present(self, db_session):
        repo = ExternalCacheRepository(db_session)
        entry = await repo.create_or_update_cache(
            url_hash="h1", url="https://a.com", raw_content="data"
        )
        assert entry.has_content is True

    async def test_has_content_false_when_never_fetched(self, db_session):
        repo = ExternalCacheRepository(db_session)
        entry = await repo.create_or_update_cache(url_hash="h1", url="https://a.com")
        assert entry.has_content is False

    async def test_config_lines_splits_and_strips_blank_lines(self, db_session):
        repo = ExternalCacheRepository(db_session)
        entry = await repo.create_or_update_cache(
            url_hash="h1",
            url="https://a.com",
            raw_content="vless://a@host:443\n\ntrojan://b@host2:443\n   \n",
        )
        assert entry.config_lines == ["vless://a@host:443", "trojan://b@host2:443"]

    async def test_config_lines_empty_when_no_content(self, db_session):
        repo = ExternalCacheRepository(db_session)
        entry = await repo.create_or_update_cache(url_hash="h1", url="https://a.com")
        assert entry.config_lines == []
