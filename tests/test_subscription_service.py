"""Tests for v2hub_api.services.subscription_service.SubscriptionService.

Uses an in-memory SQLite database for all repository operations. Calls
that would reach out to Redis/HTTP (via `CacheService`/`get_redis_client`,
imported lazily inside the service methods) are patched to avoid any
real network access.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from v2hub_api.core.enums import SourceType
from v2hub_api.core.exceptions import (
    AuthorizationError,
    AuthenticationError,
    CircularReferenceError,
    DuplicateNameError,
    InvalidConfigError,
    NotFoundError,
    SubscriptionNotFoundError,
    TooManySourcesError,
    TooManySubscriptionsError,
)
from v2hub_api.db.repositories.user_repository import UserRepository
from v2hub_api.schemas import SourceCreateRequest
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _patch_external_fetching(monkeypatch):
    """
    Prevent any real Redis/HTTP calls triggered from inside
    SubscriptionService for EXTERNAL_URL sources (`get_redis_client` +
    `CacheService.refresh`), and from SubscriptionHTTPClient's static URL
    validation, which are exercised as part of adding external sources.
    """
    import v2hub_api.services.cache_service as cache_service_module

    async def _fake_get_redis_client():
        return None

    fake_cache_instance = AsyncMock()
    fake_cache_instance.refresh = AsyncMock(return_value="mocked-content")
    # CacheService(...) is a synchronous constructor call that returns an
    # instance immediately -- it must NOT be an AsyncMock itself, or calling
    # it would return a coroutine instead of fake_cache_instance.
    fake_cache_service_cls = MagicMock(return_value=fake_cache_instance)

    monkeypatch.setattr(cache_service_module, "get_redis_client", _fake_get_redis_client)
    monkeypatch.setattr(cache_service_module, "CacheService", fake_cache_service_cls)

    yield


async def _make_user(session, user_hash="u1", user_id=1, api_token="tok1"):
    return await UserRepository(session).create_user(
        user_hash=user_hash, user_id=user_id, api_token=api_token
    )


class TestCreateSubscription:
    async def test_creates_subscription_with_no_sources(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)

        sub = await service.create_subscription(user_hash="u1", name="My Sub")

        assert sub.name == "My Sub"
        assert sub.user_hash == "u1"
        assert sub.sources == []

    async def test_raises_duplicate_name_error(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        await service.create_subscription(user_hash="u1", name="Dup")

        with pytest.raises(DuplicateNameError):
            await service.create_subscription(user_hash="u1", name="Dup")

    async def test_raises_too_many_subscriptions(self, db_session, monkeypatch):
        from v2hub_api.core.config import settings

        monkeypatch.setattr(settings, "max_subscriptions_per_user", 1)
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        await service.create_subscription(user_hash="u1", name="First")

        with pytest.raises(TooManySubscriptionsError):
            await service.create_subscription(user_hash="u1", name="Second")

    async def test_creates_with_initial_config_source(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)

        sub = await service.create_subscription(
            user_hash="u1",
            name="With Config",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
        )

        assert len(sub.sources) == 1
        assert sub.sources[0].source_type == SourceType.CONFIG.value


class TestGetSubscription:
    async def test_returns_owned_subscription(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        created = await service.create_subscription(user_hash="u1", name="Mine")

        found = await service.get_subscription(
            token=created.token,
            user_hash="u1",
        )
        assert found.token == created.token

    async def test_raises_not_found_for_missing_token(self, db_session):
        service = SubscriptionService(db_session)
        with pytest.raises(SubscriptionNotFoundError):
            await service.get_subscription(token="missing-token", user_hash="u1")

    async def test_raises_authorization_error_for_other_user(self, db_session):
        await _make_user(db_session, user_hash="u1", user_id=1, api_token="t1")
        await _make_user(db_session, user_hash="u2", user_id=2, api_token="t2")
        service = SubscriptionService(db_session)
        created = await service.create_subscription(user_hash="u1", name="Mine")

        with pytest.raises(AuthorizationError):
            await service.get_subscription(token=created.token, user_hash="u2")


class TestListSubscriptions:
    async def test_lists_only_users_subscriptions(self, db_session):
        await _make_user(db_session, user_hash="u1", user_id=1, api_token="t1")
        await _make_user(db_session, user_hash="u2", user_id=2, api_token="t2")
        service = SubscriptionService(db_session)

        await service.create_subscription(user_hash="u1", name="A")
        await service.create_subscription(user_hash="u2", name="B")

        subs = await service.list_subscriptions(user_hash="u1")
        assert len(subs) == 1
        assert subs[0].name == "A"


class TestUpdateSubscription:
    async def test_updates_name_and_description(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        created = await service.create_subscription(user_hash="u1", name="Old Name")

        updated = await service.update_subscription(
            token=created.token, user_hash="u1", name="New Name", description="New Desc"
        )

        assert updated.name == "New Name"
        assert updated.description == "New Desc"

    async def test_raises_duplicate_name_on_conflict(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        await service.create_subscription(user_hash="u1", name="Taken")
        sub2 = await service.create_subscription(user_hash="u1", name="Other")

        with pytest.raises(DuplicateNameError):
            await service.update_subscription(token=sub2.token, user_hash="u1", name="Taken")

    async def test_no_op_update_does_not_raise(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        created = await service.create_subscription(user_hash="u1", name="Same")

        updated = await service.update_subscription(
            token=created.token, user_hash="u1", name="Same"
        )
        assert updated.name == "Same"


class TestDeleteSubscription:
    async def test_deletes_subscription(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        created = await service.create_subscription(user_hash="u1", name="ToDelete")

        await service.delete_subscription(created.token, "u1")

        with pytest.raises(SubscriptionNotFoundError):
            await service.get_subscription(token=created.token, user_hash="u1")

    async def test_raises_authorization_error_for_other_user(self, db_session):
        await _make_user(db_session, user_hash="u1", user_id=1, api_token="t1")
        await _make_user(db_session, user_hash="u2", user_id=2, api_token="t2")
        service = SubscriptionService(db_session)
        created = await service.create_subscription(user_hash="u1", name="Mine")

        with pytest.raises(AuthorizationError):
            await service.delete_subscription(created.token, "u2")


class TestAddSourcesConfig:
    # NOTE: `SourceCreateRequest.is_hidden`/`max_depth` default to `None`,
    # which is passed straight through to `Source.is_hidden`
    # (`nullable=False`, default=False) / `Source.max_depth`
    # (`nullable=False`, default=3). If this test starts failing with an
    # IntegrityError/NOT NULL constraint failure after a refactor, it means
    # the "pass None through to a NOT NULL column with a Python-side
    # default" behavior changed — worth checking whether that was
    # intentional in the original code, since explicitly assigning `None`
    # bypasses SQLAlchemy's Python-side column default.
    async def test_adds_config_source(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        updated = await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443#MyServer")],
        )

        assert len(updated.sources) == 1
        source = updated.sources[0]
        assert source.source_type == SourceType.CONFIG.value

    async def test_adding_same_config_twice_deduplicates(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        config = f"vless://{VALID_UUID}@host:443"
        await service.add_sources(
            token=sub.token, user_hash="u1", sources=[SourceCreateRequest(data=config)]
        )
        updated = await service.add_sources(
            token=sub.token, user_hash="u1", sources=[SourceCreateRequest(data=config)]
        )

        assert len(updated.sources) == 1

    async def test_invalid_config_raises(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        with pytest.raises(InvalidConfigError):
            await service.add_sources(
                token=sub.token,
                user_hash="u1",
                sources=[SourceCreateRequest(data="not-a-valid-source")],
            )

    async def test_too_many_sources_raises(self, db_session, monkeypatch):
        from v2hub_api.core.config import settings

        monkeypatch.setattr(settings, "max_sources_per_subscription", 1)
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
        )

        with pytest.raises(TooManySourcesError):
            await service.add_sources(
                token=sub.token,
                user_hash="u1",
                sources=[SourceCreateRequest(data="trojan://pass@host2:443")],
            )


class TestAddSourcesExternalUrl:
    async def test_adds_external_url_source(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        updated = await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data="https://example.com/sub")],
        )

        assert len(updated.sources) == 1
        assert updated.sources[0].source_type == SourceType.EXTERNAL_URL.value
        assert updated.sources[0].external_url == "https://example.com/sub"

    async def test_private_ip_url_rejected(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        with pytest.raises(Exception):
            await service.add_sources(
                token=sub.token,
                user_hash="u1",
                sources=[SourceCreateRequest(data="http://127.0.0.1/sub")],
            )


class TestAddSourcesInternalToken:
    async def test_adds_internal_token_source(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        target = await service.create_subscription(user_hash="u1", name="Target")
        owner = await service.create_subscription(user_hash="u1", name="Owner")

        from v2hub_api.core.config import settings

        internal_url = f"https://{settings.domain}/sub/{target.token}"

        updated = await service.add_sources(
            token=owner.token, user_hash="u1", sources=[SourceCreateRequest(data=internal_url)]
        )

        assert len(updated.sources) == 1
        assert updated.sources[0].source_type == SourceType.INTERNAL_TOKEN.value
        assert updated.sources[0].internal_token == target.token

    async def test_direct_self_reference_raises_circular_error(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        from v2hub_api.core.config import settings

        internal_url = f"https://{settings.domain}/sub/{sub.token}"

        with pytest.raises(CircularReferenceError):
            await service.add_sources(
                token=sub.token, user_hash="u1", sources=[SourceCreateRequest(data=internal_url)]
            )

    async def test_two_hop_cycle_raises_circular_error(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub_a = await service.create_subscription(user_hash="u1", name="A")
        sub_b = await service.create_subscription(user_hash="u1", name="B")

        from v2hub_api.core.config import settings

        # a -> b
        await service.add_sources(
            token=sub_a.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"https://{settings.domain}/sub/{sub_b.token}")],
        )

        # b -> a should be rejected (would create a cycle)
        with pytest.raises(CircularReferenceError):
            await service.add_sources(
                token=sub_b.token,
                user_hash="u1",
                sources=[SourceCreateRequest(data=f"https://{settings.domain}/sub/{sub_a.token}")],
            )

    async def test_nonexistent_target_subscription_raises(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        from v2hub_api.core.config import settings

        with pytest.raises(SubscriptionNotFoundError):
            await service.add_sources(
                token=sub.token,
                user_hash="u1",
                sources=[SourceCreateRequest(data=f"https://{settings.domain}/sub/does-not-exist")],
            )


class TestRemoveSources:
    async def test_removes_specified_sources(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")
        updated = await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
        )
        source_id = updated.sources[0].id

        result = await service.remove_sources(
            token=sub.token, user_hash="u1", source_ids=[source_id]
        )
        assert result.sources == []


class TestReplaceSources:
    async def test_replaces_all_sources(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
        )

        new_config = "trojan://password@host2:443"
        replaced = await service.replace_sources(
            token=sub.token, user_hash="u1", sources=[SourceCreateRequest(data=new_config)]
        )

        assert len(replaced.sources) == 1
        assert replaced.sources[0].source_type == SourceType.CONFIG.value


class TestCheckSource:
    async def test_returns_true_when_present(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")
        updated = await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
        )

        result = await service.check_source(updated, updated.sources[0].id)
        assert result is True

    async def test_raises_not_found_when_missing(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")

        with pytest.raises(NotFoundError):
            await service.check_source(sub, "does-not-exist")


class TestUpdateConfigComment:
    async def test_updates_comment(self, db_session):
        await _make_user(db_session)
        service = SubscriptionService(db_session)
        sub = await service.create_subscription(user_hash="u1", name="Sub")
        updated = await service.add_sources(
            token=sub.token,
            user_hash="u1",
            sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
        )
        config_hash = updated.sources[0].id

        await service.update_config_comment(
            token=sub.token, user_hash="u1", config_hash=config_hash, comment="New Comment"
        )

        comment = await service.comment_repo.get_comment(sub.token, config_hash)
        assert comment is not None
        assert comment.comment == "New Comment"


class TestExtractToken:
    # extract_token is a sync staticmethod; override the module-level
    # asyncio marker (empty list = no markers) to avoid a PytestWarning.
    pytestmark = []

    def test_extracts_token_from_url(self):
        token = SubscriptionService.extract_token("https://example.com/sub/abc123")
        assert token == "abc123"

    def test_raises_when_no_token_segment(self):
        with pytest.raises(SubscriptionNotFoundError):
            SubscriptionService.extract_token("https://example.com/other/path")

    def test_raises_when_trailing_slash_with_no_token(self):
        with pytest.raises(SubscriptionNotFoundError):
            SubscriptionService.extract_token("https://example.com/sub/")


class TestAuthenticateUser:
    async def test_succeeds_for_active_user(self, db_session):
        await _make_user(db_session, api_token="valid-token")
        service = UserService(db_session)

        user = await service.authenticate_user("valid-token")
        assert user.user_hash == "u1"

    async def test_raises_for_invalid_token(self, db_session):
        service = UserService(db_session)
        with pytest.raises(AuthenticationError):
            await service.authenticate_user("bad-token")

    async def test_raises_for_inactive_user(self, db_session):
        user_repo = UserRepository(db_session)
        await user_repo.create_user(user_hash="u1", user_id=1, api_token="tok", is_active=False)
        service = UserService(db_session)

        with pytest.raises(AuthenticationError):
            await service.authenticate_user("tok")
