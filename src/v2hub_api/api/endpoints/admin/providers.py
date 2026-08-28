"""
Admin API endpoints for provider management.

Provides secure endpoints for:
- Creating and deleting providers
- Retrieving provider information
- Enabling and disabling providers
- Updating provider name and URL
- Regenerating provider API tokens

All endpoints require admin request signature verification
and an allowed internal IP address.
"""

import logging

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import ProviderServiceDep, UserServiceDep
from v2hub_api.core.exceptions import NotFoundError, to_http_exception
from v2hub_api.schemas.admin_models import (
    AllProvidersResponse,
    ProviderCreateRequest,
    ProviderCreateResponse,
    ProviderResponse,
    ProviderStatusUpdateRequest,
    ProviderTokenRefreshRequest,
    ProviderTokenRefreshResponse,
    ProviderURLUpdateRequest,
)
from v2hub_api.schemas.admin_models.providers import ProviderNameUpdateRequest

from .dependencies import AdminSecurityDep, InternalIPDep
from .provider_authorization import router as auth_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers")
router.include_router(auth_router)


# ═══════════════════════════════════════════════════════════════════════════
# Provider Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=AllProvidersResponse,
    summary="Get providers",
    description="Get providers information",
)
async def get_providers_list(
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> AllProvidersResponse:
    """
    Get provider account info.

    Returns provider credentials.
    """
    try:
        providers = await provider_service.get_all_providers()

        return AllProvidersResponse(
            provider_hashes={
                provider.provider_name: provider.provider_hash for provider in providers
            }
        )

    except Exception as e:
        logger.error(f"Failed to return provider: {e}")
        raise to_http_exception(e) from e


@router.post(
    "",
    response_model=ProviderCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new provider",
    description="Create a new provider account with generated API token",
)
async def create_provider(
    request: ProviderCreateRequest,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderCreateResponse:
    """
    Create a new provider account.

    Generates:
    - provider_hash
    - unique API token

    Returns provider credentials.
    """
    try:
        provider = await provider_service.create_provider(
            owner_hash=request.owner_hash,
            provider_name=request.provider_name,
            provider_url=request.provider_url,
        )

        logger.info(
            "Provider created: provider_hash=%s, owner_hash=%s, provider_url=%s",
            provider.provider_hash,
            provider.owner_hash,
            provider.provider_url,
        )

        return ProviderCreateResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to create provider: {e}")
        raise to_http_exception(e) from e


@router.get(
    "/name/{provider_name}",
    status_code=status.HTTP_200_OK,
    response_model=ProviderResponse,
    summary="Get provider info by name",
    description="Get provider id, hash and api-token by provider name.",
)
async def get_provider_by_name(
    provider_name: str,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderResponse:
    """
    Get provider account info by provider name.

    Returns provider credentials.
    """
    try:
        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        return ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error(
            "Failed to return provider by name=%s: %s",
            provider_name,
            e,
        )
        raise to_http_exception(e) from e


@router.get(
    "/owner/{owner_id}",
    status_code=status.HTTP_200_OK,
    response_model=ProviderResponse,
    summary="Get provider info by owner",
    description="Get provider id, hash and api-token by owner id.",
)
async def get_provider_by_owner(
    owner_id: int,
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderResponse:
    """
    Get provider account info by owner ID.

    Returns provider credentials.
    """
    try:
        user = await user_service.get_user(owner_id)

        provider = await provider_service.get_by_owner_hash(user.user_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        return ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error(
            "Failed to return provider by owner_id=%d: %s",
            owner_id,
            e,
        )
        raise to_http_exception(e) from e


@router.get(
    "/{provider_hash}",
    status_code=status.HTTP_200_OK,
    response_model=ProviderResponse,
    summary="Get provider info",
    description="Get provider id, hash and api-token",
)
async def get_provider(
    provider_hash: str,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderResponse:
    """
    Get provider account info.

    Returns provider credentials.
    """
    try:
        provider = await provider_service.get_provider(provider_hash)

        return ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to return provider: {e}")
        raise to_http_exception(e) from e


@router.delete(
    "/{provider_hash}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a provider",
    description="Delete a provider account",
)
async def delete_provider(
    provider_hash: str,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> None:
    """
    Delete a provider account.
    """
    try:
        await provider_service.delete_provider(provider_hash=provider_hash)

    except Exception as e:
        logger.error(f"Failed to delete provider: {e}")
        raise to_http_exception(e) from e


@router.patch(
    "/{provider_hash}/status",
    response_model=ProviderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update provider active status",
    description="Enable or disable provider account",
)
async def update_provider_status(
    provider_hash: str,
    request: ProviderStatusUpdateRequest,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderResponse:
    """
    Update provider active status.

    Args:
        provider_hash: Provider hash
        is_active: True to activate, False to deactivate

    Returns:
        Updated provider data
    """
    try:
        provider = await provider_service.set_active(
            provider_hash=provider_hash,
            is_active=request.is_active,
        )

        logger.info(
            "Provider status updated: provider_hash=%s, is_active=%s",
            provider.provider_hash,
            provider.is_active,
        )

        return ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to update provider status: {e}")
        raise to_http_exception(e) from e


@router.patch(
    "/{provider_hash}/url",
    response_model=ProviderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update provider url",
    description="Update provider url address",
)
async def update_provider_url(
    provider_hash: str,
    request: ProviderURLUpdateRequest,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderResponse:
    """Update provider URL.

    Args:
        provider_hash: Provider hash.
        provider_url: New provider URL.

    Returns:
        Updated provider data.
    """
    try:
        provider = await provider_service.update_provider_url(
            provider_hash=provider_hash,
            provider_url=request.provider_url,
        )

        logger.info(
            "Provider url updated: provider_hash=%s, provider_url=%s",
            provider.provider_hash,
            provider.provider_url,
        )

        return ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error("Failed to update provider URL: %s", e)
        raise to_http_exception(e) from e


@router.patch(
    "/{provider_hash}/name",
    response_model=ProviderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update provider name",
    description="Update provider name",
)
async def update_provider_name(
    provider_hash: str,
    request: ProviderNameUpdateRequest,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderResponse:
    """Update provider name.

    Args:
        provider_hash: Provider hash.
        provider_name: New provider name.

    Returns:
        Updated provider data.
    """
    try:
        provider = await provider_service.update_provider_name(
            provider_hash=provider_hash,
            provider_name=request.provider_name,
        )

        logger.info(
            "Provider name updated: provider_hash=%s, provider_name=%s",
            provider.provider_hash,
            provider.provider_name,
        )

        return ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to update provider name: {e}")
        raise to_http_exception(e) from e


@router.post(
    "/refresh-token",
    response_model=ProviderTokenRefreshResponse,
    summary="Refresh provider API token",
    description="Generate new API token for existing provider",
)
async def refresh_provider_token(
    request: ProviderTokenRefreshRequest,
    provider_service: ProviderServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderTokenRefreshResponse:
    """
    Refresh provider's API token.

    Generates new unique token and invalidates the old one.
    """
    try:
        new_token = await provider_service.refresh_provider_token(
            provider_hash=request.provider_hash
        )

        logger.info(
            "Token refreshed for provider_hash=%s",
            request.provider_hash,
        )

        return ProviderTokenRefreshResponse(
            provider_hash=request.provider_hash,
            new_api_token=new_token,
        )

    except Exception as e:
        logger.error(f"Failed to refresh token: {e}")
        raise to_http_exception(e) from e
