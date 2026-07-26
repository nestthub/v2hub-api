"""Tests for src.services.whitelist_service.WhitelistService.

Redis is replaced by a small in-memory fake implementing the set/hash
operations WhitelistService uses, so no real Redis instance is required.
"""

import pytest

from src.services.whitelist_service import WhitelistService

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Minimal in-memory fake of the redis.asyncio.Redis interface (sets + hashes)."""

    def __init__(self):
        self._sets: dict[str, set[str]] = {}
        self._hashes: dict[str, dict[bytes, bytes]] = {}

    async def sismember(self, key, value):
        return value in self._sets.get(key, set())

    async def smembers(self, key):
        # redis-py normally returns bytes members; WhitelistService handles both.
        return set(self._sets.get(key, set()))

    async def sadd(self, key, value):
        s = self._sets.setdefault(key, set())
        added = 0 if value in s else 1
        s.add(value)
        return added

    async def srem(self, key, value):
        s = self._sets.get(key, set())
        if value in s:
            s.remove(value)
            return 1
        return 0

    async def hset(self, key, mapping):
        h = self._hashes.setdefault(key, {})
        for k, v in mapping.items():
            h[k.encode() if isinstance(k, str) else k] = (
                v.encode() if isinstance(v, str) else v
            )
        return len(mapping)

    async def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._sets:
                del self._sets[k]
                count += 1
            if k in self._hashes:
                del self._hashes[k]
                count += 1
        return count


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def whitelist_service(fake_redis):
    return WhitelistService(redis_client=fake_redis)


class TestAdd:
    async def test_adds_new_ip(self, whitelist_service):
        added = await whitelist_service.add("1.2.3.4")
        assert added is True

    async def test_adding_existing_ip_returns_false(self, whitelist_service):
        await whitelist_service.add("1.2.3.4")
        added_again = await whitelist_service.add("1.2.3.4")
        assert added_again is False

    async def test_adds_cidr_range(self, whitelist_service):
        added = await whitelist_service.add("10.0.0.0/24")
        assert added is True

    async def test_invalid_ip_raises(self, whitelist_service):
        with pytest.raises(Exception):
            await whitelist_service.add("not-an-ip")

    async def test_stores_description_metadata(self, whitelist_service):
        await whitelist_service.add("1.2.3.4", description="Office IP")

        entries = await whitelist_service.list_all()
        assert entries[0]["description"] == "Office IP"


class TestIsWhitelisted:
    async def test_exact_match(self, whitelist_service):
        await whitelist_service.add("1.2.3.4")
        assert await whitelist_service.is_whitelisted("1.2.3.4") is True

    async def test_not_whitelisted(self, whitelist_service):
        assert await whitelist_service.is_whitelisted("9.9.9.9") is False

    async def test_cidr_range_match(self, whitelist_service):
        await whitelist_service.add("10.0.0.0/24")
        assert await whitelist_service.is_whitelisted("10.0.0.55") is True

    async def test_cidr_range_no_match_outside_range(self, whitelist_service):
        await whitelist_service.add("10.0.0.0/24")
        assert await whitelist_service.is_whitelisted("10.0.1.55") is False

    async def test_fails_open_on_redis_error(self, whitelist_service):
        async def _raise(*args, **kwargs):
            raise ConnectionError("redis down")

        whitelist_service.redis.sismember = _raise

        assert await whitelist_service.is_whitelisted("1.2.3.4") is False


class TestRemove:
    async def test_removes_existing_ip(self, whitelist_service):
        await whitelist_service.add("1.2.3.4")

        removed = await whitelist_service.remove("1.2.3.4")
        assert removed is True
        assert await whitelist_service.is_whitelisted("1.2.3.4") is False

    async def test_removing_nonexistent_ip_returns_false(self, whitelist_service):
        removed = await whitelist_service.remove("9.9.9.9")
        assert removed is False

    async def test_removes_metadata_too(self, whitelist_service):
        await whitelist_service.add("1.2.3.4", description="test")
        await whitelist_service.remove("1.2.3.4")

        entries = await whitelist_service.list_all()
        assert entries == []


class TestListAll:
    async def test_empty_list_when_nothing_whitelisted(self, whitelist_service):
        assert await whitelist_service.list_all() == []

    async def test_lists_all_entries(self, whitelist_service):
        await whitelist_service.add("1.1.1.1")
        await whitelist_service.add("2.2.2.2")

        entries = await whitelist_service.list_all()
        ips = {e["ip_address"] for e in entries}
        assert ips == {"1.1.1.1", "2.2.2.2"}

    async def test_entry_without_description_has_none(self, whitelist_service):
        await whitelist_service.add("1.1.1.1")

        entries = await whitelist_service.list_all()
        assert entries[0]["description"] is None


class TestClear:
    async def test_removes_all_entries(self, whitelist_service):
        await whitelist_service.add("1.1.1.1")
        await whitelist_service.add("2.2.2.2")

        removed_count = await whitelist_service.clear()

        assert removed_count == 2
        assert await whitelist_service.list_all() == []

    async def test_clear_when_empty_returns_zero(self, whitelist_service):
        assert await whitelist_service.clear() == 0


class TestIpInCidr:
    # _ip_in_cidr is a sync method; override the module-level asyncio
    # marker (empty list = no markers) to avoid a PytestWarning.
    pytestmark = []

    def test_ip_in_range(self, whitelist_service):
        assert whitelist_service._ip_in_cidr("192.168.1.5", "192.168.1.0/24") is True

    def test_ip_not_in_range(self, whitelist_service):
        assert whitelist_service._ip_in_cidr("192.168.2.5", "192.168.1.0/24") is False

    def test_invalid_cidr_returns_false(self, whitelist_service):
        assert whitelist_service._ip_in_cidr("192.168.1.5", "not-a-cidr") is False

    def test_invalid_ip_returns_false(self, whitelist_service):
        assert whitelist_service._ip_in_cidr("not-an-ip", "192.168.1.0/24") is False
