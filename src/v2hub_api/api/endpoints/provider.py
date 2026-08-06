import logging

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import (
    CurrentProvider,
    ProviderAuthorizationServiceDep,
    UserServiceDep,
)
from v2hub_api.core.config import settings
from v2hub_api.core.exceptions import (
    AuthenticationError,
    TooManyApprovedUsersError,
    to_http_exception,
)
from v2hub_api.db.models.provider_authorization import ProviderAuthorizationStatus
from v2hub_api.schemas.base_models import (
    ProviderConnectionDeleteResponse,
    ProviderConnectionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/providers",
    tags=["Provider"],
    include_in_schema=False,
)


@router.get(
    "/{user_id}",
    response_model=ProviderConnectionResponse,
    summary="Get user connection status",
    description="Get provider authorization status for user",
)
async def get_user(
    user_id: int,
    provider: CurrentProvider,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ProviderConnectionResponse:
    try:
        user = await user_service.authenticate_user_by_id(user_id)

        status = await authorization_service.get_status(
            provider.provider_hash,
            user.user_hash,
        )

        return ProviderConnectionResponse(
            user_id=user.user_id,
            status=status,
        )

    except Exception as e:
        raise to_http_exception(e) from e


@router.post(
    "/{user_id}",
    response_model=ProviderConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create provider connection",
    description="Create authorization request between provider and user",
)
async def create_connection(
    user_id: int,
    provider: CurrentProvider,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ProviderConnectionResponse:
    try:
        user = await user_service.get_by_user_id(user_id)

        if not user:
            # TEMPORARY IMPLEMENTATION:
            # In the future this flow will be changed.
            # Providers should only be able to create connections for users
            # from trusted services. Otherwise, this endpoint may be abused
            # for creating unnecessary user accounts or spam.
            user = await user_service.create_user(user_id)

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        if authorization is None or authorization.status != ProviderAuthorizationStatus.APPROVED:
            approved_users_count = await authorization_service.get_approved_users_count(
                provider_hash=provider.provider_hash
            )
            if approved_users_count >= settings.max_provider_users:
                raise TooManyApprovedUsersError(approved_users_count, settings.max_provider_users)

        if authorization is None:
            authorization = await authorization_service.add_authorization(
                provider_hash=provider.provider_hash,
                user_hash=user.user_hash,
            )

        elif authorization.status != ProviderAuthorizationStatus.APPROVED:
            # TEMPORARY IMPLEMENTATION:
            # User confirmation is currently not required.
            # In the next update this will be replaced with a proper
            # user approval flow through the connection request process.
            await authorization_service.grant(
                provider_hash=provider.provider_hash,
                user_hash=user.user_hash,
            )

            authorization.status = ProviderAuthorizationStatus.APPROVED

        return ProviderConnectionResponse(
            user_id=user.user_id,
            status=authorization.status,
        )

    except Exception as e:
        raise to_http_exception(e) from e


@router.post(
    "/{user_id}/revoke",
    response_model=ProviderConnectionResponse,
    summary="Revoke provider connection",
    description="Revoke provider authorization for user",
)
async def revoke_connection(
    user_id: int,
    provider: CurrentProvider,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ProviderConnectionResponse:
    try:
        user = await user_service.authenticate_user_by_id(user_id)

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        if authorization is None:
            raise AuthenticationError("Authorization not found")

        await authorization_service.revoke(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return ProviderConnectionResponse(
            user_id=user.user_id,
            status=ProviderAuthorizationStatus.REVOKED,
        )

    except Exception as e:
        raise to_http_exception(e) from e


@router.delete(
    "/{user_id}",
    response_model=ProviderConnectionDeleteResponse,
    summary="Delete provider connection",
    description="Remove provider authorization permanently",
)
async def delete_connection(
    user_id: int,
    provider: CurrentProvider,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ProviderConnectionDeleteResponse:
    try:
        user = await user_service.authenticate_user_by_id(user_id)

        await authorization_service.delete_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return ProviderConnectionDeleteResponse(
            detail="Provider connection deleted",
        )

    except Exception as e:
        raise to_http_exception(e) from e
