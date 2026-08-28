"""
Admin API endpoints for user management.

Provides secure endpoints for:
- User creation and retrieval
- User deletion
- User activation and deactivation
- API token regeneration

All endpoints require admin request signature and internal IP verification.
"""

import logging

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import (
    ProviderAuthorizationServiceDep,
    ProviderServiceDep,
    UserServiceDep,
)
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import NotFoundError, to_http_exception
from v2hub_api.schemas import (
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserResponse,
    UserStatusUpdateRequest,
)
from v2hub_api.schemas.base_models.users import ConnectionResponse, ConnectionsResponse

from .dependencies import AdminSecurityDep, InternalIPDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users")

# ═══════════════════════════════════════════════════════════════════════════
# User Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new user",
    description="Create a new user account with generated API token",
)
async def create_user(
    request: UserCreateRequest,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> UserCreateResponse:
    """
    Create a new user account.

    Generates:
    - user_hash from user_id
    - unique API token

    Returns user credentials.
    """
    try:
        user = await user_service.create_user(user_id=request.user_id)

        logger.info("User created: user_id=%d, user_hash=%s", user.user_id, user.user_hash)

        return UserCreateResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
            provider_hash=None,
        )

    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise to_http_exception(e) from e


@router.get(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=UserResponse,
    summary="Get user info",
    description="Get user id, hash and api-token",
)
async def get_user(
    user_id: int,
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> UserResponse:
    """
    Get user account info.

    Returns user credentials.
    """
    try:
        user = await user_service.get_user(user_id)

        provider = await provider_service.get_by_owner_hash(owner_hash=user.user_hash)

        return UserResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
            provider_hash=provider.provider_hash if provider else None,
        )

    except Exception as e:
        logger.error(f"Failed to return user: {e}")
        raise to_http_exception(e) from e


@router.get(
    "/{user_id}/providers",
    response_model=ConnectionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List user's providers",
    description="Get all providers owned by the specified user.",
)
async def get_user_providers(
    user_id: int,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ConnectionsResponse:
    """
    Get all providers owned by the specified user.
    """
    try:
        user = await user_service.get_user(user_id)

        authorizations = await authorization_service.list_providers_for_user(
            user_hash=user.user_hash,
        )

        return ConnectionsResponse(
            connections=[
                ConnectionResponse(
                    provider_name=authorization.provider.provider_name,
                    provider_url=authorization.provider.provider_url,
                    is_authorized=authorization.status == ProviderAuthorizationStatus.APPROVED,
                    status=authorization.status,
                )
                for authorization in authorizations
            ],
        )

    except Exception as e:
        logger.error(
            "Failed to get providers for user_id=%d: %s",
            user_id,
            e,
        )
        raise to_http_exception(e) from e


@router.get(
    "/{user_id}/providers/{provider_name}",
    response_model=ConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user's provider",
    description="Get provider information and authorization status for the specified user.",
)
async def get_user_provider(
    user_id: int,
    provider_name: str,
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ConnectionResponse:
    """
    Get provider information and authorization status for a user.
    """
    try:
        user = await user_service.get_user(user_id)

        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return ConnectionResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            is_authorized=(
                authorization.status == ProviderAuthorizationStatus.APPROVED
                if authorization
                else False
            ),
            status=authorization.status if authorization else None,
        )

    except Exception as e:
        logger.error(
            "Failed to get provider for user_id=%d, provider=%s: %s",
            user_id,
            provider_name,
            e,
        )
        raise to_http_exception(e) from e


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description="Delete a user account",
)
async def delete_user(
    user_id: int,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> None:
    """
    Delete a user account.
    """
    try:
        await user_service.delete_user(user_id=user_id)

    except Exception as e:
        logger.error(f"Failed to delete user: {e}")
        raise to_http_exception(e) from e


@router.patch(
    "/{user_id}/status",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user active status",
    description="Enable or disable user account",
)
async def update_user_status(
    user_id: int,
    request: UserStatusUpdateRequest,
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> UserResponse:
    """
    Update user active status.

    Args:
        user_id: User ID
        is_active: True to activate, False to deactivate

    Returns:
        Updated user data
    """
    try:
        user = await user_service.set_active(
            user_id=user_id,
            is_active=request.is_active,
        )

        provider = await provider_service.get_by_owner_hash(owner_hash=user.user_hash)

        logger.info(
            "User status updated: user_id=%d, is_active=%s",
            user.user_id,
            user.is_active,
        )

        return UserResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
            provider_hash=provider.provider_hash if provider else None,
        )

    except Exception as e:
        logger.error(f"Failed to update user status: {e}")
        raise to_http_exception(e) from e


@router.post(
    "/refresh-token",
    response_model=TokenRefreshResponse,
    summary="Refresh user API token",
    description="Generate new API token for existing user",
)
async def refresh_user_token(
    request: TokenRefreshRequest,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> TokenRefreshResponse:
    """
    Refresh user's API token.

    Generates new unique token and invalidates the old one.
    """
    try:
        new_token = await user_service.refresh_token(user_id=request.user_id)

        logger.info("Token refreshed for user_id=%d", request.user_id)

        return TokenRefreshResponse(
            user_id=request.user_id,
            new_api_token=new_token,
        )

    except Exception as e:
        logger.error(f"Failed to refresh token: {e}")
        raise to_http_exception(e) from e
