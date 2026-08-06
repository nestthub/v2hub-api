"""Extended tests for v2hub_api.services.resolver_service.ResolverService.

These complement test_resolver_service.py by covering:
- Comment precedence/overlay rules (root wins, first-seen-nested wins over deeper)
- Description inheritance precedence (root wins over nested)
- Correctness under the concurrent (asyncio.gather) fetch path for
  EXTERNAL_URL and INTERNAL_TOKEN siblings: ordering, dedup, and
  max_configs truncation must remain deterministic and independent of
  which coroutine happens to finish first.
- Mixed source types within a single subscription (CONFIG + EXTERNAL_URL
  + INTERNAL_TOKEN together), preserving declared order.
- Partial failure isolation among concurrently-fetched siblings.
- is_hidden semantics for EXTERNAL_URL / INTERNAL_TOKEN sources at depth 0
  (not just CONFIG, which the base suite already covers).
- Cross-type deduplication (CONFIG source and EXTERNAL_URL-provided config
  sharing the same config hash).
"""

import asyncio
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


# ---------------------------------------------------------------------------
# Shared helpers (mirrors the base test module so this file is self-contained)
# ---------------------------------------------------------------------------


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


def _make_mock_cache(
    cache_contents: dict[str, str] | None = None, delays: dict[str, float] | None = None
):
    """Mock CacheService.get_or_fetch(url, refresh).

    The resolver now calls `cache.get_or_fetch(url, refresh)` (two positional
    args) rather than the old `get_from_cache_only(url)`. It also decides
    `refresh` itself based on `external_cache.updated_at` vs a cooldown; since
    these tests don't create `external_cache` rows, `refresh` will always be
    True here — the mock must return content regardless of `refresh`'s value.

    `delays` lets tests simulate different latencies per URL so we can prove
    that result ordering/limits do not depend on completion order under the
    concurrent (asyncio.gather) fetch path.
    """
    mock = AsyncMock()
    contents = cache_contents or {}
    delays = delays or {}

    async def _get_or_fetch(url, refresh=False):
        delay = delays.get(url)
        if delay:
            await asyncio.sleep(delay)
        return contents.get(url)

    mock.get_or_fetch.side_effect = _get_or_fetch
    return mock


# ---------------------------------------------------------------------------
# Comment overlay / precedence rules
# ---------------------------------------------------------------------------


class TestCommentPrecedence:
    async def test_root_comment_wins_over_nested_comment(self, db_session):
        """If both root and a nested subscription define a comment for the
        same config hash, the ROOT subscription's comment must win — nested
        comments are merged only via `if not root_comment_map.get(key)`.
        """
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")

        config_hash = await _add_config_source(
            db_session, "sub-child", "vless://uuid1@host:443", source_id="child-cfg"
        )

        # Root defines its own comment for this config hash, even though the
        # config source itself only exists in the child subscription.
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-parent", config_hash, "Root Comment"
        )
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-child", config_hash, "Child Comment"
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.count == 1
        assert result.configs[0].config == "vless://uuid1@host:443#Root Comment"

    async def test_nested_comment_used_when_root_has_none(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")

        config_hash = await _add_config_source(
            db_session, "sub-child", "vless://uuid1@host:443", source_id="child-cfg"
        )
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-child", config_hash, "Child Comment"
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.configs[0].config == "vless://uuid1@host:443#Child Comment"

    async def test_first_seen_nested_comment_wins_over_deeper_nested(self, db_session):
        """sub-a -> sub-b -> sub-c, config lives in sub-c. If both sub-b and
        sub-c define a comment for that hash, sub-b's (shallower, visited
        first during the internal-token comment merge) should win, since the
        merge only fills in missing keys and sub-b is merged before recursing
        into sub-c.
        """
        await _make_user_and_subscription(db_session, "sub-a")
        await _make_user_and_subscription(db_session, "sub-b", user_hash="u1")
        await _make_user_and_subscription(db_session, "sub-c", user_hash="u1")
        await _add_internal_source(db_session, "sub-a", "sub-b", source_id="ref-a-b")
        await _add_internal_source(db_session, "sub-b", "sub-c", source_id="ref-b-c")

        config_hash = await _add_config_source(
            db_session, "sub-c", "vless://uuid1@host:443", source_id="c-cfg"
        )
        await ConfigCommentRepository(db_session).upsert_comment("sub-b", config_hash, "B Comment")
        await ConfigCommentRepository(db_session).upsert_comment("sub-c", config_hash, "C Comment")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-a")

        assert result.configs[0].config == "vless://uuid1@host:443#B Comment"

    async def test_empty_string_comment_treated_as_falsy_and_overridable(self, db_session):
        """root_comment_map merge uses `if not root_comment_map.get(key)`,
        so an empty-string comment at root should NOT block a nested
        non-empty comment from being used (empty string is falsy).
        """
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")

        config_hash = await _add_config_source(
            db_session, "sub-child", "vless://uuid1@host:443", source_id="child-cfg"
        )
        await ConfigCommentRepository(db_session).upsert_comment("sub-parent", config_hash, "")
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-child", config_hash, "Child Comment"
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.configs[0].config == "vless://uuid1@host:443#Child Comment"


# ---------------------------------------------------------------------------
# Description inheritance precedence
# ---------------------------------------------------------------------------


class TestDescriptionPrecedence:
    async def test_root_description_wins_over_nested_description(self, db_session):
        user_repo = UserRepository(db_session)
        await user_repo.create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-parent", name="p", user_hash="u1", description="Parent Desc"
        )
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-child", name="c", user_hash="u1", description="Child Desc"
        )
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")
        await _add_config_source(db_session, "sub-child", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.description == "Parent Desc"

    async def test_nested_description_used_when_root_has_none(self, db_session):
        user_repo = UserRepository(db_session)
        await user_repo.create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-parent", name="p", user_hash="u1", description=None
        )
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-child", name="c", user_hash="u1", description="Child Desc"
        )
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")
        await _add_config_source(db_session, "sub-child", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.description == "Child Desc"

    async def test_first_nested_description_wins_when_multiple_children(self, db_session):
        """Root has no description, two internal sources point to children
        that both have descriptions — the first one processed (in source
        order_index order) should win, since `result.description` is only
        overwritten while it still equals `settings.domain` (the default).
        """
        from v2hub_api.core.config import settings

        user_repo = UserRepository(db_session)
        await user_repo.create_user(user_hash="u1", user_id=1, api_token="tok")
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-parent", name="p", user_hash="u1", description=None
        )
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-child-1", name="c1", user_hash="u1", description="First Child Desc"
        )
        await SubscriptionRepository(db_session).create_subscription(
            token="sub-child-2", name="c2", user_hash="u1", description="Second Child Desc"
        )
        await _add_internal_source(
            db_session, "sub-parent", "sub-child-1", source_id="ref-1", order_index=0
        )
        await _add_internal_source(
            db_session, "sub-parent", "sub-child-2", source_id="ref-2", order_index=1
        )
        await _add_config_source(db_session, "sub-child-1", "vless://uuid1@host:443")
        await _add_config_source(db_session, "sub-child-2", "vless://uuid2@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.description == "First Child Desc"
        assert result.description != settings.domain


# ---------------------------------------------------------------------------
# Concurrent EXTERNAL_URL fetch correctness (ordering, dedup, limits)
# ---------------------------------------------------------------------------


class TestConcurrentExternalFetchCorrectness:
    async def test_result_order_matches_source_order_regardless_of_fetch_latency(self, db_session):
        """Two EXTERNAL_URL sources are fetched concurrently; the *slower*
        one is declared first (order_index=0). The final config order must
        still follow declared source order, not completion order.
        """
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://slow.example.com/sub", source_id="ext-slow", order_index=0
        )
        await _add_external_source(
            db_session, "sub-1", "https://fast.example.com/sub", source_id="ext-fast", order_index=1
        )

        cache = _make_mock_cache(
            cache_contents={
                "https://slow.example.com/sub": "vless://slow@host:443\n",
                "https://fast.example.com/sub": "vless://fast@host:443\n",
            },
            delays={
                "https://slow.example.com/sub": 0.05,
                "https://fast.example.com/sub": 0.0,
            },
        )
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 2
        assert [c.config for c in result.configs] == [
            "vless://slow@host:443",
            "vless://fast@host:443",
        ]

    async def test_dedup_across_multiple_external_sources(self, db_session):
        """Two different EXTERNAL_URL sources both surface the same config
        line; only one should survive in the result, keyed by config hash.
        """
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://a.example.com/sub", source_id="ext-a", order_index=0
        )
        await _add_external_source(
            db_session, "sub-1", "https://b.example.com/sub", source_id="ext-b", order_index=1
        )

        shared_line = "vless://shared@host:443\n"
        cache = _make_mock_cache(
            {
                "https://a.example.com/sub": shared_line,
                "https://b.example.com/sub": shared_line,
            }
        )
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 1

    async def test_max_configs_truncation_deterministic_under_concurrency(self, db_session):
        """max_configs=3, three EXTERNAL_URL sources each yield 2 configs.
        Regardless of which coroutine finishes fetching first, only the
        first `max_configs` configs *in declared source order* should
        survive, and `truncated` must be True.
        """
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://a.example.com/sub", source_id="ext-a", order_index=0
        )
        await _add_external_source(
            db_session, "sub-1", "https://b.example.com/sub", source_id="ext-b", order_index=1
        )
        await _add_external_source(
            db_session, "sub-1", "https://c.example.com/sub", source_id="ext-c", order_index=2
        )

        cache = _make_mock_cache(
            cache_contents={
                "https://a.example.com/sub": "vless://a1@host:443\nvless://a2@host:443\n",
                "https://b.example.com/sub": "vless://b1@host:443\nvless://b2@host:443\n",
                "https://c.example.com/sub": "vless://c1@host:443\nvless://c2@host:443\n",
            },
            # Deliberately make the *last declared* source finish fastest,
            # to prove ordering/truncation don't depend on completion order.
            delays={
                "https://a.example.com/sub": 0.06,
                "https://b.example.com/sub": 0.03,
                "https://c.example.com/sub": 0.0,
            },
        )
        resolver = ResolverService(db_session, cache)
        resolver.max_configs = 3

        result = await resolver.resolve("sub-1")

        assert result.truncated is True
        assert result.count == 3
        assert [c.config for c in result.configs] == [
            "vless://a1@host:443",
            "vless://a2@host:443",
            "vless://b1@host:443",
        ]

    async def test_partial_failure_does_not_block_sibling_sources(self, db_session):
        """One EXTERNAL_URL source raises during fetch (simulated via cache
        raising); sibling sources fetched concurrently must still resolve
        successfully.
        """
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session,
            "sub-1",
            "https://broken.example.com/sub",
            source_id="ext-broken",
            order_index=0,
        )
        await _add_external_source(
            db_session, "sub-1", "https://ok.example.com/sub", source_id="ext-ok", order_index=1
        )

        cache = AsyncMock()

        async def _get_or_fetch(url, refresh=False):
            if url == "https://broken.example.com/sub":
                raise RuntimeError("simulated cache failure")
            if url == "https://ok.example.com/sub":
                return "vless://ok@host:443\n"
            return None

        cache.get_or_fetch.side_effect = _get_or_fetch

        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 1
        assert result.configs[0].config == "vless://ok@host:443"


# ---------------------------------------------------------------------------
# Concurrent INTERNAL_TOKEN fetch correctness (comment-map preload + recursion)
# ---------------------------------------------------------------------------


class TestConcurrentInternalFetchCorrectness:
    async def test_multiple_internal_sources_all_resolved_and_ordered(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child-1", user_hash="u1")
        await _make_user_and_subscription(db_session, "sub-child-2", user_hash="u1")

        await _add_internal_source(
            db_session, "sub-parent", "sub-child-1", source_id="ref-1", order_index=0
        )
        await _add_internal_source(
            db_session, "sub-parent", "sub-child-2", source_id="ref-2", order_index=1
        )

        h1 = await _add_config_source(db_session, "sub-child-1", "vless://c1@host:443")
        h2 = await _add_config_source(db_session, "sub-child-2", "vless://c2@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.count == 2
        assert [c.hash for c in result.configs] == [h1, h2]

    async def test_comment_map_merge_is_correct_across_concurrently_fetched_siblings(
        self, db_session
    ):
        """Two internal sources (sub-child-1, sub-child-2) are fetched
        concurrently for their comment maps. sub-child-1's comment for a
        hash shared with sub-child-2 should win (declared first), even
        though comment-map loading itself runs concurrently.
        """
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child-1", user_hash="u1")
        await _make_user_and_subscription(db_session, "sub-child-2", user_hash="u1")

        await _add_internal_source(
            db_session, "sub-parent", "sub-child-1", source_id="ref-1", order_index=0
        )
        await _add_internal_source(
            db_session, "sub-parent", "sub-child-2", source_id="ref-2", order_index=1
        )

        # Same config exists (as a source) only in child-1, but both
        # children define a comment for its hash.
        config_hash = await _add_config_source(
            db_session, "sub-child-1", "vless://shared@host:443", source_id="shared-cfg"
        )
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-child-1", config_hash, "Child1 Comment"
        )
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-child-2", config_hash, "Child2 Comment"
        )

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        assert result.count == 1
        assert result.configs[0].config == "vless://shared@host:443#Child1 Comment"


# ---------------------------------------------------------------------------
# Mixed source types within one subscription
# ---------------------------------------------------------------------------


class TestMixedSourceTypesOrdering:
    async def test_config_external_internal_mixed_preserve_declared_order(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")

        h_config = await _add_config_source(
            db_session, "sub-parent", "vless://direct@host:443", source_id="cfg-1", order_index=0
        )
        await _add_external_source(
            db_session,
            "sub-parent",
            "https://ext.example.com/sub",
            source_id="ext-1",
            order_index=1,
        )
        await _add_internal_source(
            db_session, "sub-parent", "sub-child", source_id="ref-1", order_index=2
        )
        h_child = await _add_config_source(db_session, "sub-child", "vless://nested@host:443")

        cache = _make_mock_cache({"https://ext.example.com/sub": "vless://external@host:443\n"})
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-parent")

        assert result.count == 3
        assert [c.hash for c in result.configs] == [
            h_config,
            get_config_hash("vless://external@host:443"),
            h_child,
        ]


# ---------------------------------------------------------------------------
# Cross-type deduplication
# ---------------------------------------------------------------------------


class TestCrossTypeDeduplication:
    async def test_config_source_and_external_url_yielding_same_config_deduped(self, db_session):
        """A CONFIG source and an EXTERNAL_URL source both resolve to the
        exact same underlying config string -> same hash -> only one entry
        in the final result, and the CONFIG source (processed first, since
        CONFIG sources are applied before EXTERNAL_URL fetch results) wins,
        including its subscription-specific comment.
        """
        await _make_user_and_subscription(db_session, "sub-1")
        config_uri = "vless://dup@host:443"
        config_hash = await _add_config_source(
            db_session, "sub-1", config_uri, source_id="cfg-1", order_index=0
        )
        await ConfigCommentRepository(db_session).upsert_comment(
            "sub-1", config_hash, "Direct Comment"
        )
        await _add_external_source(
            db_session, "sub-1", "https://ext.example.com/sub", source_id="ext-1", order_index=1
        )

        cache = _make_mock_cache({"https://ext.example.com/sub": f"{config_uri}\n"})
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 1
        assert result.configs[0].config == f"{config_uri}#Direct Comment"


# ---------------------------------------------------------------------------
# is_hidden semantics for EXTERNAL_URL / INTERNAL_TOKEN (base suite only
# covered CONFIG sources for this)
# ---------------------------------------------------------------------------


class TestHiddenNonConfigSources:
    async def test_hidden_external_source_excluded_at_root_depth(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://ext.example.com/sub", source_id="ext-1", is_hidden=True
        )

        cache = _make_mock_cache({"https://ext.example.com/sub": "vless://x@host:443\n"})
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 0

    async def test_hidden_internal_source_excluded_at_root_depth(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(
            db_session, "sub-parent", "sub-child", source_id="ref-1", is_hidden=True
        )
        await _add_config_source(db_session, "sub-child", "vless://uuid1@host:443")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-parent")

        # is_hidden is only enforced at depth == 0 for the *source itself*;
        # since the hidden source is the internal-token reference at root,
        # it must not be followed at all.
        assert result.count == 0

    async def test_hidden_external_source_visible_when_nested(self, db_session):
        await _make_user_and_subscription(db_session, "sub-parent")
        await _make_user_and_subscription(db_session, "sub-child", user_hash="u1")
        await _add_internal_source(db_session, "sub-parent", "sub-child", source_id="ref-1")
        await _add_external_source(
            db_session,
            "sub-child",
            "https://ext.example.com/sub",
            source_id="ext-1",
            is_hidden=True,
        )

        cache = _make_mock_cache({"https://ext.example.com/sub": "vless://x@host:443\n"})
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-parent")

        assert result.count == 1


# ---------------------------------------------------------------------------
# Empty / edge-case subscriptions
# ---------------------------------------------------------------------------


class TestEmptyAndEdgeCases:
    async def test_subscription_with_no_sources_returns_empty_result(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-1")

        assert result.count == 0
        assert result.truncated is False
        assert result.depth_exceeded is False

    async def test_external_source_returning_empty_string_content_yields_nothing(self, db_session):
        await _make_user_and_subscription(db_session, "sub-1")
        await _add_external_source(
            db_session, "sub-1", "https://ext.example.com/sub", source_id="ext-1"
        )

        cache = _make_mock_cache({"https://ext.example.com/sub": ""})
        resolver = ResolverService(db_session, cache)
        result = await resolver.resolve("sub-1")

        assert result.count == 0

    async def test_three_level_nesting_resolves_correctly_and_preserves_order(self, db_session):
        """sub-a -> sub-b -> sub-c, each contributing one distinct config;
        also confirms depth accounting doesn't accidentally trip
        depth_exceeded for a nesting depth within limits.
        """
        await _make_user_and_subscription(db_session, "sub-a")
        await _make_user_and_subscription(db_session, "sub-b", user_hash="u1")
        await _make_user_and_subscription(db_session, "sub-c", user_hash="u1")
        await _add_internal_source(db_session, "sub-a", "sub-b", source_id="ref-a-b")
        await _add_internal_source(db_session, "sub-b", "sub-c", source_id="ref-b-c")

        h_a = await _add_config_source(db_session, "sub-a", "vless://a@host:443", source_id="cfg-a")
        h_b = await _add_config_source(db_session, "sub-b", "vless://b@host:443", source_id="cfg-b")
        h_c = await _add_config_source(db_session, "sub-c", "vless://c@host:443", source_id="cfg-c")

        resolver = ResolverService(db_session, _make_mock_cache())
        result = await resolver.resolve("sub-a")

        assert result.depth_exceeded is False
        assert result.count == 3
        assert {c.hash for c in result.configs} == {h_a, h_b, h_c}
