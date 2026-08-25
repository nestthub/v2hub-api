"""
Provider-facing API endpoints for managing user connections.

These routes are called by authenticated providers (API-Token identifies
the provider, see `CurrentProvider`) to manage their authorization
relationship with a given `user_id`:

- GET    /providers/{user_id}         -> current authorization status
- POST   /providers/{user_id}         -> request/establish a connection
- POST   /providers/{user_id}/revoke  -> revoke access (soft, keeps history)
- DELETE /providers/{user_id}         -> remove the connection entirely

Two distinct flows exist under `POST /providers/{user_id}` depending on
whether the user already has an account:

1. Unknown user_id (no account yet): the API cannot approve anything
   server-side, since there is no user to authorize. It returns a
   `conn_{hmac}_{provider_name}` invite payload instead -- an HMAC over
   `(user_id, provider_hash)` that proves the link was issued by this
   API. Whatever trusted internal flow the user opens the link through
   (e.g. a Telegram bot) is expected to call the admin API to finalize
   the connection, passing that HMAC back for verification.
2. Known user_id: an authorization row is created/updated directly and
   a generic `provider_{provider_name}` deep link is returned instead
   (no HMAC needed -- the row already exists).
"""

import logging

from fastapi import APIRouter, status

from v2hub_api.api.dependencies import (
    CurrentProvider,
    ProviderAuthorizationServiceDep,
    UserServiceDep,
)
from v2hub_api.core.config import settings
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import (
    AuthenticationError,
    to_http_exception,
)
from v2hub_api.schemas.base_models import (
    ProviderConnectionDeleteResponse,
    ProviderConnectionResponse,
)
from v2hub_api.schemas.base_models.providers import ProviderConnectionCreateResponse
from v2hub_api.utils.auth_hmac import generate_auth_hmac

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/providers",
    tags=["Provider"],
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

        # Local variable intentionally named to avoid shadowing the
        # `fastapi.status` module imported above (used for status codes
        # elsewhere in this file).
        authorization_status = await authorization_service.get_status(
            provider.provider_hash,
            user.user_hash,
        )

        return ProviderConnectionResponse(
            user_id=user.user_id,
            status=authorization_status,
        )

    except Exception as e:
        raise to_http_exception(e) from e


@router.post(
    "/{user_id}",
    response_model=ProviderConnectionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create provider connection",
    description="Create authorization request between provider and user",
)
async def create_connection(
    user_id: int,
    provider: CurrentProvider,
    user_service: UserServiceDep,
    authorization_service: ProviderAuthorizationServiceDep,
) -> ProviderConnectionCreateResponse:
    try:
        user = await user_service.get_by_user_id(user_id)

        if not user:
            # No account for this user_id yet -- nothing to authorize
            # server-side. Hand back a signed invite link instead; the
            # HMAC proves to the admin API that this exact
            # (user_id, provider_hash) pair really came from here.
            auth_hmac = generate_auth_hmac(
                user_id,
                provider.provider_hash,
                settings.auth_hmac_secret,
            )
            payload = f"conn_{auth_hmac}_{provider.provider_name}"
            connection_status = ProviderAuthorizationStatus.PENDING

        else:
            authorization = await authorization_service.get_authorization(
                provider_hash=provider.provider_hash,
                user_hash=user.user_hash,
            )

            if authorization is None:
                # First-ever connection attempt for this pair: create a
                # PENDING row. This does not grant access by itself --
                # the user (or an admin, via /approve) still needs to
                # confirm it before the provider can act on their behalf.
                authorization = await authorization_service.add_authorization(
                    provider_hash=provider.provider_hash,
                    user_hash=user.user_hash,
                )

            elif authorization.status == ProviderAuthorizationStatus.APPROVED:
                # Already connected: short-circuit with no link, since
                # there's nothing left for the user to confirm.
                return ProviderConnectionCreateResponse(
                    user_id=user_id,
                    status=authorization.status,
                    connection_link=None,
                )

            elif authorization.status == ProviderAuthorizationStatus.REVOKED:
                # User previously revoked access -- reset the existing
                # row back to PENDING rather than creating a duplicate
                # one, so authorization history stays on a single row.
                authorization = await authorization_service.reinitialize_authorization(
                    authorization=authorization,
                )

            payload = f"provider_{provider.provider_name}"
            connection_status = authorization.status

        connection_link = f"{settings.connection_link_prefix}{payload}"

        return ProviderConnectionCreateResponse(
            user_id=user_id,
            status=connection_status,
            connection_link=connection_link,
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
