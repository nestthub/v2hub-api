"""
Provider authorization service.

Handles the consent relationship between a Provider and a User:
- a user grants a provider access to manage their subscriptions
- a user can revoke that access at any time
- provider-facing routes verify authorization before acting on behalf of a user
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import AuthorizationError, NotFoundError
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
        Create a provider authorization.

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

    async def grant(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization:
        """
        Grant (or re-approve) provider access to a user.
        """
        authorization = await self.authorization_repo.get_by_hash((provider_hash, user_hash))

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

        authorization = await self.authorization_repo.create_authorization(
            provider_hash=provider_hash,
            user_hash=user_hash,
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
