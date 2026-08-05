"""
FastAPI dependencies for dependency injection.

Provides:
- Database session dependency
- User authentication dependency
- Service layer dependencies
"""

from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.exceptions import to_http_exception
from v2hub_api.db.models import User
from v2hub_api.db.session import get_db_session
from v2hub_api.services.cache_service import CacheService, get_redis_client
from v2hub_api.services.resolver_service import ResolverService
from v2hub_api.services.stats_service import StatsService
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService

# ═══════════════════════════════════════════════════════════════════════════
# Database Session
# ═══════════════════════════════════════════════════════════════════════════


async def get_session() -> AsyncGenerator[AsyncSession, Any]:
    """Get database session."""
    async for session in get_db_session():
        yield session


DBSession = Annotated[AsyncSession, Depends(get_session)]


# ═══════════════════════════════════════════════════════════════════════════
# Service Dependencies
# ═══════════════════════════════════════════════════════════════════════════
async def get_cache_service(
    session: DBSession,
) -> CacheService:
    """Get cache service instance."""
    redis_client = await get_redis_client()
    return CacheService(session, redis_client)


async def get_subscription_service(
    session: DBSession,
    cache_service: Annotated[CacheService, Depends(get_cache_service)],
) -> SubscriptionService:
    """Get subscription service instance."""
    return SubscriptionService(session, cache_service)


async def get_resolver_service(
    session: DBSession,
    cache_service: Annotated[CacheService, Depends(get_cache_service)],
) -> ResolverService:
    """Get resolver service instance."""
    return ResolverService(session, cache_service)


async def get_user_service(
    session: DBSession,
) -> UserService:
    """Get user service instance."""
    return UserService(session)


async def get_stats_service(
    session: DBSession,
) -> StatsService:
    """Get stats service instance."""
    return StatsService(session)


StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]


SubscriptionServiceDep = Annotated[SubscriptionService, Depends(get_subscription_service)]

CacheServiceDep = Annotated[CacheService, Depends(get_cache_service)]

ResolverServiceDep = Annotated[ResolverService, Depends(get_resolver_service)]

UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# ═══════════════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════════════


async def get_current_user(
    api_token: Annotated[str, Header(alias="API-Token")],
    service: SubscriptionServiceDep,
) -> User:
    """
    Authenticate user by API token.

    Args:
        api_token: API token from API-Token header
        service: Subscription service

    Returns:
        Authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    try:
        return await service.authenticate_user(api_token)
    except Exception as e:
        raise to_http_exception(e) from e


CurrentUser = Annotated[User, Depends(get_current_user)]
