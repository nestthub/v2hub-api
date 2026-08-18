"""
User self-service API endpoints.

Provides endpoints for the currently authenticated user to:
- View their account information.
- List their active provider connections.
- View provider information and connection status.
- Revoke an active provider connection.

Authentication is performed using the user's API token.

Provider connections are identified by provider name, which is public API
information. Internal identifiers such as provider hashes are never exposed.
"""

import logging

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import (
    CurrentUser,
    ProviderAuthorizationServiceDep,
    ProviderServiceDep,
)
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import NotFoundError, to_http_exception
from v2hub_api.schemas import (
    ConnectionResponse,
    ConnectionsResponse,
    MeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["Me"])


@router.get(
    "",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description="Get information about the currently authenticated user.",
)
async def get_me(
    current_user: CurrentUser,
) -> MeResponse:
    """Get information about the currently authenticated user."""
    return MeResponse(
        user_id=current_user.user_id,
        is_active=current_user.is_active,
    )


@router.get(
    "/connections",
    response_model=ConnectionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List active connections",
    description="Get providers currently authorized to manage the user's subscriptions.",
)
async def get_connections(
    current_user: CurrentUser,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ConnectionsResponse:
    """
    Get all providers currently authorized to manage the user's subscriptions.

    Only approved connections are returned. Pending and revoked
    authorizations are excluded.
    """
    try:
        authorizations = await authorization_service.list_providers_for_user(
            user_hash=current_user.user_hash,
        )

        return ConnectionsResponse(
            connections=[
                ConnectionResponse(
                    provider_name=authorization.provider.provider_name,
                    provider_url=authorization.provider.provider_url,
                    is_authorized=True,
                )
                for authorization in authorizations
                if authorization.status == ProviderAuthorizationStatus.APPROVED
            ],
        )

    except Exception as e:
        logger.error(
            "Failed to get connections for user_id=%d: %s",
            current_user.user_id,
            e,
        )
        raise to_http_exception(e) from e


@router.get(
    "/connections/{provider_name}",
    response_model=ConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get provider connection",
    description="Get provider information and the current user's connection status.",
)
async def get_connection(
    provider_name: str,
    current_user: CurrentUser,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ConnectionResponse:
    """
    Get provider information and connection status.

    The provider is returned even when the user is not currently connected.
    This allows the client to display provider information and offer a
    connection action when appropriate.
    """
    try:
        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        is_authorized = await authorization_service.is_authorized(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        return ConnectionResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            is_authorized=is_authorized,
        )

    except Exception as e:
        logger.error(
            "Failed to get provider connection for user_id=%d, provider=%s: %s",
            current_user.user_id,
            provider_name,
            e,
        )
        raise to_http_exception(e) from e


@router.delete(
    "/connections/{provider_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke connection",
    description="Revoke the current user's authorization for a provider.",
)
async def revoke_connection(
    provider_name: str,
    current_user: CurrentUser,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> None:
    """
    Revoke a provider connection.

    The authorization record is preserved. The provider-side connection
    and its subscriptions remain available so that the user can reconnect
    later without losing their existing subscriptions.
    """
    try:
        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        await authorization_service.revoke(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        logger.info(
            "Connection authorization revoked: user_id=%d, provider=%s",
            current_user.user_id,
            provider_name,
        )

    except Exception as e:
        logger.error(
            "Failed to revoke connection for user_id=%d, provider=%s: %s",
            current_user.user_id,
            provider_name,
            e,
        )
        raise to_http_exception(e) from e
