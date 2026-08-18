"""
Provider management service.

Handles provider creation, token management, and authentication.
"""

import logging
import secrets
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.exceptions import (
    AuthenticationError,
    DuplicateNameError,
    NotFoundError,
    ValidationError,
)
from v2hub_api.db.models import Provider
from v2hub_api.db.repositories.provider_repository import ProviderRepository
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.user_service import UserService

if TYPE_CHECKING:
    from v2hub_api.db.models.user import User


logger = logging.getLogger(__name__)


class ProviderService:
    """
    Service for provider management operations.

    Features:
    - Create providers with generated tokens
    - Refresh API tokens
    - Authenticate providers
    - Provider lookup
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.provider_repo = ProviderRepository(session)
        self.authorization_service = ProviderAuthorizationService(session)
        self.user_service = UserService(session)

    def _generate_provider_hash(self) -> str:
        """
        Generate unique provider hash.

        Returns:
            Provider hash
        """
        return str(uuid.uuid4())

    def _generate_api_token(self) -> str:
        """
        Generate API token.

        Returns:
            Generated API token
        """
        return secrets.token_urlsafe(settings.api_token_length)

    async def create_provider(
        self,
        owner_hash: str,
        provider_name: str,
        provider_url: str | None = None,
    ) -> Provider:
        """
        Create a new provider account.

        Args:
            owner_hash: Provider owner hash
            provider_name: Provider name
            provider_url: Optional provider URL

        Returns:
            Created provider

        Raises:
            ValidationError: If provider already exists
        """
        existing_provider = await self.get_by_owner_hash(owner_hash)

        if existing_provider:
            raise ValidationError("Provider already exists")

        provider_hash = self._generate_provider_hash()
        api_token = self._generate_api_token()

        provider = await self.provider_repo.create_provider(
            provider_hash=provider_hash,
            owner_hash=owner_hash,
            provider_name=provider_name,
            provider_url=provider_url,
            api_token=api_token,
        )

        await self.session.commit()

        logger.info(
            "Provider created: provider_hash=%s, owner_hash=%s",
            provider_hash,
            owner_hash,
        )

        return provider

    async def get_all_providers(
        self,
    ) -> list[Provider]:
        """
        Get all providers.

        Returns:
            list[Provider]

        """
        providers = await self.provider_repo.get_all(limit=1000)

        return providers

    async def get_provider(
        self,
        provider_hash: str,
    ) -> Provider:
        """
        Get provider account.

        Args:
            provider_hash: Provider hash

        Returns:
            Provider

        Raises:
            NotFoundError: Provider not found
        """
        provider = await self.get_by_hash(provider_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        return provider

    async def set_active(
        self,
        provider_hash: str,
        is_active: bool,
    ) -> Provider:
        """
        Update provider active status.

        Args:
            provider_hash: Provider hash
            is_active: New state

        Returns:
            Updated provider

        Raises:
            NotFoundError: Provider not found
        """
        provider = await self.get_by_hash(provider_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        if provider.is_active == is_active:
            return provider

        provider.is_active = is_active

        await self.session.commit()
        await self.session.refresh(provider)

        logger.info(
            "Provider status updated: provider_hash=%s, is_active=%s",
            provider_hash,
            is_active,
        )

        return provider

    async def update_provider_url(
        self,
        provider_hash: str,
        provider_url: str | None,
    ) -> Provider:
        """
        Update provider URL.

        Args:
            provider_hash: Provider hash
            provider_url: New provider URL

        Returns:
            Updated provider

        Raises:
            NotFoundError: Provider not found
        """
        provider = await self.get_by_hash(provider_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        # Idempotency: avoid unnecessary DB writes
        if provider.provider_url == provider_url:
            return provider

        provider.provider_url = provider_url

        await self.session.commit()
        await self.session.refresh(provider)

        logger.info(
            "Provider URL updated: provider_hash=%s, provider_url=%s",
            provider_hash,
            provider_url,
        )

        return provider

    async def update_provider_name(
        self,
        provider_hash: str,
        provider_name: str,
    ) -> Provider:
        """
        Update provider name.

        Args:
            provider_hash: Provider hash
            provider_name: New provider name

        Returns:
            Updated provider

        Raises:
            NotFoundError: Provider not found
            DuplicateNameError: Provider name already exists
        """
        provider = await self.get_by_hash(provider_hash=provider_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        # Idempotency: avoid unnecessary DB writes
        if provider.provider_name == provider_name:
            return provider

        existing_provider = await self.provider_repo.get_by_name(
            provider_name=provider_name,
        )

        if existing_provider:
            raise DuplicateNameError(provider_name, entity="provider")

        provider.provider_name = provider_name

        await self.session.commit()
        await self.session.refresh(provider)

        logger.info(
            "Provider name updated: provider_hash=%s, provider_name=%s",
            provider_hash,
            provider_name,
        )

        return provider

    async def delete_provider(
        self,
        provider_hash: str,
    ) -> None:
        """
        Delete provider account.

        Args:
            provider_hash: Provider hash

        Raises:
            NotFoundError: Provider not found
        """
        provider = await self.get_by_hash(provider_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        await self.provider_repo.delete(provider)
        await self.session.commit()

        logger.info(
            "Provider deleted: provider_hash=%s",
            provider_hash,
        )

    async def refresh_provider_token(
        self,
        provider_hash: str,
    ) -> str:
        """
        Refresh provider API token.

        Args:
            provider_hash: Provider hash

        Returns:
            New API token

        Raises:
            NotFoundError: If provider not found
        """
        provider = await self.get_by_hash(provider_hash)

        if not provider:
            raise NotFoundError("Provider not found")

        new_token = self._generate_api_token()

        await self.provider_repo.update_api_token(
            provider,
            new_token,
        )

        await self.session.commit()

        logger.info(
            "Token refreshed for provider_hash=%s",
            provider_hash,
        )

        return new_token

    async def get_by_token(
        self,
        api_token: str,
    ) -> Provider | None:
        """
        Get provider by API token.

        Args:
            api_token: API token

        Returns:
            Provider or None if not found
        """
        return await self.provider_repo.get_by_api_token(api_token)

    async def get_by_hash(
        self,
        provider_hash: str,
    ) -> Provider | None:
        """
        Get provider by provider hash.

        Args:
            provider_hash: Provider hash

        Returns:
            Provider or None if not found
        """
        return await self.provider_repo.get_by_hash(provider_hash)

    async def get_by_name(
        self,
        provider_name: str,
    ) -> Provider | None:
        """
        Get provider by provider name.

        Args:
            provider_name: Provider name.

        Returns:
            Provider or None if not found.
        """
        return await self.provider_repo.get_by_name(provider_name)

    async def get_by_owner_hash(
        self,
        owner_hash: str,
    ) -> Provider | None:
        """
        Get provider by owner hash.

        Args:
            owner_hash: Provider owner hash

        Returns:
            Provider or None if not found
        """
        return await self.provider_repo.get_by_owner_hash(owner_hash)

    async def authenticate_provider(
        self,
        api_token: str,
    ) -> Provider:
        """
        Authenticate provider by API token.

        Args:
            api_token: API token

        Returns:
            Authenticated provider

        Raises:
            AuthenticationError: If authentication fails
        """
        provider = await self.get_by_token(api_token)

        if not provider:
            raise AuthenticationError("Invalid API token")

        if not provider.is_active:
            raise AuthenticationError("Provider account is inactive")

        return provider

    async def deactivate_provider(
        self,
        provider_hash: str,
    ) -> Provider:
        """
        Deactivate provider account.

        Args:
            provider_hash: Provider hash

        Returns:
            Updated provider
        """
        provider = await self.set_active(
            provider_hash,
            False,
        )

        logger.info(
            "Provider deactivated: provider_hash=%s",
            provider_hash,
        )

        return provider

    async def activate_provider(
        self,
        provider_hash: str,
    ) -> Provider:
        """
        Activate provider account.

        Args:
            provider_hash: Provider hash

        Returns:
            Updated provider
        """
        provider = await self.set_active(
            provider_hash,
            True,
        )

        logger.info(
            "Provider activated: provider_hash=%s",
            provider_hash,
        )

        return provider

    async def resolve_managed_user_hash(
        self,
        provider: Provider,
        user_id: int,
    ) -> str:
        """
        Resolve the target user_hash for a provider-facing subscription
        request, verifying the provider is authorized to act on that
        user's behalf.

        Used by the /provider/{user_id}/subs routes: the provider
        authenticates with its own API token, then names which user's
        subscriptions it wants to manage via user_id in the path. This
        method is the single choke point that turns that (provider,
        user_id) pair into a trusted user_hash — or rejects it.

        Args:
            provider: The authenticated provider (already verified active
                      by ProviderService.authenticate_provider)
            user_id: Target user's numeric id, from the request path

        Returns:
            The target user's user_hash

        Raises:
            NotFoundError: If no user exists with that user_id
            AuthorizationError: If the provider is not authorized for
                                 this user
        """
        user: User | None = await self.user_service.get_by_user_id(user_id)

        if not user:
            raise NotFoundError("User not found")

        await self.authorization_service.require_authorized(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        return user.user_hash
