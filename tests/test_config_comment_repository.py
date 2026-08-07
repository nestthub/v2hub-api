"""Tests for v2hub_api.db.repositories.config_comment_repository.ConfigCommentRepository."""

import pytest

from v2hub_api.db.repositories.config_comment_repository import ConfigCommentRepository
from v2hub_api.db.repositories.proxy_config import ProxyConfigRepository
from v2hub_api.db.repositories.subscription_repository import SubscriptionRepository
from v2hub_api.db.repositories.user_repository import UserRepository

pytestmark = pytest.mark.asyncio


async def _make_subscription_with_config(session, token="sub-1", config_hash="hash-1"):
    await UserRepository(session).create_user(user_hash="u1", user_id=1, api_token="tok")
    await SubscriptionRepository(session).create_subscription(
        token=token, name="n1", user_hash="u1"
    )
    await ProxyConfigRepository(session).create_config(
        config_hash, "vless://uuid@host:443", "vless"
    )


class TestUpsertComment:
    async def test_creates_new_comment(self, db_session):
        await _make_subscription_with_config(db_session)
        repo = ConfigCommentRepository(db_session)

        comment = await repo.upsert_comment("sub-1", "hash-1", "My Server")

        assert comment.comment == "My Server"
        assert comment.subscription_token == "sub-1"
        assert comment.config_hash == "hash-1"

    async def test_updates_existing_comment(self, db_session):
        await _make_subscription_with_config(db_session)
        repo = ConfigCommentRepository(db_session)

        first = await repo.upsert_comment("sub-1", "hash-1", "Initial")
        second = await repo.upsert_comment("sub-1", "hash-1", "Updated")

        assert second.id == first.id
        assert second.comment == "Updated"

        # Only one row should exist
        all_comments = await repo.get_all_for_subscription("sub-1")
        assert len(all_comments) == 1


class TestGetComment:
    async def test_returns_comment(self, db_session):
        await _make_subscription_with_config(db_session)
        repo = ConfigCommentRepository(db_session)
        await repo.upsert_comment("sub-1", "hash-1", "Hello")

        found = await repo.get_comment("sub-1", "hash-1")
        assert found is not None
        assert found.comment == "Hello"

    async def test_returns_none_when_missing(self, db_session):
        await _make_subscription_with_config(db_session)
        repo = ConfigCommentRepository(db_session)

        assert await repo.get_comment("sub-1", "hash-1") is None


class TestGetAllForSubscription:
    async def test_returns_all_comments(self, db_session):
        await UserRepository(db_session).create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-1", name="n1", user_hash="u1"
        )
        proxy_repo = ProxyConfigRepository(db_session)
        await proxy_repo.create_config("hash-1", "vless://a@host:443", "vless")
        await proxy_repo.create_config("hash-2", "vless://b@host:443", "vless")

        repo = ConfigCommentRepository(db_session)
        await repo.upsert_comment("sub-1", "hash-1", "Server A")
        await repo.upsert_comment("sub-1", "hash-2", "Server B")

        comments = await repo.get_all_for_subscription("sub-1")
        assert {c.comment for c in comments} == {"Server A", "Server B"}

    async def test_empty_for_subscription_without_comments(self, db_session):
        await _make_subscription_with_config(db_session)
        repo = ConfigCommentRepository(db_session)

        assert await repo.get_all_for_subscription("sub-1") == []


class TestDeleteForSubscription:
    async def test_deletes_specific_config_comment(self, db_session):
        await UserRepository(db_session).create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-1", name="n1", user_hash="u1"
        )
        proxy_repo = ProxyConfigRepository(db_session)
        await proxy_repo.create_config("hash-1", "vless://a@host:443", "vless")
        await proxy_repo.create_config("hash-2", "vless://b@host:443", "vless")

        repo = ConfigCommentRepository(db_session)
        await repo.upsert_comment("sub-1", "hash-1", "A")
        await repo.upsert_comment("sub-1", "hash-2", "B")

        deleted = await repo.delete_for_subscription("sub-1", config_hash="hash-1")
        assert deleted == 1

        remaining = await repo.get_all_for_subscription("sub-1")
        assert [c.config_hash for c in remaining] == ["hash-2"]

    async def test_deletes_all_when_no_config_hash_given(self, db_session):
        await UserRepository(db_session).create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-1", name="n1", user_hash="u1"
        )
        proxy_repo = ProxyConfigRepository(db_session)
        await proxy_repo.create_config("hash-1", "vless://a@host:443", "vless")
        await proxy_repo.create_config("hash-2", "vless://b@host:443", "vless")

        repo = ConfigCommentRepository(db_session)
        await repo.upsert_comment("sub-1", "hash-1", "A")
        await repo.upsert_comment("sub-1", "hash-2", "B")

        deleted = await repo.delete_for_subscription("sub-1")
        assert deleted == 2
        assert await repo.get_all_for_subscription("sub-1") == []


class TestUniqueConstraint:
    async def test_cannot_have_two_comments_for_same_sub_and_config_via_direct_create(
        self, db_session
    ):
        await _make_subscription_with_config(db_session)
        repo = ConfigCommentRepository(db_session)

        await repo.create(subscription_token="sub-1", config_hash="hash-1", comment="first")

        with pytest.raises(Exception):
            await repo.create(subscription_token="sub-1", config_hash="hash-1", comment="second")
