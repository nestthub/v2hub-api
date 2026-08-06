"""
FastAPI dependencies for dependency injection.

Provides:
- Database session dependency
- User authentication dependency
- Service layer dependencies
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Path
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.exceptions import to_http_exception
from v2hub_api.db.models import User
from v2hub_api.db.models.provider import Provider
from v2hub_api.db.session import get_db_session
from v2hub_api.services.cache_service import CacheService, get_redis_client
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
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


async def get_provider_service(
    session: DBSession,
) -> ProviderService:
    """Get provider service instance."""
    return ProviderService(session)


async def get_provider_authorization_service(
    session: DBSession,
) -> ProviderAuthorizationService:
    """Get provider authorization service instance."""
    return ProviderAuthorizationService(session)


SubscriptionServiceDep = Annotated[SubscriptionService, Depends(get_subscription_service)]

CacheServiceDep = Annotated[CacheService, Depends(get_cache_service)]

ResolverServiceDep = Annotated[ResolverService, Depends(get_resolver_service)]

UserServiceDep = Annotated[UserService, Depends(get_user_service)]

StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]

ProviderServiceDep = Annotated[ProviderService, Depends(get_provider_service)]
ProviderAuthorizationServiceDep = Annotated[
    ProviderAuthorizationService, Depends(get_provider_authorization_service)
]

# ═══════════════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════════════


async def get_current_user(
    api_token: Annotated[str, Header(alias="API-Token")],
    service: UserServiceDep,
) -> User:
    """
    Authenticate user by API token.

    Args:
        api_token: API token from API-Token header
        service: User service

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


async def get_current_provider(
    api_token: Annotated[str, Header(alias="API-Token")],
    service: ProviderServiceDep,
) -> Provider:
    """
    Authenticate provider by API token.

    Args:
        api_token: API token from API-Token header
        service: Provider service

    Returns:
        Authenticated provider

    Raises:
        HTTPException: If authentication fails
    """
    try:
        return await service.authenticate_provider(api_token)
    except Exception as e:
        raise to_http_exception(e) from e


CurrentProvider = Annotated[Provider, Depends(get_current_provider)]


async def get_provider_and_user(
    user_id: Annotated[int, Path(...)],
    api_token: Annotated[str, Header(alias="API-Token")],
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> tuple[Provider, User]:
    """
    Authenticate a provider and resolve the target user for
    /providers/{user_id}/subscriptions routes.

    Requires the authenticated caller to be a Provider, and the provider
    must have an APPROVED ProviderAuthorization for the given user_id.
    """
    try:
        provider = await provider_service.authenticate_provider(api_token=api_token)
        user = await user_service.authenticate_user_by_id(user_id)

        await authorization_service.require_authorized(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return provider, user

    except Exception as e:
        raise to_http_exception(e) from e


ProviderAndUser = Annotated[tuple[Provider, User], Depends(get_provider_and_user)]


# ═══════════════════════════════════════════════════════════════════════════
# Subscription Actor
# ═══════════════════════════════════════════════════════════════════════════
#
# Ручки подписок идентичны для пользователя и для провайдера, управляющего
# подписками своего клиента — разница только в том, кто аутентифицировался.
# SubscriptionActor несет ПОЛНЫЕ данные обеих сторон (не просто user_hash),
# чтобы бизнес-логика могла обращаться и к User, и к Provider напрямую —
# например для аудит-лога "какой провайдер что изменил", лимитов на
# провайдера и т.п.


@dataclass
class SubscriptionActor:
    """
    Контекст выполнения ручки подписок.

    - user: целевой пользователь, чьими подписками управляют
    - provider: провайдер, выполняющий запрос от имени user, либо None
      если запрос выполняет сам пользователь (self-service)
    """

    user: User
    provider: Provider | None = None

    @property
    def user_hash(self) -> str:
        return self.user.user_hash

    @property
    def is_provider_request(self) -> bool:
        return self.provider is not None


async def get_actor(current_user: CurrentUser) -> SubscriptionActor:
    """Self-service: пользователь действует от своего собственного имени."""
    return SubscriptionActor(user=current_user)


async def get_provider_actor(
    provider_and_user: ProviderAndUser,
) -> SubscriptionActor:
    """Provider: провайдер действует от имени указанного user_id."""
    provider, user = provider_and_user
    return SubscriptionActor(user=user, provider=provider)


Actor = Annotated[SubscriptionActor, Depends(get_actor)]
ProviderActor = Annotated[SubscriptionActor, Depends(get_provider_actor)]
