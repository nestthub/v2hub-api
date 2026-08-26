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
    SubscriptionServiceDep,
)
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import (
    InvalidAuthorizationStatusError,
    NotFoundError,
    to_http_exception,
)
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

    Only approved and pending connections are returned. Revoked
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
                    is_authorized=authorization.status == ProviderAuthorizationStatus.APPROVED,
                    status=authorization.status,
                )
                for authorization in authorizations
                if authorization.status
                in [ProviderAuthorizationStatus.APPROVED, ProviderAuthorizationStatus.PENDING]
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

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        return ConnectionResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            is_authorized=authorization.status == ProviderAuthorizationStatus.APPROVED
            if authorization
            else False,
            status=authorization.status if authorization else None,
        )

    except Exception as e:
        logger.error(
            "Failed to get provider connection for user_id=%d, provider=%s: %s",
            current_user.user_id,
            provider_name,
            e,
        )
        raise to_http_exception(e) from e


@router.post(
    "/connections/{provider_name}/approve",
    status_code=status.HTTP_200_OK,
    response_model=ConnectionResponse,
    summary="Approve provider connection",
    description="Approve a pending provider connection request.",
)
async def approve_connection(
    provider_name: str,
    current_user: CurrentUser,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ConnectionResponse:
    """
    Approve a pending provider connection for the current user.

    Only PENDING authorizations can be approved.
    """
    try:
        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        if authorization is None:
            raise NotFoundError("Authorization not found")

        if authorization.status == ProviderAuthorizationStatus.APPROVED:
            return ConnectionResponse(
                provider_name=provider.provider_name,
                provider_url=provider.provider_url,
                is_authorized=True,
                status=ProviderAuthorizationStatus.APPROVED,
            )
        elif authorization.status != ProviderAuthorizationStatus.PENDING:
            raise InvalidAuthorizationStatusError(authorization.status)

        authorization = await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        logger.info(
            "Connection authorization approved: user_id=%d, provider=%s",
            current_user.user_id,
            provider_name,
        )

        return ConnectionResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            is_authorized=True,
            status=authorization.status,
        )

    except Exception as e:
        logger.error(
            "Failed to approve connection for user_id=%d, provider=%s: %s",
            current_user.user_id,
            provider_name,
            e,
        )
        raise to_http_exception(e) from e


@router.post(
    "/connections/{provider_name}/reject",
    status_code=status.HTTP_200_OK,
    response_model=ConnectionResponse,
    summary="Reject provider connection",
    description="Reject a pending provider connection request.",
)
async def reject_connection(
    provider_name: str,
    current_user: CurrentUser,
    provider_service: ProviderServiceDep,
    subscription_service: SubscriptionServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ConnectionResponse:
    """
    Reject a pending provider connection for the current user.

    Only PENDING authorizations can be rejected.
    The pending authorization is deleted.
    """
    try:
        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        if authorization is None:
            raise NotFoundError("Authorization not found")

        if authorization.status != ProviderAuthorizationStatus.PENDING:
            raise InvalidAuthorizationStatusError(authorization.status)

        subscriptions_exist = await subscription_service.list_subscriptions(
            user_hash=current_user.user_hash,
            provider_hash=provider.provider_hash,
        )

        if subscriptions_exist:
            authorization = await authorization_service.revoke(
                provider_hash=provider.provider_hash,
                user_hash=current_user.user_hash,
            )

            return ConnectionResponse(
                provider_name=provider.provider_name,
                provider_url=provider.provider_url,
                is_authorized=False,
                status=authorization.status,
            )

        await authorization_service.delete_authorization(
            provider_hash=provider.provider_hash,
            user_hash=current_user.user_hash,
        )

        return ConnectionResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            is_authorized=False,
            status=None,
        )

    except Exception as e:
        logger.error(
            "Failed to reject connection for user_id=%d, provider=%s: %s",
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
