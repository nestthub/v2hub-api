"""
Admin API endpoints for provider authorization.

Provides secure endpoints for:
- Retrieving provider authorization information
- Processing provider connection requests
- Approving provider connections
- Rejecting provider connections

All endpoints require admin request signature verification
and an allowed internal IP address.
"""

import logging

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import (
    ProviderAuthorizationServiceDep,
    ProviderServiceDep,
    SubscriptionServiceDep,
    UserServiceDep,
)
from v2hub_api.core.config import settings
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import AuthenticationError, NotFoundError, to_http_exception
from v2hub_api.schemas.admin_models import (
    ProviderAuthorizationDecisionRequest,
    ProviderAuthorizationInfoResponse,
    ProviderAuthorizationRequest,
)
from v2hub_api.utils.auth_hmac import verify_auth_hmac

from .dependencies import AdminSecurityDep, InternalIPDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


def _verify_hmac_or_401(user_id: int, provider_hash: str, auth_hmac: str) -> None:
    if not verify_auth_hmac(user_id, provider_hash, settings.auth_hmac_secret, auth_hmac):
        raise AuthenticationError("Invalid or expired connection invite")


@router.get(
    "/{provider_name}/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=ProviderAuthorizationInfoResponse,
    summary="Get authorization status",
    description="Get user-provider authorization status.",
)
async def get_provider_and_authorization_status(
    provider_name: str,
    user_id: int,
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderAuthorizationInfoResponse:
    try:
        provider = await provider_service.get_by_name(provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        user = await user_service.get_by_user_id(user_id)

        if not user:
            raise NotFoundError("User not found")

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return ProviderAuthorizationInfoResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            user_id=user.user_id,
            status=authorization.status if authorization else None,
        )

    except Exception as e:
        logger.error(
            "Failed to get authorization status for provider=%s, user_id=%d: %s",
            provider_name,
            user_id,
            e,
        )
        raise to_http_exception(e) from e


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ProviderAuthorizationInfoResponse,
    summary="Process provider connection request",
    description="Process a provider connection request from the admin bot.",
)
async def process_provider_authorization_request(
    request: ProviderAuthorizationRequest,
    user_service: UserServiceDep,
    provider_service: ProviderServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderAuthorizationInfoResponse:
    try:
        provider = await provider_service.get_by_name(request.provider_name)

        if not provider:
            # Checked before touching the user record: an unknown
            # provider_name must not have the side effect of creating a
            # user for a caller-supplied user_id.
            raise NotFoundError("Provider not found")

        user = await user_service.get_by_user_id(request.user_id)

        if not user:
            user = await user_service.create_user(request.user_id)

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        if authorization is None and request.hmac is not None:
            _verify_hmac_or_401(request.user_id, provider.provider_hash, request.hmac)

            authorization = await authorization_service.add_authorization(
                provider_hash=provider.provider_hash,
                user_hash=user.user_hash,
                status=ProviderAuthorizationStatus.PENDING,
            )

        return ProviderAuthorizationInfoResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            user_id=user.user_id,
            status=authorization.status if authorization else None,
        )

    except Exception as e:
        logger.error(
            "Failed to process authorization request for provider=%s, user_id=%d: %s",
            request.provider_name,
            request.user_id,
            e,
        )
        raise to_http_exception(e) from e


@router.post(
    "/approve",
    status_code=status.HTTP_200_OK,
    response_model=ProviderAuthorizationInfoResponse,
    summary="Approve provider connection",
    description="Approve a provider connection request.",
)
async def approve_provider_connection(
    request: ProviderAuthorizationDecisionRequest,
    provider_service: ProviderServiceDep,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderAuthorizationInfoResponse:
    try:
        provider = await provider_service.get_by_name(request.provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        user = await user_service.get_by_user_id(request.user_id)

        if not user:
            raise NotFoundError("User not found")

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        if authorization is None:
            raise NotFoundError("Authorization not found")

        if authorization.status != ProviderAuthorizationStatus.PENDING:
            return ProviderAuthorizationInfoResponse(
                provider_name=provider.provider_name,
                provider_url=provider.provider_url,
                user_id=user.user_id,
                status=authorization.status,
            )

        authorization = await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return ProviderAuthorizationInfoResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            user_id=user.user_id,
            status=authorization.status,
        )

    except Exception as e:
        logger.error(
            "Failed to approve authorization for provider=%s, user_id=%d: %s",
            request.provider_name,
            request.user_id,
            e,
        )
        raise to_http_exception(e) from e


@router.post(
    "/reject",
    status_code=status.HTTP_200_OK,
    response_model=ProviderAuthorizationInfoResponse,
    summary="Reject provider connection",
    description="Reject a provider connection request.",
)
async def reject_provider_connection(
    request: ProviderAuthorizationDecisionRequest,
    provider_service: ProviderServiceDep,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
    subscription_service: SubscriptionServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> ProviderAuthorizationInfoResponse:
    try:
        provider = await provider_service.get_by_name(request.provider_name)

        if not provider:
            raise NotFoundError("Provider not found")

        user = await user_service.get_by_user_id(request.user_id)

        if not user:
            raise NotFoundError("User not found")

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        if authorization is None:
            raise NotFoundError("Authorization not found")

        subscriptions_exist = await subscription_service.list_subscriptions(
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
        )

        if subscriptions_exist:
            authorization = await authorization_service.revoke(
                provider_hash=provider.provider_hash,
                user_hash=user.user_hash,
            )

            return ProviderAuthorizationInfoResponse(
                provider_name=provider.provider_name,
                provider_url=provider.provider_url,
                user_id=user.user_id,
                status=authorization.status,
            )

        await authorization_service.delete_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return ProviderAuthorizationInfoResponse(
            provider_name=provider.provider_name,
            provider_url=provider.provider_url,
            user_id=user.user_id,
            status=None,
        )

    except Exception as e:
        logger.error(
            "Failed to reject authorization for provider=%s, user_id=%d: %s",
            request.provider_name,
            request.user_id,
            e,
        )
        raise to_http_exception(e) from e
