"""
URL request rate limiter for external URL fetching.

Implements:
- 1 request per second limit for external URLs
- Automatic ban after 3 consecutive failures or failures within 1 minute
- Redis-based distributed rate limiting
"""

import logging
from typing import Optional, Tuple

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class URLRequestLimiter:
    """
    Rate limiter for external URL requests.
    
    Features:
    - 1 request per second limit per IP
    - Track failed requests
    - Auto-ban after threshold exceeded
    - Redis-based storage
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        requests_per_second: int = 1,
        max_failures: int = 3,
        failure_window_seconds: int = 60,
    ):
        """
        Initialize URL request limiter.
        
        Args:
            redis_client: Redis client for storage
            requests_per_second: Maximum requests per second (default: 1)
            max_failures: Number of failures before ban (default: 3)
            failure_window_seconds: Time window for counting failures (default: 60)
        """
        self.redis = redis_client
        self.requests_per_second = requests_per_second
        self.max_failures = max_failures
        self.failure_window = failure_window_seconds
        
        # Redis key prefixes
        self.request_key_prefix = "url_request:"
        self.failure_key_prefix = "url_failures:"
    
    async def check_limit(self, ip: str) -> Tuple[bool, Optional[str]]:
        """
        Check if IP can make external URL request.
        
        Args:
            ip: IP address
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        request_key = f"{self.request_key_prefix}{ip}"
        
        try:
            # Check current request count
            current_count = await self.redis.get(request_key)
            
            if current_count is None:
                # First request - allow and set counter
                await self.redis.set(request_key, "1", ex=1)
                return True, None
            
            count = int(current_count)
            
            if count >= self.requests_per_second:
                return False, f"URL request rate limit exceeded: max {self.requests_per_second} per second"
            
            # Increment counter
            await self.redis.incr(request_key)
            
            return True, None
        
        except Exception as e:
            logger.error(f"Error checking URL request limit for {ip}: {e}")
            # Fail open - allow request on error
            return True, None
    
    async def record_failure(self, ip: str) -> bool:
        """
        Record a failed URL request.
        
        Args:
            ip: IP address that had failed request
            
        Returns:
            True if IP should be banned, False otherwise
        """
        failure_key = f"{self.failure_key_prefix}{ip}"
        
        try:
            # Increment failure counter
            failures = await self.redis.incr(failure_key)
            
            # Set expiry on first failure
            if failures == 1:
                await self.redis.expire(failure_key, self.failure_window)
            
            logger.warning(
                f"URL request failure for {ip}: "
                f"{failures}/{self.max_failures} in {self.failure_window}s window"
            )
            
            # Check if threshold exceeded
            if failures >= self.max_failures:
                # Reset failure counter
                await self.redis.delete(failure_key)
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error recording URL failure for {ip}: {e}")
            return False
    
    async def clear_failures(self, ip: str) -> None:
        """
        Clear failure count for IP (called on successful request).
        
        Args:
            ip: IP address
        """
        failure_key = f"{self.failure_key_prefix}{ip}"
        
        try:
            await self.redis.delete(failure_key)
        except Exception as e:
            logger.error(f"Error clearing failures for {ip}: {e}")
    
    async def get_failure_count(self, ip: str) -> int:
        """
        Get current failure count for IP.
        
        Args:
            ip: IP address
            
        Returns:
            Number of failures in current window
        """
        failure_key = f"{self.failure_key_prefix}{ip}"
        
        try:
            count = await self.redis.get(failure_key)
            return int(count) if count else 0
        except Exception as e:
            logger.error(f"Error getting failure count for {ip}: {e}")
            return 0


# Global URL request limiter instance
_url_request_limiter: Optional[URLRequestLimiter] = None


async def get_url_request_limiter() -> Optional[URLRequestLimiter]:
    """Get global URL request limiter instance."""
    global _url_request_limiter
    
    if _url_request_limiter is None:
        # Import here to avoid circular dependency
        from src.services.cache_service import get_redis_client
        
        redis_client = await get_redis_client()
        if redis_client:
            _url_request_limiter = URLRequestLimiter(
                redis_client=redis_client,
                requests_per_second=1,      # 1 request per second
                max_failures=3,             # 3 failures
                failure_window_seconds=60,  # in 1 minute window
            )
    
    return _url_request_limiter
