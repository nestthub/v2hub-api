from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.models import Provider
from v2hub_api.db.repositories.base import BaseRepository

# ═══════════════════════════════════════════════════════════════════════════
# Provider Repository
# ═══════════════════════════════════════════════════════════════════════════


class ProviderRepository(BaseRepository[Provider]):
    """Repository for Provider model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Provider, session)

    async def get_by_hash(self, provider_hash: str) -> Provider | None:
        """Get provider by hash."""
        return await self.get_by_id(provider_hash)

    async def get_by_owner_hash(self, owner_hash: str) -> Provider | None:
        """Get provider by owner_hash."""
        stmt = select(Provider).where(Provider.owner_hash == owner_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_api_token(self, api_token: str) -> Provider | None:
        """Get provider by API token."""
        stmt = select(Provider).where(Provider.api_token == api_token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, provider_name: str) -> Provider | None:
        """Get provider by name."""
        stmt = select(Provider).where(Provider.provider_name == provider_name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_provider(
        self,
        provider_hash: str,
        owner_hash: str,
        provider_name: str,
        api_token: str,
        provider_url: str | None = None,
        is_active: bool = True,
    ) -> Provider:
        """Create new provider."""
        return await self.create(
            provider_hash=provider_hash,
            owner_hash=owner_hash,
            provider_name=provider_name,
            api_token=api_token,
            provider_url=provider_url,
            is_active=is_active,
        )

    async def update_provider_url(self, provider: Provider, provider_url: str | None) -> Provider:
        "Update provider's url"
        return await self.update(provider, provider_url=provider_url)

    async def update_api_token(self, provider: Provider, api_token: str) -> Provider:
        """Update provider's API token."""
        return await self.update(provider, api_token=api_token)

    async def update_provider_name(self, provider: Provider, provider_name: str) -> Provider:
        """Update provider's name."""
        return await self.update(provider, provider_name=provider_name)
