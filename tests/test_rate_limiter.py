"""Tests for src.utils.rate_limiter.RateLimiter.

Redis is replaced by a small in-memory fake that implements `eval` with
the same sliding-window semantics as the real Lua script (so we don't
need an actual Redis or Lua interpreter), plus `keys` for get_stats.
"""

import time

import pytest

from src.utils.rate_limiter import RateLimitConfig, RateLimiter

pytestmark = pytest.mark.asyncio


class FakeRedisSlidingWindow:
    """
    Emulates the ZADD/ZREMRANGEBYSCORE/ZCARD/EXPIRE sliding window that
    RateLimiter's Lua script implements, via a plain Python dict of lists.
    """

    def __init__(self):
        self._windows: dict[str, list[int]] = {}
        self.raise_on_eval: Exception | None = None

    async def eval(self, script, numkeys, key, max_requests, window_seconds, current_time_ms):
        if self.raise_on_eval:
            raise self.raise_on_eval

        max_requests = int(max_requests)
        window_seconds = int(window_seconds)
        current_time_ms = int(current_time_ms)

        entries = self._windows.setdefault(key, [])
        cutoff = current_time_ms - window_seconds * 1000
        entries[:] = [t for t in entries if t > cutoff]

        if len(entries) < max_requests:
            entries.append(current_time_ms)
            return 1
        return 0

    async def keys(self, pattern):
        import fnmatch
        return [k for k in self._windows if fnmatch.fnmatch(k, pattern)]


class FakeWhitelistService:
    def __init__(self, whitelisted_ips=None):
        self._whitelisted = set(whitelisted_ips or [])

    async def is_whitelisted(self, ip):
        return ip in self._whitelisted

    async def list_all(self):
        return [{"ip_address": ip} for ip in self._whitelisted]


@pytest.fixture
def fake_redis():
    return FakeRedisSlidingWindow()


def _make_limiter(fake_redis, whitelisted_ips=None, **config_overrides):
    config = RateLimitConfig(**config_overrides) if config_overrides else RateLimitConfig()
    limiter = RateLimiter(config=config, redis=fake_redis)
    limiter._whitelist_service = FakeWhitelistService(whitelisted_ips)
    return limiter


class TestCheckPublicLimit:
    async def test_allows_requests_under_limit(self, fake_redis):
        limiter = _make_limiter(
            fake_redis, public_requests_per_second=3, public_window_seconds=1
        )

        for _ in range(3):
            allowed, error = await limiter.check_public_limit("1.2.3.4")
            assert allowed is True
            assert error is None

    async def test_blocks_requests_over_limit(self, fake_redis):
        limiter = _make_limiter(
            fake_redis, public_requests_per_second=2, public_window_seconds=1
        )

        await limiter.check_public_limit("1.2.3.4")
        await limiter.check_public_limit("1.2.3.4")
        allowed, error = await limiter.check_public_limit("1.2.3.4")

        assert allowed is False
        assert error is not None
        assert "Rate limit exceeded" in error

    async def test_different_ips_tracked_independently(self, fake_redis):
        limiter = _make_limiter(
            fake_redis, public_requests_per_second=1, public_window_seconds=1
        )

        allowed1, _ = await limiter.check_public_limit("1.1.1.1")
        allowed2, _ = await limiter.check_public_limit("2.2.2.2")

        assert allowed1 is True
        assert allowed2 is True

    async def test_whitelisted_ip_always_allowed(self, fake_redis):
        limiter = _make_limiter(
            fake_redis,
            whitelisted_ips=["9.9.9.9"],
            public_requests_per_second=1,
            public_window_seconds=1,
        )

        for _ in range(5):
            allowed, error = await limiter.check_public_limit("9.9.9.9")
            assert allowed is True
            assert error is None


class TestCheckInternalLimit:
    async def test_uses_token_based_key_when_token_provided(self, fake_redis):
        limiter = _make_limiter(
            fake_redis,
            internal_with_token_requests_per_second=2,
            internal_with_token_window_seconds=1,
        )

        await limiter.check_internal_limit("1.2.3.4", token="tok-a")
        await limiter.check_internal_limit("1.2.3.4", token="tok-a")
        allowed, _ = await limiter.check_internal_limit("1.2.3.4", token="tok-a")

        assert allowed is False

    async def test_different_tokens_tracked_independently(self, fake_redis):
        limiter = _make_limiter(
            fake_redis,
            internal_with_token_requests_per_second=1,
            internal_with_token_window_seconds=1,
        )

        allowed_a, _ = await limiter.check_internal_limit("1.2.3.4", token="tok-a")
        allowed_b, _ = await limiter.check_internal_limit("1.2.3.4", token="tok-b")

        assert allowed_a is True
        assert allowed_b is True

    async def test_no_token_uses_ip_based_key_with_stricter_limit(self, fake_redis):
        limiter = _make_limiter(
            fake_redis,
            internal_no_token_requests_per_second=1,
            internal_no_token_window_seconds=1,
        )

        allowed1, _ = await limiter.check_internal_limit("1.2.3.4", token=None)
        allowed2, _ = await limiter.check_internal_limit("1.2.3.4", token=None)

        assert allowed1 is True
        assert allowed2 is False

    async def test_whitelisted_ip_bypasses_internal_limit(self, fake_redis):
        limiter = _make_limiter(
            fake_redis,
            whitelisted_ips=["9.9.9.9"],
            internal_no_token_requests_per_second=1,
            internal_no_token_window_seconds=1,
        )

        for _ in range(3):
            allowed, _ = await limiter.check_internal_limit("9.9.9.9", token=None)
            assert allowed is True


class TestRedisFailure:
    async def test_fails_open_when_redis_raises(self, fake_redis):
        fake_redis.raise_on_eval = ConnectionError("redis down")
        limiter = _make_limiter(fake_redis, public_requests_per_second=1, public_window_seconds=1)

        allowed, error = await limiter.check_public_limit("1.2.3.4")

        assert allowed is True
        assert error is None

    async def test_fails_open_when_redis_client_is_none(self):
        limiter = RateLimiter(config=RateLimitConfig())
        limiter._redis = None
        limiter._redis_available = False
        limiter._redis_unavailable_since = time.monotonic()  # inside backoff window
        limiter._whitelist_service = FakeWhitelistService()

        allowed, error = await limiter.check_public_limit("1.2.3.4")

        assert allowed is True
        assert error is None


class TestGetStats:
    async def test_reports_redis_unavailable(self):
        limiter = RateLimiter(config=RateLimitConfig())
        limiter._redis = None
        limiter._redis_available = False
        limiter._redis_unavailable_since = time.monotonic()

        stats = await limiter.get_stats()
        assert stats["redis_available"] is False

    async def test_reports_tracked_ip_counts(self, fake_redis):
        limiter = _make_limiter(fake_redis, public_requests_per_second=5, public_window_seconds=1)
        await limiter.check_public_limit("1.1.1.1")
        await limiter.check_public_limit("2.2.2.2")

        stats = await limiter.get_stats()

        assert stats["redis_available"] is True
        assert stats["public_tracked_ips"] == 2
