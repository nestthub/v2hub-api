"""
FastAPI middleware and dependencies for rate limiting.

Usage:
    # In main.py lifespan
    await setup_rate_limiting(app, whitelisted_ips=["1.2.3.4"])
    
    # In endpoints
    from src.middleware.rate_limit import check_public_rate_limit
    
    @router.get("/sub/{token}")
    async def get_subscription(
        token: str,
        _: None = Depends(check_public_rate_limit),
    ):
        ...
"""

import logging
from typing import Optional, Set

from fastapi import FastAPI, Request

from src.core.exceptions import RateLimitError, to_http_exception
from src.utils.rate_limiter import (
    RateLimitConfig,
    get_rate_limiter,
)

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """
    Extract real client IP from request.
    
    Checks headers in order:
    1. X-Real-IP (nginx)
    2. X-Forwarded-For (proxies)
    3. Direct connection
    """
    # X-Real-IP header (nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    
    # X-Forwarded-For header (can contain multiple IPs)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Берем первый IP (оригинальный клиент)
        return forwarded_for.split(",")[0].strip()

    
    # Direct connection
    if request.client:
        return request.client.host
    
    return "unknown"


def get_api_token(request: Request) -> Optional[str]:
    """
    Extract API token from request.
    
    Checks:
    1. API-Token header
    """
    # API-Token header
    api_token = request.headers.get("API-Token")
    if api_token:
        return api_token.strip()
    
    return None


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI Dependencies
# ═══════════════════════════════════════════════════════════════════════════

async def check_public_rate_limit(request: Request) -> None:
    """
    Dependency для проверки лимитов публичных эндпоинтов.
    
    Checks:
    1. If IP is banned (from previous violations)
    2. Rate limit
    3. Records violation if limit exceeded
    
    Использование:
        @router.get("/sub/{token}")
        async def get_subscription(
            token: str,
            _: None = Depends(check_public_rate_limit),
        ):
            ...
    """
    from src.services.ban_service import get_ban_service
    
    client_ip = get_client_ip(request)
    
    # 1. Check if IP is banned
    ban_service = await get_ban_service()
    if ban_service:
        if await ban_service.is_banned(client_ip):
            ban_info = await ban_service.get_ban_info(client_ip)
            logger.warning(
                "Banned IP %s attempted access to %s %s",
                client_ip,
                request.method,
                request.url.path,
            )
            raise RateLimitError(
                message=f"IP banned until {ban_info['banned_until']}",
                retry_after=ban_info['remaining_seconds'],
            )
    
    # 2. Check rate limit
    limiter = get_rate_limiter()
    is_allowed, error_message = await limiter.check_public_limit(client_ip)
    
    if not is_allowed:
        logger.warning(
            "Public rate limit exceeded for IP %s on %s %s",
            client_ip,
            request.method,
            request.url.path,
        )
        
        # 3. Record violation (may result in ban)
        if ban_service:
            was_banned = await ban_service.record_violation(client_ip)
            if was_banned:
                error_message = "Rate limit exceeded multiple times. IP has been banned."
        
        raise RateLimitError(
            message=error_message or "Too many requests",
            retry_after=120,
        )



async def check_internal_rate_limit(request: Request) -> None:
    """
    Dependency для проверки лимитов внутренних эндпоинтов.
    
    Checks:
    1. If IP is banned (from previous violations)
    2. Rate limit
    3. Records violation if limit exceeded
    
    Автоматически определяет наличие токена и применяет соответствующие лимиты.
    """
    from src.services.ban_service import get_ban_service
    
    client_ip = get_client_ip(request)
    api_token = get_api_token(request)
    
    # 1. Check if IP is banned
    ban_service = await get_ban_service()
    if ban_service:
        if await ban_service.is_banned(client_ip):
            ban_info = await ban_service.get_ban_info(client_ip)
            logger.warning(
                "Banned IP %s attempted access to %s %s",
                client_ip,
                request.method,
                request.url.path,
            )
            raise to_http_exception(RateLimitError(
                message=f"IP banned until {ban_info['banned_until']}",
                retry_after=ban_info['remaining_seconds'],
            ))
    
    # 2. Check rate limit
    limiter = get_rate_limiter()
    is_allowed, error_message = await limiter.check_internal_limit(
        client_ip, 
        api_token
    )
    
    if not is_allowed:
        logger.warning(
            "Internal rate limit exceeded for IP %s (token: %s) on %s %s",
            client_ip,
            "present" if api_token else "absent",
            request.method,
            request.url.path,
        )
        
        # 3. Record violation (may result in ban)
        if ban_service:
            was_banned = await ban_service.record_violation(client_ip)
            if was_banned:
                error_message = "Rate limit exceeded multiple times. IP has been banned."
        
        raise to_http_exception(RateLimitError(
            message=error_message or "Too many requests",
            retry_after=120,
        ))



# ═══════════════════════════════════════════════════════════════════════════
# Setup and Middleware
# ═══════════════════════════════════════════════════════════════════════════

async def setup_rate_limiting(
    app: FastAPI,
    public_rps: float = 10.0,
    internal_no_token_rps: float = 5.0,
    internal_with_token_rps: float = 20.0,
) -> None:
    """
    Setup rate limiting with Redis.
    
    Args:
        app: FastAPI application
        public_rps: Requests per second for public endpoints
        internal_no_token_rps: RPS for internal without token
        internal_with_token_rps: RPS for internal with token
        whitelisted_ips: IPs exempt from rate limiting
    """
    # Get Redis client
    from src.services.cache_service import get_redis_client
    redis = await get_redis_client()
    
    if not redis:
        logger.warning(
            "Redis not available - rate limiting will fail open (allow all requests)"
        )
    
    # Initialize rate limiter with config
    config = RateLimitConfig(
        public_requests_per_second=int(public_rps),
        internal_no_token_requests_per_second=int(internal_no_token_rps),
        internal_with_token_requests_per_second=int(internal_with_token_rps),
    )
    
    # Create and store rate limiter instance
    get_rate_limiter(config)
    
    logger.info(
        "Rate limiting configured: public=%d rps, internal_no_token=%d rps, "
        "internal_with_token=%d rps",
        int(public_rps),
        int(internal_no_token_rps),
        int(internal_with_token_rps),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Admin Endpoint для мониторинга
# ═══════════════════════════════════════════════════════════════════════════

async def get_rate_limiter_stats() -> dict:
    """
    Get current rate limiter statistics.
    
    Использование в admin endpoint:
        @router.get("/admin/rate-limit-stats")
        async def stats():
            return await get_rate_limiter_stats()
    """
    limiter = get_rate_limiter()
    return await limiter.get_stats()
