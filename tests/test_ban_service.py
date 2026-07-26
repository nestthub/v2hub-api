"""Tests for src.services.ban_service.BanService.

Redis is replaced by a small in-memory fake implementing just the
operations BanService uses (get/set/delete/incr/expire/scan), so no real
Redis instance is required.
"""

from datetime import datetime, timedelta

import pytest

from src.services.ban_service import BanService

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Minimal in-memory fake of the redis.asyncio.Redis interface."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttl_seconds: dict[str, int] = {}  # not enforced automatically; informational

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = str(value)
        if ex is not None:
            self._ttl_seconds[key] = ex
        return True

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                self._ttl_seconds.pop(k, None)
                count += 1
        return count

    async def incr(self, key):
        current = int(self._store.get(key, "0"))
        current += 1
        self._store[key] = str(current)
        return current

    async def expire(self, key, seconds):
        self._ttl_seconds[key] = seconds
        return True

    async def scan(self, cursor=0, match=None, count=100):
        import fnmatch
        pattern = match or "*"
        matched = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        return 0, matched


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def ban_service(fake_redis):
    return BanService(
        redis_client=fake_redis,
        max_violations=3,
        violation_window_seconds=600,
        ban_duration_seconds=3600,
    )


class TestIsBanned:
    async def test_returns_false_when_not_banned(self, ban_service):
        assert await ban_service.is_banned("1.2.3.4") is False

    async def test_returns_true_when_banned(self, ban_service):
        await ban_service.ban_ip("1.2.3.4")
        assert await ban_service.is_banned("1.2.3.4") is True

    async def test_returns_false_and_cleans_up_expired_ban(self, ban_service, fake_redis):
        expired_timestamp = (datetime.now() - timedelta(seconds=10)).timestamp()
        await fake_redis.set(f"{ban_service.ban_key_prefix}1.2.3.4", str(expired_timestamp))

        assert await ban_service.is_banned("1.2.3.4") is False
        # cleaned up
        assert await fake_redis.get(f"{ban_service.ban_key_prefix}1.2.3.4") is None

    async def test_fails_open_on_redis_error(self, ban_service, monkeypatch):
        async def _raise(*args, **kwargs):
            raise ConnectionError("redis down")

        ban_service.redis.get = _raise

        assert await ban_service.is_banned("1.2.3.4") is False


class TestGetBanInfo:
    async def test_returns_none_when_not_banned(self, ban_service):
        assert await ban_service.get_ban_info("1.2.3.4") is None

    async def test_returns_info_when_banned(self, ban_service):
        await ban_service.ban_ip("1.2.3.4", duration_seconds=100)

        info = await ban_service.get_ban_info("1.2.3.4")
        assert info is not None
        assert info["ip"] == "1.2.3.4"
        assert 0 < info["remaining_seconds"] <= 100

    async def test_returns_none_for_expired_ban(self, ban_service, fake_redis):
        expired_timestamp = (datetime.now() - timedelta(seconds=10)).timestamp()
        await fake_redis.set(f"{ban_service.ban_key_prefix}1.2.3.4", str(expired_timestamp))

        assert await ban_service.get_ban_info("1.2.3.4") is None


class TestRecordViolation:
    async def test_returns_false_before_threshold(self, ban_service):
        assert await ban_service.record_violation("1.2.3.4") is False
        assert await ban_service.record_violation("1.2.3.4") is False

    async def test_returns_true_and_bans_at_threshold(self, ban_service):
        await ban_service.record_violation("1.2.3.4")
        await ban_service.record_violation("1.2.3.4")
        banned = await ban_service.record_violation("1.2.3.4")

        assert banned is True
        assert await ban_service.is_banned("1.2.3.4") is True

    async def test_resets_violation_counter_after_ban(self, ban_service):
        await ban_service.record_violation("1.2.3.4")
        await ban_service.record_violation("1.2.3.4")
        await ban_service.record_violation("1.2.3.4")  # triggers ban

        count = await ban_service.get_violation_count("1.2.3.4")
        assert count == 0

    async def test_independent_per_ip(self, ban_service):
        await ban_service.record_violation("1.1.1.1")
        await ban_service.record_violation("1.1.1.1")
        await ban_service.record_violation("2.2.2.2")

        assert await ban_service.get_violation_count("1.1.1.1") == 2
        assert await ban_service.get_violation_count("2.2.2.2") == 1


class TestManualBanUnban:
    async def test_ban_ip_with_custom_duration(self, ban_service):
        await ban_service.ban_ip("1.2.3.4", duration_seconds=10)

        info = await ban_service.get_ban_info("1.2.3.4")
        assert info["remaining_seconds"] <= 10

    async def test_ban_ip_uses_default_duration(self, ban_service):
        await ban_service.ban_ip("1.2.3.4")

        info = await ban_service.get_ban_info("1.2.3.4")
        assert info["remaining_seconds"] <= ban_service.ban_duration

    async def test_unban_removes_ban_and_returns_true(self, ban_service):
        await ban_service.ban_ip("1.2.3.4")

        result = await ban_service.unban_ip("1.2.3.4")
        assert result is True
        assert await ban_service.is_banned("1.2.3.4") is False

    async def test_unban_returns_false_when_not_banned(self, ban_service):
        result = await ban_service.unban_ip("1.2.3.4")
        assert result is False

    async def test_unban_also_clears_violation_counter(self, ban_service):
        await ban_service.record_violation("1.2.3.4")
        await ban_service.ban_ip("1.2.3.4")

        await ban_service.unban_ip("1.2.3.4")

        assert await ban_service.get_violation_count("1.2.3.4") == 0


class TestListAll:
    async def test_empty_when_no_bans(self, ban_service):
        assert await ban_service.list_all() == []

    async def test_lists_active_bans_sorted_by_remaining_time(self, ban_service):
        await ban_service.ban_ip("1.1.1.1", duration_seconds=100)
        await ban_service.ban_ip("2.2.2.2", duration_seconds=10)

        result = await ban_service.list_all()

        assert len(result) == 2
        assert result[0]["ip"] == "2.2.2.2"  # shorter remaining time first
        assert result[1]["ip"] == "1.1.1.1"

    async def test_excludes_expired_bans(self, ban_service, fake_redis):
        expired_timestamp = (datetime.now() - timedelta(seconds=10)).timestamp()
        await fake_redis.set(f"{ban_service.ban_key_prefix}1.1.1.1", str(expired_timestamp))
        await ban_service.ban_ip("2.2.2.2", duration_seconds=100)

        result = await ban_service.list_all()

        assert len(result) == 1
        assert result[0]["ip"] == "2.2.2.2"
