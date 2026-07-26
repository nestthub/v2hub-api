"""Tests for v2hub_api.db.repositories.subscription_repository.SubscriptionRepository."""

import pytest

from v2hub_api.db.repositories.subscription_repository import SubscriptionRepository
from v2hub_api.db.repositories.user_repository import UserRepository

pytestmark = pytest.mark.asyncio


async def _make_user(session, user_hash="user-hash-1", user_id=1, api_token="tok-1"):
    repo = UserRepository(session)
    return await repo.create_user(user_hash=user_hash, user_id=user_id, api_token=api_token)


class TestCreateSubscription:
    async def test_creates_subscription(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)

        sub = await repo.create_subscription(
            token="tok-abc",
            name="My Sub",
            user_hash="user-hash-1",
            description="desc",
        )

        assert sub.token == "tok-abc"
        assert sub.name == "My Sub"
        assert sub.user_hash == "user-hash-1"
        assert sub.description == "desc"

    async def test_description_optional(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)

        sub = await repo.create_subscription(token="t1", name="n1", user_hash="user-hash-1")
        assert sub.description is None


class TestGetByToken:
    async def test_returns_subscription(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)
        await repo.create_subscription(token="t1", name="n1", user_hash="user-hash-1")

        found = await repo.get_by_token("t1")
        assert found is not None
        assert found.name == "n1"

    async def test_returns_none_for_missing_token(self, db_session):
        repo = SubscriptionRepository(db_session)
        assert await repo.get_by_token("missing") is None

    async def test_load_sources_flag_does_not_error_when_empty(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)
        await repo.create_subscription(token="t1", name="n1", user_hash="user-hash-1")

        found = await repo.get_by_token("t1", load_sources=True)
        assert found is not None
        assert list(found.sources) == []


class TestGetByName:
    async def test_returns_subscription_for_user_and_name(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)
        await repo.create_subscription(token="t1", name="unique-name", user_hash="user-hash-1")

        found = await repo.get_by_name("user-hash-1", "unique-name")
        assert found is not None
        assert found.token == "t1"

    async def test_returns_none_for_wrong_user(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)
        await repo.create_subscription(token="t1", name="n1", user_hash="user-hash-1")

        found = await repo.get_by_name("other-user-hash", "n1")
        assert found is None

    async def test_returns_none_for_wrong_name(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)
        await repo.create_subscription(token="t1", name="n1", user_hash="user-hash-1")

        found = await repo.get_by_name("user-hash-1", "different-name")
        assert found is None


class TestListByUser:
    async def test_lists_only_users_subscriptions(self, db_session):
        await _make_user(db_session, user_hash="u1", user_id=1, api_token="tok1")
        await _make_user(db_session, user_hash="u2", user_id=2, api_token="tok2")
        repo = SubscriptionRepository(db_session)

        await repo.create_subscription(token="t1", name="n1", user_hash="u1")
        await repo.create_subscription(token="t2", name="n2", user_hash="u1")
        await repo.create_subscription(token="t3", name="n3", user_hash="u2")

        subs = await repo.list_by_user("u1")
        assert {s.token for s in subs} == {"t1", "t2"}

    async def test_empty_for_user_with_no_subscriptions(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)

        subs = await repo.list_by_user("user-hash-1")
        assert subs == []


class TestUniqueNamePerUser:
    async def test_same_name_different_users_allowed(self, db_session):
        await _make_user(db_session, user_hash="u1", user_id=1, api_token="tok1")
        await _make_user(db_session, user_hash="u2", user_id=2, api_token="tok2")
        repo = SubscriptionRepository(db_session)

        await repo.create_subscription(token="t1", name="same-name", user_hash="u1")
        # Should not raise: unique constraint is on (user_hash, name)
        sub2 = await repo.create_subscription(token="t2", name="same-name", user_hash="u2")
        assert sub2.name == "same-name"

    async def test_same_name_same_user_raises(self, db_session):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)

        await repo.create_subscription(token="t1", name="dup-name", user_hash="user-hash-1")

        with pytest.raises(Exception):
            await repo.create_subscription(token="t2", name="dup-name", user_hash="user-hash-1")


class TestGenerateUniqueToken:
    async def test_generates_token_of_expected_length_class(self, db_session):
        repo = SubscriptionRepository(db_session)
        token = await repo.generate_unique_token(length=16)
        assert isinstance(token, str)
        assert len(token) > 0

    async def test_generated_token_does_not_collide_with_existing(self, db_session, monkeypatch):
        await _make_user(db_session)
        repo = SubscriptionRepository(db_session)

        existing_token = await repo.generate_unique_token()
        await repo.create_subscription(token=existing_token, name="n1", user_hash="user-hash-1")

        # Force secrets.token_urlsafe to return the colliding token once,
        # then a fresh one, to verify the retry loop works.
        import secrets as secrets_module

        calls = {"count": 0}
        real_token_urlsafe = secrets_module.token_urlsafe

        def fake_token_urlsafe(n):
            calls["count"] += 1
            if calls["count"] == 1:
                return existing_token
            return real_token_urlsafe(n)

        monkeypatch.setattr(secrets_module, "token_urlsafe", fake_token_urlsafe)

        new_token = await repo.generate_unique_token()
        assert new_token != existing_token
        assert calls["count"] >= 2


class TestCascadeDelete:
    async def test_deleting_user_cascades_to_subscriptions(self, db_session):
        user_repo = UserRepository(db_session)
        sub_repo = SubscriptionRepository(db_session)

        user = await _make_user(db_session)
        await sub_repo.create_subscription(token="t1", name="n1", user_hash=user.user_hash)

        await user_repo.delete(user)

        assert await sub_repo.get_by_token("t1") is None
