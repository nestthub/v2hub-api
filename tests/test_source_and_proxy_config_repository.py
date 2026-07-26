"""Tests for SourceRepository and ProxyConfigRepository."""

import pytest

from v2hub_api.core.enums import SourceType
from v2hub_api.db.repositories.proxy_config import ProxyConfigRepository
from v2hub_api.db.repositories.source_repository import SourceRepository
from v2hub_api.db.repositories.subscription_repository import SubscriptionRepository
from v2hub_api.db.repositories.user_repository import UserRepository

pytestmark = pytest.mark.asyncio


async def _make_subscription(session, token="sub-1", user_hash="u1"):
    user_repo = UserRepository(session)
    existing = await user_repo.get_by_hash(user_hash)
    if not existing:
        # Derive a stable, unique user_id/api_token per user_hash so tests
        # that create multiple users (e.g. "u1", "u2") don't collide.
        suffix = abs(hash(user_hash)) % 1_000_000
        await user_repo.create_user(
            user_hash=user_hash, user_id=suffix, api_token=f"tok-{user_hash}"
        )
    return await SubscriptionRepository(session).create_subscription(
        token=token, name="n1", user_hash=user_hash
    )


async def _make_proxy_config(
    session, config_hash="hash-abc", config_data="vless://uuid@host:443", protocol="vless"
):
    return await ProxyConfigRepository(session).create_config(
        config_hash=config_hash, config_data=config_data, protocol=protocol
    )


class TestProxyConfigRepository:
    async def test_create_config(self, db_session):
        repo = ProxyConfigRepository(db_session)
        cfg = await repo.create_config("h1", "vless://uuid@host:443", "vless")

        assert cfg.config_hash == "h1"
        assert cfg.config_data == "vless://uuid@host:443"
        assert cfg.protocol == "vless"

    async def test_create_config_is_idempotent(self, db_session):
        repo = ProxyConfigRepository(db_session)
        first = await repo.create_config("h1", "vless://uuid@host:443", "vless")
        second = await repo.create_config("h1", "vless://different@host:443", "vless")

        # create_config returns the *existing* row untouched on conflict
        assert second.config_hash == first.config_hash
        assert second.config_data == "vless://uuid@host:443"

    async def test_get_by_hash(self, db_session):
        repo = ProxyConfigRepository(db_session)
        await repo.create_config("h1", "vless://uuid@host:443", "vless")

        found = await repo.get_by_hash("h1")
        assert found is not None
        assert found.protocol == "vless"

    async def test_get_by_hash_missing(self, db_session):
        repo = ProxyConfigRepository(db_session)
        assert await repo.get_by_hash("missing") is None

    async def test_get_or_create_same_as_create_config(self, db_session):
        repo = ProxyConfigRepository(db_session)
        first = await repo.get_or_create("h1", "vless://uuid@host:443", "vless")
        second = await repo.get_or_create("h1", "vless://uuid@host:443", "vless")
        assert first.config_hash == second.config_hash


class TestSourceRepositoryCreate:
    async def test_create_config_source(self, db_session):
        await _make_subscription(db_session)
        await _make_proxy_config(db_session)
        repo = SourceRepository(db_session)

        source = await repo.create_source(
            source_id="src-1",
            subscription_token="sub-1",
            source_type=SourceType.CONFIG.value,
            config_hash="hash-abc",
        )

        assert source.id == "src-1"
        assert source.source_type == "config"
        assert source.config_hash == "hash-abc"
        assert source.is_hidden is False
        assert source.max_depth == 3

    async def test_create_external_url_source(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)

        source = await repo.create_source(
            source_id="src-2",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://example.com/sub",
        )

        assert source.source_type == "external_url"
        assert source.external_url == "https://example.com/sub"

    async def test_create_internal_token_source(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)

        source = await repo.create_source(
            source_id="src-3",
            subscription_token="sub-1",
            source_type=SourceType.INTERNAL_TOKEN.value,
            internal_token="other-sub-token",
        )

        assert source.source_type == "internal_token"
        assert source.internal_token == "other-sub-token"


class TestSourceRepositoryQueries:
    async def test_get_by_subscription_orders_by_order_index(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)

        await repo.create_source(
            source_id="s2",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://b.com",
            order_index=2,
        )
        await repo.create_source(
            source_id="s1",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://a.com",
            order_index=1,
        )

        sources = await repo.get_by_subscription("sub-1")
        assert [s.id for s in sources] == ["s1", "s2"]

    async def test_get_existing_ids(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)
        await repo.create_source(
            source_id="s1",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://a.com",
        )

        ids = await repo.get_existing_ids("sub-1")
        assert ids == ["s1"]

    async def test_get_config(self, db_session):
        await _make_subscription(db_session)
        await _make_proxy_config(db_session)
        repo = SourceRepository(db_session)
        await repo.create_source(
            source_id="hash-abc",
            subscription_token="sub-1",
            source_type=SourceType.CONFIG.value,
            config_hash="hash-abc",
        )

        found = await repo.get_config("sub-1", "hash-abc")
        assert found is not None
        assert found.id == "hash-abc"

    async def test_get_config_missing_returns_none(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)
        assert await repo.get_config("sub-1", "missing") is None


class TestSourceRepositoryUpsertConfig:
    async def test_upsert_config_updates_fields(self, db_session):
        await _make_subscription(db_session)
        await _make_proxy_config(db_session)
        repo = SourceRepository(db_session)
        await repo.create_source(
            source_id="hash-abc",
            subscription_token="sub-1",
            source_type=SourceType.CONFIG.value,
            config_hash="hash-abc",
            is_hidden=False,
            max_depth=3,
            order_index=0,
        )

        updated = await repo.upsert_config(
            subscription_token="sub-1",
            config_hash="hash-abc",
            is_hidden=True,
            max_depth=1,
            order_index=5,
        )

        assert updated.is_hidden is True
        assert updated.max_depth == 1
        assert updated.order_index == 5

    async def test_upsert_config_returns_none_for_missing_source(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)

        result = await repo.upsert_config(
            subscription_token="sub-1", config_hash="does-not-exist", is_hidden=True
        )
        assert result is None

    async def test_upsert_config_with_no_kwargs_returns_none(self, db_session):
        await _make_subscription(db_session)
        await _make_proxy_config(db_session)
        repo = SourceRepository(db_session)
        await repo.create_source(
            source_id="hash-abc",
            subscription_token="sub-1",
            source_type=SourceType.CONFIG.value,
            config_hash="hash-abc",
        )

        result = await repo.upsert_config(subscription_token="sub-1", config_hash="hash-abc")
        assert result is None


class TestSourceRepositoryDelete:
    async def test_delete_all_for_subscription(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)
        await repo.create_source(
            source_id="s1",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://a.com",
        )
        await repo.create_source(
            source_id="s2",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://b.com",
        )

        deleted_count = await repo.delete_all_for_subscription("sub-1")
        assert deleted_count == 2
        assert await repo.get_by_subscription("sub-1") == []

    async def test_delete_by_ids(self, db_session):
        await _make_subscription(db_session)
        repo = SourceRepository(db_session)
        await repo.create_source(
            source_id="s1",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://a.com",
        )
        await repo.create_source(
            source_id="s2",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://b.com",
        )

        deleted_count = await repo.delete_by_ids("sub-1", ["s1"])
        assert deleted_count == 1

        remaining_ids = await repo.get_existing_ids("sub-1")
        assert remaining_ids == ["s2"]

    async def test_delete_internal_references(self, db_session):
        await _make_subscription(db_session, token="sub-1")
        await _make_subscription(db_session, token="sub-2", user_hash="u2")
        repo = SourceRepository(db_session)

        # sub-2 references sub-1 internally
        await repo.create_source(
            source_id="ref",
            subscription_token="sub-2",
            source_type=SourceType.INTERNAL_TOKEN.value,
            internal_token="sub-1",
        )

        await repo.delete_internal_references("sub-1")
        await db_session.flush()

        remaining = await repo.get_by_subscription("sub-2")
        assert remaining == []


class TestSourceRepositoryGetUniqueIds:
    async def test_returns_only_ids_that_appear_once(self, db_session):
        await _make_subscription(db_session, token="sub-1")
        await _make_subscription(db_session, token="sub-2", user_hash="u2")
        repo = SourceRepository(db_session)

        # "dup" appears in two different subscriptions -> not unique
        await repo.create_source(
            source_id="dup",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://a.com",
        )
        await repo.create_source(
            source_id="dup",
            subscription_token="sub-2",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://b.com",
        )
        await repo.create_source(
            source_id="unique-id",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://c.com",
        )

        unique_ids = await repo.get_unique_ids({"dup", "unique-id"})
        assert unique_ids == {"unique-id"}


class TestCascadeDeleteSubscription:
    async def test_deleting_subscription_cascades_sources(self, db_session):
        await _make_subscription(db_session)
        source_repo = SourceRepository(db_session)
        sub_repo = SubscriptionRepository(db_session)

        await source_repo.create_source(
            source_id="s1",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url="https://a.com",
        )

        sub = await sub_repo.get_by_token("sub-1")
        await sub_repo.delete(sub)

        remaining = await source_repo.get_by_subscription("sub-1")
        assert remaining == []
