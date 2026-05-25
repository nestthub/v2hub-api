"""
Redis-based rate limiting system.

Features:
- Distributed rate limiting using Redis
- Public endpoint rate limiting (per IP)
- Internal endpoint rate limiting (with/without token)
- IP whitelist (unlimited requests)
- Sliding window counter algorithm
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from redis.asyncio import Redis

from src.services.whitelist_service import WhitelistService, get_whitelist_service
from src.services.cache_service import get_redis_client

logger = logging.getLogger(__name__)

# Время (секунды) до следующей попытки переподключения к Redis после сбоя
_REDIS_RETRY_INTERVAL = 30.0


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    
    # Public endpoints (e.g., /sub/{token})
    public_requests_per_second: int = 3
    public_window_seconds: int = 3
    
    # Internal endpoints without token
    internal_no_token_requests_per_second: int = 1
    internal_no_token_window_seconds: int = 3
    
    # Internal endpoints with token
    internal_with_token_requests_per_second: int = 3
    internal_with_token_window_seconds: int = 3
    

class RateLimiter:
    """
    Redis-based rate limiter using sliding window counter.
    
    Uses Redis sorted sets for efficient distributed rate limiting.
    Falls back to allowing requests if Redis is unavailable.
    """
    
    def __init__(
        self,
        config: Optional[RateLimitConfig] = None,
        redis: Optional[Redis] = None,
    ):
        """
        Initialize rate limiter.
        
        Args:
            config: Rate limit configuration
            redis: Redis client (will be fetched if not provided)
        """
        self.config = config or RateLimitConfig()
        self._redis = redis
        self._redis_available = True
        self._redis_unavailable_since: float = 0.0   # timestamp последнего сбоя
        self._whitelist_service: Optional[WhitelistService] = None
    
    async def _get_redis(self) -> Optional[Redis]:
        """
        Возвращает Redis-клиент.
        
        Если Redis ранее упал, повторяет попытку не чаще раза в
        _REDIS_RETRY_INTERVAL секунд — без этого флаг _redis_available
        оставался бы False навсегда до рестарта процесса.
        """
        # Если клиент уже есть — возвращаем сразу
        if self._redis is not None:
            return self._redis

        # Если Redis недоступен — проверяем, не истёк ли интервал ожидания
        if not self._redis_available:
            if time.monotonic() - self._redis_unavailable_since < _REDIS_RETRY_INTERVAL:
                return None
            # Интервал истёк — сбрасываем флаг и пробуем снова
            logger.info("Retrying Redis connection after backoff...")
            self._redis_available = True

        try:
            self._redis = await get_redis_client()
            if self._redis is None:
                self._redis_available = False
                self._redis_unavailable_since = time.monotonic()
                logger.warning("Redis not available - rate limiting will fail open")
        except Exception as e:
            logger.error(f"Failed to get Redis client: {e}")
            self._redis_available = False
            self._redis_unavailable_since = time.monotonic()
        
        return self._redis

    async def _get_whitelist_service(self) -> Optional[WhitelistService]:
        if self._whitelist_service is None:
            self._whitelist_service = await get_whitelist_service()
        return self._whitelist_service
    
    async def _is_whitelisted(self, ip: str) -> bool:
        if not ip:
            return False
    
        service = await self._get_whitelist_service()
        if not service:
            return False
    
        return await service.is_whitelisted(ip)
    
    async def _check_limit_redis(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check rate limit using Redis sliding window.
        
        Args:
            key: Redis key for this rate limit
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        redis = await self._get_redis()
        
        if not redis:
            # Redis unavailable - fail open (allow request)
            return True, None
        
        try:
            # Lua script for atomic sliding window counter
            lua_script = """
            local key = KEYS[1]
            local max_requests = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local current_time = tonumber(ARGV[3])
            
            -- Remove old entries outside window
            redis.call('ZREMRANGEBYSCORE', key, 0, current_time - window * 1000)
            
            -- Count requests in current window
            local current_count = redis.call('ZCARD', key)
            
            if current_count < max_requests then
                -- Add new request
                redis.call('ZADD', key, current_time, current_time)
                redis.call('EXPIRE', key, window * 2)
                return 1
            else
                return 0
            end
            """
            
            current_time = int(time.time() * 1000)  # milliseconds
            
            result = await redis.eval(
                lua_script,
                1,
                key,
                max_requests,
                window_seconds,
                current_time,
            )
            
            if result == 1:
                return True, None
            else:
                return False, f"Rate limit exceeded: max {max_requests} requests per {window_seconds}s"
        
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            # Сбрасываем клиент, чтобы _get_redis попробовал переподключиться
            self._redis = None
            self._redis_available = False
            self._redis_unavailable_since = time.monotonic()
            # Fail open (allow request)
            return True, None
    
    async def check_public_limit(self, ip: str) -> Tuple[bool, Optional[str]]:
        if await self._is_whitelisted(ip):
            return True, None
    
        key = f"rate_limit:public:{ip}"
        return await self._check_limit_redis(
            key,
            self.config.public_requests_per_second * self.config.public_window_seconds,
            self.config.public_window_seconds,
        )
    
    async def check_internal_limit(
        self,
        ip: str,
        token: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
    
        if await self._is_whitelisted(ip):
            return True, None
    
        if token:
            key = f"rate_limit:internal_token:{token}"
            max_requests = (
                self.config.internal_with_token_requests_per_second *
                self.config.internal_with_token_window_seconds
            )
            window = self.config.internal_with_token_window_seconds
        else:
            key = f"rate_limit:internal_no_token:{ip}"
            max_requests = (
                self.config.internal_no_token_requests_per_second *
                self.config.internal_no_token_window_seconds
            )
            window = self.config.internal_no_token_window_seconds
    
        return await self._check_limit_redis(key, max_requests, window)
    
    async def get_stats(self) -> dict:
        """
        Get rate limiter statistics.
        
        Returns:
            Dictionary with statistics
        """
        redis = await self._get_redis()
        
        if not redis:
            return {
                "redis_available": False,
                "message": "Redis not available",
            }
        
        try:
            # Count total keys used for rate limiting
            public_keys = await redis.keys("rate_limit:public:*")
            internal_no_token_keys = await redis.keys("rate_limit:internal_no_token:*")
            internal_token_keys = await redis.keys("rate_limit:internal_token:*")
            whitelist_service = await self._get_whitelist_service()
            
            return {
                "redis_available": True,
                "public_tracked_ips": len(public_keys),
                "internal_no_token_tracked_ips": len(internal_no_token_keys),
                "internal_token_tracked_tokens": len(internal_token_keys),
                "config": {
                    "public_rps": self.config.public_requests_per_second,
                    "internal_no_token_rps": self.config.internal_no_token_requests_per_second,
                    "internal_with_token_rps": self.config.internal_with_token_requests_per_second,
                    "whitelisted_ips": len(await whitelist_service.list_all() if whitelist_service else []),
                },
            }
        
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                "redis_available": True,
                "error": str(e),
            }


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """
    Get or create global rate limiter instance.
    
    Args:
        config: Configuration (only used on first call)
        
    Returns:
        RateLimiter instance
    """
    global _rate_limiter
    
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(config)
        logger.info("Rate limiter initialized")
    
    return _rate_limiter


def shutdown_rate_limiter() -> None:
    """Shutdown rate limiter (cleanup)."""
    global _rate_limiter
    
    if _rate_limiter is not None:
        logger.info("Rate limiter shutdown")
        _rate_limiter = None
