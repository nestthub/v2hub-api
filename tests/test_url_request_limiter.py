"""Tests for src.utils.url_request_limiter.URLRequestLimiter.

Redis is replaced by a small in-memory fake implementing get/set/incr/
expire/delete, so no real Redis instance is required.
"""

import pytest

from src.utils.url_request_limiter import URLRequestLimiter

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Minimal in-memory fake of the redis.asyncio.Redis interface."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = str(value)
        return True

    async def incr(self, key):
        current = int(self._store.get(key, "0")) + 1
        self._store[key] = str(current)
        return current

    async def expire(self, key, seconds):
        return True

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def limiter(fake_redis):
    return URLRequestLimiter(
        redis_client=fake_redis,
        requests_per_second=1,
        max_failures=3,
        failure_window_seconds=60,
    )


class TestCheckLimit:
    async def test_first_request_allowed(self, limiter):
        allowed, error = await limiter.check_limit("1.2.3.4")
        assert allowed is True
        assert error is None

    async def test_second_request_within_same_second_blocked(self, limiter):
        await limiter.check_limit("1.2.3.4")
        allowed, error = await limiter.check_limit("1.2.3.4")

        assert allowed is False
        assert "rate limit exceeded" in error.lower()

    async def test_different_ips_independent(self, limiter):
        allowed1, _ = await limiter.check_limit("1.1.1.1")
        allowed2, _ = await limiter.check_limit("2.2.2.2")

        assert allowed1 is True
        assert allowed2 is True

    async def test_fails_open_on_redis_error(self, limiter):
        async def _raise(*args, **kwargs):
            raise ConnectionError("redis down")

        limiter.redis.get = _raise

        allowed, error = await limiter.check_limit("1.2.3.4")
        assert allowed is True
        assert error is None

    async def test_respects_custom_requests_per_second(self, fake_redis):
        limiter = URLRequestLimiter(redis_client=fake_redis, requests_per_second=3)

        results = [await limiter.check_limit("1.2.3.4") for _ in range(3)]
        assert all(allowed for allowed, _ in results)

        blocked, _ = await limiter.check_limit("1.2.3.4")
        assert blocked is False


class TestRecordFailure:
    async def test_returns_false_before_threshold(self, limiter):
        assert await limiter.record_failure("1.2.3.4") is False
        assert await limiter.record_failure("1.2.3.4") is False

    async def test_returns_true_at_threshold(self, limiter):
        await limiter.record_failure("1.2.3.4")
        await limiter.record_failure("1.2.3.4")
        should_ban = await limiter.record_failure("1.2.3.4")

        assert should_ban is True

    async def test_resets_counter_after_threshold_reached(self, limiter):
        await limiter.record_failure("1.2.3.4")
        await limiter.record_failure("1.2.3.4")
        await limiter.record_failure("1.2.3.4")  # triggers ban condition

        count = await limiter.get_failure_count("1.2.3.4")
        assert count == 0

    async def test_independent_per_ip(self, limiter):
        await limiter.record_failure("1.1.1.1")
        await limiter.record_failure("1.1.1.1")
        await limiter.record_failure("2.2.2.2")

        assert await limiter.get_failure_count("1.1.1.1") == 2
        assert await limiter.get_failure_count("2.2.2.2") == 1


class TestClearFailures:
    async def test_removes_failure_count(self, limiter):
        await limiter.record_failure("1.2.3.4")
        await limiter.clear_failures("1.2.3.4")

        assert await limiter.get_failure_count("1.2.3.4") == 0

    async def test_no_op_when_no_failures_recorded(self, limiter):
        await limiter.clear_failures("1.2.3.4")  # should not raise
        assert await limiter.get_failure_count("1.2.3.4") == 0


class TestGetFailureCount:
    async def test_zero_when_no_failures(self, limiter):
        assert await limiter.get_failure_count("1.2.3.4") == 0

    async def test_fails_open_returns_zero_on_error(self, limiter):
        async def _raise(*args, **kwargs):
            raise ConnectionError("redis down")

        limiter.redis.get = _raise

        assert await limiter.get_failure_count("1.2.3.4") == 0
