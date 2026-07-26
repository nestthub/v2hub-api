from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.db.models import User
from v2hub_api.db.repositories.base import BaseRepository

# ═══════════════════════════════════════════════════════════════════════════
# User Repository
# ═══════════════════════════════════════════════════════════════════════════


class UserRepository(BaseRepository[User]):
    """Repository for User model operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_hash(self, user_hash: str) -> User | None:
        """Get user by hash."""
        return await self.get_by_id(user_hash)

    async def get_by_user_id(self, user_id: int) -> User | None:
        """Get user by original user ID."""
        stmt = select(User).where(User.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_api_token(self, api_token: str) -> User | None:
        """Get user by API token."""
        stmt = select(User).where(User.api_token == api_token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self, user_hash: str, user_id: int, api_token: str, is_active: bool = True
    ) -> User:
        """Create new user."""
        return await self.create(
            user_hash=user_hash, user_id=user_id, api_token=api_token, is_active=is_active
        )

    async def update_api_token(self, user: User, api_token: str) -> User:
        """Update user's API token."""
        return await self.update(user, api_token=api_token)
