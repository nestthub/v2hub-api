"""
Provider authorization service.

Handles the consent relationship between a Provider and a User:
- a user grants a provider access to manage their subscriptions
- a user can revoke that access at any time
- provider-facing routes verify authorization before acting on behalf of a user

Authorization lifecycle
------------------------
An authorization row moves through three statuses (`ProviderAuthorizationStatus`):

    PENDING  --grant()-->  APPROVED  --revoke()-->  REVOKED
       ^                                                 |
       └──────────── reinitialize_authorization() ───────┘

- `add_authorization` creates a row, usually starting PENDING (an admin
  or the user still has to confirm it).
- `grant` moves a row to APPROVED (or creates one directly as APPROVED,
  e.g. for provider-initiated connections). This is the only place the
  `MAX_PROVIDERS_PER_USER` quota (see `settings.max_providers_per_user`)
  is enforced -- a user cannot end up with more than that many providers
  simultaneously APPROVED.
- `revoke` moves an APPROVED row to REVOKED. It is idempotent: revoking
  an already-revoked authorization is a no-op rather than an error.
- `reinitialize_authorization` resets a REVOKED row back to PENDING so a
  user can be re-invited without losing the original authorization
  history (created_at, provider/user hashes) in a fresh row.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import AuthorizationError, NotFoundError, TooManyProvidersError
from v2hub_api.db.models import ProviderAuthorization
from v2hub_api.db.repositories.provider_authorization_repository import (
    ProviderAuthorizationRepository,
)
from v2hub_api.db.repositories.subscription_repository import SubscriptionRepository

logger = logging.getLogger(__name__)


class ProviderAuthorizationService:
    """Manage provider ↔ user authorization relationships."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.authorization_repo = ProviderAuthorizationRepository(session)
        self.subscription_repo = SubscriptionRepository(session)

    async def add_authorization(
        self,
        provider_hash: str,
        user_hash: str,
        status: ProviderAuthorizationStatus | None = None,
    ) -> ProviderAuthorization:
        """
        Create a provider authorization row.

        This does NOT enforce the `MAX_PROVIDERS_PER_USER` quota -- that
        check only applies when a provider becomes APPROVED (see `grant`).

        Args:
            provider_hash: Hash of the provider requesting authorization.
            user_hash: Hash of the user being asked to authorize.
            status: Initial status. When omitted, falls back to the
                `ProviderAuthorization` model's column default, which is
                PENDING (see migration 0004 and the model definition) --
                a row created this way still requires confirmation via
                `grant` (or the admin `/approve` endpoint) before the
                provider has any access. Pass
                `status=ProviderAuthorizationStatus.APPROVED` explicitly
                for flows that intentionally create an already-approved
                row (e.g. certain admin/provider-initiated paths).

        Returns:
            Created provider authorization.
        """
        authorization = await self.authorization_repo.create(
            provider_hash=provider_hash,
            user_hash=user_hash,
            status=status,
        )

        await self.session.commit()

        return authorization

    async def delete_authorization(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> None:
        """
        Permanently remove a provider authorization and its subscriptions.

        Unlike `revoke` (which keeps the row as a REVOKED audit record),
        this hard-deletes the authorization row and any subscriptions the
        provider created for the user. Used when there is nothing worth
        keeping -- e.g. an admin rejects a connection request that never
        produced any subscriptions.

        Raises:
            NotFoundError: If no authorization exists for this pair.
        """
        authorization = await self.get_authorization(
            provider_hash,
            user_hash,
        )

        if authorization is None:
            raise NotFoundError("Authorization not found")

        await self.subscription_repo.delete_by_provider(
            provider_hash=provider_hash,
            user_hash=user_hash,
        )

        await self.authorization_repo.delete(authorization)

        await self.session.commit()

        logger.info(
            "Provider authorization deleted: provider_hash=%s user_hash=%s",
            provider_hash,
            user_hash,
        )

    async def reinitialize_authorization(
        self,
        authorization: ProviderAuthorization,
    ) -> ProviderAuthorization:
        """
        Reinitialize a provider authorization request.

        Sets the authorization status back to PENDING.

        Returns:
            Updated provider authorization.
        """
        authorization = await self.authorization_repo.update(
            authorization,
            status=ProviderAuthorizationStatus.PENDING,
        )

        await self.session.commit()

        return authorization

    async def grant(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization:
        """
        Grant (or re-approve) provider access to a user.

        Three cases, in order:
        1. No authorization row exists yet -> create one directly as
           APPROVED (used for provider-initiated connections where no
           separate PENDING step is needed).
        2. A row exists but isn't APPROVED (PENDING or REVOKED) -> flip
           it to APPROVED.
        3. A row exists and is already APPROVED -> return it unchanged
           (idempotent; no duplicate log entry, no quota check).

        Cases 1 and 2 are gated by `settings.max_providers_per_user`: a
        user cannot have more than that many providers simultaneously
        APPROVED. The check is skipped for case 3 so that re-fetching an
        already-approved authorization never fails due to the user's own
        existing approval.

        Raises:
            TooManyProvidersError: If granting this authorization would
                push the user's approved-provider count over the
                configured maximum.
        """
        authorization = await self.authorization_repo.get_by_hash((provider_hash, user_hash))

        if not authorization or authorization.status != ProviderAuthorizationStatus.APPROVED:
            # Only enforce the quota when this call would *add* a new
            # approved provider. Re-approving an authorization that is
            # already APPROVED for this exact provider is a no-op below
            # and must not be blocked by its own existing membership.
            approved_count = await self.authorization_repo.get_user_approved_providers_count(
                user_hash
            )

            if approved_count >= settings.max_providers_per_user:
                raise TooManyProvidersError(approved_count, settings.max_providers_per_user)

        if authorization:
            if authorization.status != ProviderAuthorizationStatus.APPROVED:
                authorization = await self.authorization_repo.set_status(
                    authorization,
                    ProviderAuthorizationStatus.APPROVED,
                )
                await self.session.commit()

                logger.info(
                    "Provider authorization re-approved: provider_hash=%s, user_hash=%s",
                    provider_hash,
                    user_hash,
                )

            return authorization

        authorization = await self.authorization_repo.create(
            provider_hash=provider_hash,
            user_hash=user_hash,
            status=ProviderAuthorizationStatus.APPROVED,
        )

        await self.session.commit()

        logger.info(
            "Provider authorization granted: provider_hash=%s, user_hash=%s",
            provider_hash,
            user_hash,
        )

        return authorization

    async def revoke(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization:
        """
        Revoke provider access to a user.
        """
        authorization = await self.authorization_repo.get_by_hash((provider_hash, user_hash))

        if authorization is None:
            raise NotFoundError("Provider authorization not found")

        if authorization.status == ProviderAuthorizationStatus.REVOKED:
            return authorization

        authorization = await self.authorization_repo.set_status(
            authorization,
            ProviderAuthorizationStatus.REVOKED,
        )

        await self.session.commit()

        logger.info(
            "Provider authorization revoked: provider_hash=%s, user_hash=%s",
            provider_hash,
            user_hash,
        )

        return authorization

    async def require_authorized(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization:
        """
        Return an approved authorization or raise AuthorizationError.
        """
        authorization = await self.authorization_repo.get_approved(
            provider_hash=provider_hash,
            user_hash=user_hash,
        )

        if authorization is None:
            raise AuthorizationError(
                "Provider is not authorized to manage this user's subscriptions"
            )

        return authorization

    async def is_authorized(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> bool:
        """
        Check whether a provider is authorized for a user.
        """
        return (
            await self.authorization_repo.get_approved(
                provider_hash=provider_hash,
                user_hash=user_hash,
            )
        ) is not None

    async def get_status(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorizationStatus:
        """
        Get current authorization status.

        Raises:
            AuthorizationError: If no authorization exists.
        """
        authorization = await self.authorization_repo.get_by_hash((provider_hash, user_hash))

        if authorization is None:
            raise AuthorizationError(
                "Provider is not authorized to manage this user's subscriptions"
            )

        return authorization.status

    async def get_authorization(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization | None:
        """
        Get provider authorization for the specified user.

        Returns:
            Provider authorization if it exists, otherwise None.
        """
        return await self.authorization_repo.get_by_hash((provider_hash, user_hash))

    async def get_approved_users_count(
        self,
        provider_hash: str,
    ) -> int:
        """
        Get the number of users that have approved the provider.
        """
        return await self.authorization_repo.get_provider_approved_users_count(
            provider_hash=provider_hash,
        )

    async def list_providers_for_user(
        self,
        user_hash: str,
    ) -> list[ProviderAuthorization]:
        """List all provider authorizations for a user."""
        return await self.authorization_repo.get_all_for_user(user_hash)

    async def list_users_for_provider(
        self,
        provider_hash: str,
    ) -> list[ProviderAuthorization]:
        """List all user authorizations for a provider."""
        return await self.authorization_repo.get_all_for_provider(provider_hash)
