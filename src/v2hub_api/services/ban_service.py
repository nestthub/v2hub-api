"""
Ban management service for rate limit violations.

Tracks violations and automatically bans IPs that exceed violation thresholds.
Uses Redis for distributed ban storage.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class BanService:
    """
    Service for managing IP bans based on rate limit violations.

    Features:
    - Track violations per IP
    - Auto-ban after N violations
    - Configurable ban duration
    - Redis-based storage for distributed systems
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        max_violations: int = 3,
        violation_window_seconds: int = 60 * 10,
        ban_duration_seconds: int = 60 * 60 * 1,
    ) -> None:
        """
        Initialize ban service.

        Args:
            redis_client: Redis client for storage
            max_violations: Number of violations before ban (default: 5)
            violation_window_seconds: Time window for counting violations (default: 1 hour)
            ban_duration_seconds: How long to ban violators (default: 24 hours)
        """
        self.redis = redis_client
        self.max_violations = max_violations
        self.violation_window = violation_window_seconds
        self.ban_duration = ban_duration_seconds

        # Redis key prefixes
        self.ban_key_prefix = "ban:"
        self.violation_key_prefix = "violations:"

    async def is_banned(self, ip: str) -> bool:
        """
        Check if an IP is currently banned.

        Args:
            ip: IP address to check

        Returns:
            True if banned, False otherwise
        """
        ban_key = f"{self.ban_key_prefix}{ip}"

        try:
            ban_until = await self.redis.get(ban_key)

            if not ban_until:
                return False

            # Check if ban has expired
            ban_timestamp = float(ban_until)
            if datetime.now().timestamp() >= ban_timestamp:
                # Ban expired, clean up
                await self.redis.delete(ban_key)
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking ban for {ip}: {e}")
            # Fail open - don't block on Redis errors
            return False

    async def get_ban_info(self, ip: str) -> dict[str, Any] | None:
        """
        Get ban information for an IP.

        Args:
            ip: IP address

        Returns:
            Dict with ban info or None if not banned
        """
        ban_key = f"{self.ban_key_prefix}{ip}"

        try:
            ban_until = await self.redis.get(ban_key)

            if not ban_until:
                return None

            ban_timestamp = float(ban_until)
            now = datetime.now().timestamp()

            if now >= ban_timestamp:
                await self.redis.delete(ban_key)
                return None

            return {
                "ip": ip,
                "banned_until": datetime.fromtimestamp(ban_timestamp).isoformat(),
                "remaining_seconds": int(ban_timestamp - now),
            }

        except Exception as e:
            logger.error(f"Error getting ban info for {ip}: {e}")
            return None

    async def list_all(self) -> list[dict[str, Any]]:
        """
        Get all currently banned IPs.

        Returns:
            List of active bans with metadata
        """
        try:
            result = []
            now_ts = datetime.now().timestamp()

            cursor = 0
            pattern = f"{self.ban_key_prefix}*"

            while True:
                cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=100)

                for key in keys:
                    # key may be bytes
                    key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                    ip = key_str.replace(self.ban_key_prefix, "")

                    ban_until_raw = await self.redis.get(key)
                    if not ban_until_raw:
                        continue

                    try:
                        ban_timestamp = float(ban_until_raw)
                    except (TypeError, ValueError):
                        continue

                    # skip expired (cleanup safety)
                    if now_ts >= ban_timestamp:
                        await self.redis.delete(key)
                        continue

                    result.append(
                        {
                            "ip": ip,
                            "banned_until": datetime.fromtimestamp(ban_timestamp).isoformat(),
                            "remaining_seconds": int(ban_timestamp - now_ts),
                        }
                    )

                if cursor == 0:
                    break

            return sorted(result, key=lambda x: x["remaining_seconds"])

        except Exception as e:
            logger.error(f"Error listing bans: {e}")
            return []

    async def record_violation(self, ip: str) -> bool:
        """
        Record a rate limit violation for an IP.

        Increments violation counter and bans if threshold exceeded.

        Args:
            ip: IP address that violated rate limit

        Returns:
            True if IP was banned as a result, False otherwise
        """
        violation_key = f"{self.violation_key_prefix}{ip}"

        try:
            # Increment violation counter
            violations = await self.redis.incr(violation_key)

            # Set expiry on first violation
            if violations == 1:
                await self.redis.expire(violation_key, self.violation_window)

            logger.warning(
                f"Rate limit violation for {ip}: "
                f"{violations}/{self.max_violations} in {self.violation_window}s window"
            )

            # Check if threshold exceeded
            if violations >= self.max_violations:
                await self._ban_ip(ip)
                # Reset violation counter
                await self.redis.delete(violation_key)
                return True

            return False

        except Exception as e:
            logger.error(f"Error recording violation for {ip}: {e}")
            return False

    async def _ban_ip(self, ip: str) -> None:
        """
        Ban an IP address.

        Args:
            ip: IP address to ban
        """
        ban_key = f"{self.ban_key_prefix}{ip}"

        # Calculate ban expiry
        ban_until = datetime.now() + timedelta(seconds=self.ban_duration)
        ban_timestamp = ban_until.timestamp()

        try:
            # Store ban with TTL
            await self.redis.set(ban_key, str(ban_timestamp), ex=self.ban_duration)

            logger.warning(
                f"IP {ip} BANNED until {ban_until.isoformat()} "
                f"for exceeding {self.max_violations} rate limit violations"
            )

        except Exception as e:
            logger.error(f"Error banning IP {ip}: {e}")

    async def ban_ip(self, ip: str, duration_seconds: int | None = None) -> None:
        """
        Manually ban an IP address with custom duration.

        Args:
            ip: IP address to ban
            duration_seconds: Ban duration in seconds (optional, uses default if not specified)
        """
        ban_key = f"{self.ban_key_prefix}{ip}"
        ban_duration = duration_seconds if duration_seconds is not None else self.ban_duration

        # Calculate ban expiry
        ban_until = datetime.now() + timedelta(seconds=ban_duration)
        ban_timestamp = ban_until.timestamp()

        try:
            # Store ban with TTL
            await self.redis.set(ban_key, str(ban_timestamp), ex=ban_duration)

            logger.warning(
                f"IP {ip} MANUALLY BANNED until {ban_until.isoformat()} for {ban_duration} seconds"
            )

        except Exception as e:
            logger.error(f"Error manually banning IP {ip}: {e}")
            raise

    async def unban_ip(self, ip: str) -> bool:
        """
        Manually unban an IP address.

        Args:
            ip: IP address to unban

        Returns:
            True if IP was banned and is now unbanned, False otherwise
        """
        ban_key = f"{self.ban_key_prefix}{ip}"
        violation_key = f"{self.violation_key_prefix}{ip}"

        try:
            # Delete both ban and violations
            ban_deleted = await self.redis.delete(ban_key)
            await self.redis.delete(violation_key)

            if ban_deleted:
                logger.info(f"IP {ip} manually unbanned")
                return True

            return False

        except Exception as e:
            logger.error(f"Error unbanning IP {ip}: {e}")
            return False

    async def get_violation_count(self, ip: str) -> int:
        """
        Get current violation count for an IP.

        Args:
            ip: IP address

        Returns:
            Number of violations in current window
        """
        violation_key = f"{self.violation_key_prefix}{ip}"

        try:
            count = await self.redis.get(violation_key)
            return int(count) if count else 0

        except Exception as e:
            logger.error(f"Error getting violation count for {ip}: {e}")
            return 0


# Global ban service instance
_ban_service: BanService | None = None


async def get_ban_service() -> BanService | None:
    """Get global ban service instance."""
    global _ban_service

    if _ban_service is None:
        # Import here to avoid circular dependency
        from v2hub_api.services.cache_service import get_redis_client

        redis_client = await get_redis_client()
        if redis_client:
            _ban_service = BanService(
                redis_client=redis_client,
                max_violations=3,  # 3 violations
                violation_window_seconds=60 * 10,  # in 10 minutes
                ban_duration_seconds=60 * 60 * 3,  # = 3 hour ban
            )

    return _ban_service
