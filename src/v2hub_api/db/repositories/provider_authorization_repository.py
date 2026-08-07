from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from v2hub_api.db.models import ProviderAuthorization, ProviderAuthorizationStatus
from v2hub_api.db.repositories.base import BaseRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ═══════════════════════════════════════════════════════════════════════════
# ProviderAuthorization Repository
# ═══════════════════════════════════════════════════════════════════════════
class ProviderAuthorizationRepository(BaseRepository[ProviderAuthorization]):
    """Repository for ProviderAuthorization model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ProviderAuthorization, session)

    async def get_by_hash(
        self,
        hashes: tuple[str, str],
    ) -> ProviderAuthorization | None:
        """Get authorization by (provider_hash, user_hash)."""
        return await self.get_by_id(hashes)

    async def get_approved(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization | None:
        """
        Get an authorization only if it exists AND is currently approved.

        This is the check that matters for access control — a revoked
        row must never grant access, so callers that care about
        authorization (not just history) should use this instead of
        get_by_hash.
        """
        stmt = select(ProviderAuthorization).where(
            ProviderAuthorization.provider_hash == provider_hash,
            ProviderAuthorization.user_hash == user_hash,
            ProviderAuthorization.status == ProviderAuthorizationStatus.APPROVED,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_approved_provider_hashes(
        self,
        user_hash: str,
    ) -> set[str]:
        """
        Get hashes of all providers currently approved by the user.
        """
        stmt = select(ProviderAuthorization.provider_hash).where(
            ProviderAuthorization.user_hash == user_hash,
            ProviderAuthorization.status == ProviderAuthorizationStatus.APPROVED,
        )

        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def get_user_approved_providers_count(
        self,
        user_hash: str,
    ) -> int:
        """Get number of providers authorized by user (any status)."""
        stmt = (
            select(func.count())
            .select_from(ProviderAuthorization)
            .where(
                ProviderAuthorization.user_hash == user_hash,
                ProviderAuthorization.status == ProviderAuthorizationStatus.APPROVED,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_approved_user_hashes(
        self,
        provider_hash: str,
    ) -> set[str]:
        """
        Get hashes of all users currently approved for the provider.
        """
        stmt = select(ProviderAuthorization.user_hash).where(
            ProviderAuthorization.provider_hash == provider_hash,
            ProviderAuthorization.status == ProviderAuthorizationStatus.APPROVED,
        )

        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def get_provider_approved_users_count(
        self,
        provider_hash: str,
    ) -> int:
        """
        Get number of users currently approved for the provider.
        """
        stmt = (
            select(func.count())
            .select_from(ProviderAuthorization)
            .where(
                ProviderAuthorization.provider_hash == provider_hash,
                ProviderAuthorization.status == ProviderAuthorizationStatus.APPROVED,
            )
        )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_all_for_user(
        self,
        user_hash: str,
    ) -> list[ProviderAuthorization]:
        """Get all provider authorizations for user (any status)."""
        stmt = (
            select(ProviderAuthorization)
            .where(ProviderAuthorization.user_hash == user_hash)
            .options(selectinload(ProviderAuthorization.provider))
        )
        result = await self.session.execute(stmt)
        return cast("list[ProviderAuthorization]", result.scalars().all())

    async def get_all_for_provider(
        self,
        provider_hash: str,
    ) -> list[ProviderAuthorization]:
        """Get all authorizations (any status) issued to a provider."""
        stmt = (
            select(ProviderAuthorization)
            .where(ProviderAuthorization.provider_hash == provider_hash)
            .options(selectinload(ProviderAuthorization.user))
        )
        result = await self.session.execute(stmt)
        return cast("list[ProviderAuthorization]", result.scalars().all())

    async def create_authorization(
        self,
        provider_hash: str,
        user_hash: str,
    ) -> ProviderAuthorization:
        """Create new authorization (defaults to APPROVED via model default)."""
        return await self.create(
            provider_hash=provider_hash,
            user_hash=user_hash,
        )

    async def set_status(
        self,
        authorization: ProviderAuthorization,
        status: ProviderAuthorizationStatus,
    ) -> ProviderAuthorization:
        """Update the status of an existing authorization (approve/revoke)."""
        return await self.update(authorization, status=status)
