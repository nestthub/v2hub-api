"""Tests for v2hub_api.db.repositories.user_repository.UserRepository."""

import pytest

from v2hub_api.db.repositories.user_repository import UserRepository

pytestmark = pytest.mark.asyncio


async def _make_user(repo: UserRepository, **overrides):
    defaults = {
        "user_hash": "hash-1",
        "user_id": 1001,
        "api_token": "token-1",
        "is_active": True,
    }
    defaults.update(overrides)
    return await repo.create_user(**defaults)


class TestCreateUser:
    async def test_creates_and_returns_user(self, db_session):
        repo = UserRepository(db_session)
        user = await _make_user(repo)

        assert user.user_hash == "hash-1"
        assert user.user_id == 1001
        assert user.api_token == "token-1"
        assert user.is_active is True

    async def test_defaults_is_active_true(self, db_session):
        repo = UserRepository(db_session)
        user = await repo.create_user(user_hash="h", user_id=2, api_token="t")
        assert user.is_active is True


class TestGetByHash:
    async def test_returns_user_when_found(self, db_session):
        repo = UserRepository(db_session)
        created = await _make_user(repo)

        found = await repo.get_by_hash("hash-1")
        assert found is not None
        assert found.user_hash == created.user_hash

    async def test_returns_none_when_missing(self, db_session):
        repo = UserRepository(db_session)
        assert await repo.get_by_hash("does-not-exist") is None


class TestGetByUserId:
    async def test_returns_user_when_found(self, db_session):
        repo = UserRepository(db_session)
        await _make_user(repo)

        found = await repo.get_by_user_id(1001)
        assert found is not None
        assert found.user_id == 1001

    async def test_returns_none_when_missing(self, db_session):
        repo = UserRepository(db_session)
        assert await repo.get_by_user_id(999999) is None


class TestGetByApiToken:
    async def test_returns_user_when_found(self, db_session):
        repo = UserRepository(db_session)
        await _make_user(repo)

        found = await repo.get_by_api_token("token-1")
        assert found is not None
        assert found.api_token == "token-1"

    async def test_returns_none_when_missing(self, db_session):
        repo = UserRepository(db_session)
        assert await repo.get_by_api_token("nope") is None


class TestUpdateApiToken:
    async def test_updates_token(self, db_session):
        repo = UserRepository(db_session)
        user = await _make_user(repo)

        updated = await repo.update_api_token(user, "new-token")
        assert updated.api_token == "new-token"

        refetched = await repo.get_by_api_token("new-token")
        assert refetched is not None
        assert refetched.user_hash == user.user_hash

        assert await repo.get_by_api_token("token-1") is None


class TestUniqueConstraints:
    async def test_duplicate_user_id_raises(self, db_session):
        repo = UserRepository(db_session)
        await _make_user(repo, user_hash="h1", user_id=42, api_token="t1")

        with pytest.raises(Exception):
            await _make_user(repo, user_hash="h2", user_id=42, api_token="t2")

    async def test_duplicate_api_token_raises(self, db_session):
        repo = UserRepository(db_session)
        await _make_user(repo, user_hash="h1", user_id=1, api_token="same-token")

        with pytest.raises(Exception):
            await _make_user(repo, user_hash="h2", user_id=2, api_token="same-token")


class TestBaseRepositoryOperations:
    async def test_exists(self, db_session):
        repo = UserRepository(db_session)
        await _make_user(repo)

        assert await repo.exists(user_hash="hash-1") is True
        assert await repo.exists(user_hash="missing") is False

    async def test_count(self, db_session):
        repo = UserRepository(db_session)
        await _make_user(repo, user_hash="h1", user_id=1, api_token="t1")
        await _make_user(repo, user_hash="h2", user_id=2, api_token="t2")

        assert await repo.count() == 2
        assert await repo.count(is_active=True) == 2

    async def test_delete(self, db_session):
        repo = UserRepository(db_session)
        user = await _make_user(repo)

        await repo.delete(user)

        assert await repo.get_by_hash("hash-1") is None

    async def test_get_all_with_pagination(self, db_session):
        repo = UserRepository(db_session)
        for i in range(5):
            await _make_user(repo, user_hash=f"h{i}", user_id=i, api_token=f"t{i}")

        page1 = await repo.get_all(limit=2, offset=0)
        page2 = await repo.get_all(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert {u.user_hash for u in page1}.isdisjoint({u.user_hash for u in page2})
