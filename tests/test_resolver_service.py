"""Tests for v2hub_api.services.resolver_service.ResolverService.

These tests use an in-memory SQLite database for subscriptions/sources/
comments (real repository behavior), and mock CacheService for external
URL fetching so no network access is required.
"""

from unittest.mock import AsyncMock

import pytest

from v2hub_api.core.enums import SourceType
from v2hub_api.db.repositories.config_comment_repository import ConfigCommentRepository
from v2hub_api.db.repositories.proxy_config import ProxyConfigRepository
from v2hub_api.db.repositories.source_repository import SourceRepository
from v2hub_api.db.repositories.subscription_repository import SubscriptionRepository
from v2hub_api.db.repositories.user_repository import UserRepository
from v2hub_api.services.resolver_service import ResolverService
from v2hub_api.utils.config_parser import get_config_hash

pytestmark = pytest.mark.asyncio


async def _make_user_and_subscription(session, token, user_hash="u1", user_id=1, api_token=None):
    user_repo = UserRepository(session)
    existing = await user_repo.get_by_hash(user_hash)
    if not existing:
        await user_repo.create_user(
            user_hash=user_hash, user_id=user_id, api_token=api_token or f"tok-{user_hash}"
        )
    return await SubscriptionRepository(session).create_subscription(
        token=token, name=f"name-{token}", user_hash=user_hash
    )


async def _add_config_source(
    session,
    subscription_token,
    config_uri,
    source_id=None,
    is_hidden=False,
    max_depth=3,
    order_index=0,
):
    config_hash = get_config_hash(config_uri)
    await ProxyConfigRepository(session).create_config(config_hash, config_uri, "vless")
    await SourceRepository(session).create_source(
        source_id=source_id or config_hash,
        subscription_token=subscription_token,
        source_type=SourceType.CONFIG.value,
        config_hash=config_hash,
        is_hidden=is_hidden,
        max_depth=max_depth,
        order_index=order_index,
    )
    return config_hash


async def _add_internal_source(
    session,
    subscription_token,
    target_token,
    source_id,
    is_hidden=False,
    max_depth=3,
    order_index=0,
):
    await SourceRepository(session).create_source(
        source_id=source_id,
        subscription_token=subscription_token,
        source_type=SourceType.INTERNAL_TOKEN.value,
        internal_token=target_token,
        is_hidden=is_hidden,
        max_depth=max_depth,
        order_index=order_index,
    )


async def _add_external_source(
    session, subscription_token, url, source_id, is_hidden=False, max_depth=3, order_index=0
):
    await SourceRepository(session).create_source(
        source_id=source_id,
        subscription_token=subscription_token,
        source_type=SourceType.EXTERNAL_URL.value,
        external_url=url,
        is_hidden=is_hidden,
        max_depth=max_depth,
        order_index=order_index,
    )


def _make_mock_cache(cache_contents: dict[str, str] | None = None):
    """Create a mock CacheService returning canned content for get_from_cache_only."""
    mock = AsyncMock()
    contents = cache_contents or {}

    async def _get_from_cache_only(url):
        return contents.get(url)

    mock.get_from_cache_only.side_effect = _get_from_cache_only
    return mock


class TestResolveSimpleConfig:
    async def test_resolves_single_config_source(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        config_hash = await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.count == 1
        assert result.configs[0].hash == config_hash
        assert result.configs[0].config == "vless://uuid1@host:443"
        assert result.truncated is False
        assert result.depth_exceeded is False

    async def test_resolve_missing_subscription_returns_empty(self, db_session):
        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("does-not-exist")

        assert result.count == 0
        assert result.configs == []

    async def test_multiple_config_sources_ordered(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        h1 = await _add_config_source(
            db_session, "sub-1", "vless://uuid1@host:443", source_id="s1", order_index=0
        )
        h2 = await _add_config_source(
            db_session, "sub-1", "vless://uuid2@host:443", source_id="s2", order_index=1
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert [c.hash for c in result.configs] == [h1, h2]


class TestResolveWithComments:
    async def test_appends_subscription_specific_comment(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        config_hash = await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443")
        await ConfigCommentRepository(db_session).upsert_comment("sub-1", config_hash, "My Server")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.configs[0].config == "vless://uuid1@host:443#My Server"

    async def test_no_comment_leaves_config_unmodified(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.configs[0].config == "vless://uuid1@host:443"


class TestResolveDeduplication:
    async def test_deduplicates_same_config_hash(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        config_hash = await _add_config_source(
            db_session, "sub-1", "vless://uuid1@host:443", source_id="s1"
        )

        # Second source pointing to the *same* proxy config
        from v2hub_api.db.repositories.source_repository import SourceRepository as SR

        await SR(db_session).create_source(
            source_id="s2",
            subscription_token="sub-1",
            source_type=SourceType.CONFIG.value,
            config_hash=config_hash,
            order_index=1,
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.count == 1


class TestResolveExternalUrl:
    async def test_resolves_configs_from_cached_content(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://example.com/sub", source_id="ext-1"
        )

        cache = _make_mock_cache(
            {"https://example.com/sub": "vless://uuid1@host:443\ntrojan://pass@host2:443\n"}
        )
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 2
        configs = {c.config for c in result.configs}
        assert "vless://uuid1@host:443" in configs
        assert "trojan://pass@host2:443" in configs

    async def test_no_cached_content_yields_nothing(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://example.com/sub", source_id="ext-1"
        )

        resolver = ResolverService(db_session, _make_mock_cache())  # empty cache
        result = await resolver.resolve("sub-1")

        assert result.count == 0

    async def test_missing_external_url_field_skipped(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        # Source with no external_url set (edge case / bad data)
        await SourceRepository(db_session).create_source(
            source_id="ext-bad",
            subscription_token="sub-1",
            source_type=SourceType.EXTERNAL_URL.value,
            external_url=None,
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.count == 0


class TestResolveInternalToken:
    async def test_resolves_nested_subscription(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")
        await _add_config_source(db_session, "sub-child", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.count == 1
        assert result.configs[0].config == "vless://uuid1@host:443"

    async def test_cycle_detection_stops_infinite_recursion(self, db_session):
        await _make_user_and_subscription(db_session, "sub-a")
        await _make_user_and_subscription(db_session, "sub-b", user_hash="u1")
        await _add_internal_source(db_session, "sub-a", "sub-b", source_id="ref-a-to-b")
        await _add_internal_source(db_session, "sub-b", "sub-a", source_id="ref-b-to-a")

        resolver = ResolverService(db_session, _make_mock_cache())
        # Should complete without hanging / raising RecursionError
        result = await resolver.resolve("sub-a")
        assert result.count == 0

    async def test_missing_internal_token_field_skipped(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await SourceRepository(db_session).create_source(
            source_id="ref-bad",
            subscription_token="sub-1",
            source_type=SourceType.INTERNAL_TOKEN.value,
            internal_token=None,
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")
        assert result.count == 0


class TestResolveDepthLimit:
    async def test_depth_exceeded_flag_set_when_nesting_too_deep(self, db_session, monkeypatch):
        # Build a chain sub-0 -> sub-1 -> sub-2 -> sub-3 -> sub-4, with max_depth patched to 2
        tokens = [f"sub-{i}" for i in range(5)]
        await _make_user_and_subscription(db_session, tokens[0])
        for t in tokens[1:]:
            await _make_user_and_subscription(db_session, t, user_hash="u1")

        for i in range(len(tokens) - 1):
            await _add_internal_source(db_session, tokens[i], tokens[i + 1], source_id=f"ref-{i}")

        # Final subscription has an actual config so we can tell if it was reached
        await _add_config_source(db_session, tokens[-1], "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        resolver.max_depth = 2  # override for test determinism

        result = await resolver.resolve(tokens[0])

        assert result.depth_exceeded is True
        assert result.count == 0  # never reached the deepest config

    async def test_source_max_depth_limits_visibility(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        # max_depth=0 on the internal-token source means it's only visible at depth 0
        await _add_internal_source(
            db_session, "sub-parent", "sub-child", source_id="ref-1", max_depth=0
        )
        await _add_config_source(db_session, "sub-child", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        # depth=0 <= source.max_depth(0) -> visible, so child *is* resolved once
        assert result.count == 1


class TestResolveConfigCountLimit:
    async def test_truncated_flag_set_when_max_configs_exceeded(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        for i in range(5):
            await _add_config_source(
                db_session, "sub-1", f"vless://uuid{i}@host:443", source_id=f"s{i}", order_index=i
            )

        resolver = ResolverService(db_session, _make_mock_cache())
        resolver.max_configs = 3  # override for test determinism

        result = await resolver.resolve("sub-1")

        assert result.truncated is True
        assert result.count == 3

    async def test_not_truncated_when_under_limit(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.truncated is False


class TestResolveHiddenSources:
    async def test_hidden_source_excluded_at_root_depth(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443", is_hidden=True)

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.count == 0

    async def test_hidden_source_visible_when_nested(self, db_session):
        # is_hidden only applies at depth == 0, per _process_source logic
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")
        await _add_config_source(db_session, "sub-child", "vless://uuid1@host:443", is_hidden=True)

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.count == 1


class TestResolveDescription:
    async def test_uses_subscription_description_when_present(self, db_session):
        user_repo = UserRepository(db_session)
        await user_repo.create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-1", name="n1", user_hash="u1", description="Custom Description"
        )
        await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.description == "Custom Description"

    async def test_falls_back_to_domain_when_no_description(self, db_session):
        from v2hub_api.core.config import settings

        await _make_user_and_subscription(db_session, "sub-1")
        await _add_config_source(db_session, "sub-1", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.description == settings.domain
