"""
User management service.

Handles user creation, token management, and authentication.
"""

import logging
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from v2hub_api.core.config import settings
from v2hub_api.core.exceptions import AuthenticationError, NotFoundError, ValidationError
from v2hub_api.db.models import User
from v2hub_api.db.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class UserService:
    """
    Service for user management operations.

    Features:
    - Create users with generated tokens
    - Refresh API tokens
    - Authenticate users
    - User lookup
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize user service.

        Args:
            session: Database session
        """
        self.session = session
        self.user_repo = UserRepository(session)

    def _generate_user_hash(self) -> str:
        """
        Generate stable hash from user ID.

        Args:
            user_id: External user ID

        Returns:
            User hash
        """
        # Combine user_id with secret for uniqueness
        return str(uuid.uuid4())

    def _generate_api_token(self) -> str:
        """
        Generate API token bound to user_id.

        Returns:
            Token in format: {user_id}:{random_token}
        """
        token = secrets.token_urlsafe(settings.api_token_length)
        return token

    async def create_user(self, user_id: int) -> User:
        """
        Create a new user account.

        Args:
            user_id: External user ID

        Returns:
            Created user

        Raises:
            ValidationError: If user already exists
        """
        # Check if user already exists
        existing_user = await self.user_repo.get_by_user_id(user_id)
        if existing_user:
            raise ValidationError(f"User with ID {user_id} already exists")

        # Generate credentials
        user_hash = self._generate_user_hash()
        api_token = self._generate_api_token()

        # Create user
        user = await self.user_repo.create_user(
            user_hash=user_hash, user_id=user_id, api_token=api_token, is_active=True
        )

        await self.session.commit()

        logger.info(f"User created: user_id={user_id}, user_hash={user_hash}")

        return user

    async def get_user(self, user_id: int) -> User:
        """
        Get user account.

        Args:
            user_id: External user ID

        Returns:
            User

        Raises:
            NotFoundError: User not found
        """
        user = await self.get_by_user_id(user_id)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")

        return user

    async def set_active(self, user_id: int, is_active: bool) -> User:
        """
        Update user active status.

        Args:
            user_id: External user ID
            is_active: New state

        Returns:
            Updated user

        Raises:
            NotFoundError: User not found
        """

        user = await self.user_repo.get_by_user_id(user_id)

        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")

        # Idempotency: avoid unnecessary DB writes
        if user.is_active == is_active:
            return user

        user.is_active = is_active

        await self.session.commit()
        await self.session.refresh(user)

        return user

    async def delete_user(self, user_id: int) -> None:
        """
        Delete user account.

        Args:
            user_id: External user ID

        Returns:
            None

        Raises:
            NotFoundError: User not found
        """

        user = await self.user_repo.get_by_user_id(user_id)
        if not user:
            raise ValidationError(f"User with ID {user_id} not found")

        await self.user_repo.delete(user)
        await self.session.commit()

    async def refresh_token(self, user_id: int) -> str:
        """
        Refresh user's API token.

        Args:
            user_id: User ID

        Returns:
            New API token

        Raises:
            NotFoundError: If user not found
        """
        # Get user
        user = await self.user_repo.get_by_user_id(user_id)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")

        # Generate new token
        new_token = self._generate_api_token()

        # Update user
        await self.user_repo.update_api_token(user, new_token)
        await self.session.commit()

        logger.info(f"Token refreshed for user_id={user_id}")

        return new_token

    async def get_by_token(self, api_token: str) -> User | None:
        """
        Get user by API token.

        Args:
            api_token: API token

        Returns:
            User or None if not found
        """
        return await self.user_repo.get_by_api_token(api_token)

    async def get_by_user_id(self, user_id: int) -> User | None:
        """
        Get user by user ID.

        Args:
            user_id: User ID

        Returns:
            User or None if not found
        """
        return await self.user_repo.get_by_user_id(user_id)

    async def authenticate_user(self, api_token: str) -> User:
        """
        Authenticate user by API token.

        Args:
            api_token: API token

        Returns:
            Authenticated user

        Raises:
            AuthenticationError: If authentication fails
        """
        user = await self.get_by_token(api_token)

        if not user:
            raise AuthenticationError("Invalid API token")

        if not user.is_active:
            raise AuthenticationError("User account is inactive")

        return user

    async def authenticate_user_by_id(
        self,
        user_id: int,
    ) -> User:
        """
        Get an active user by user ID.

        Args:
            user_id: External user identifier.

        Returns:
            Authenticated user.

        Raises:
            AuthenticationError: If the user does not exist or is inactive.
        """
        user = await self.get_by_user_id(user_id)

        if user is None:
            raise AuthenticationError("User not found")

        if not user.is_active:
            raise AuthenticationError("User account is inactive")

        return user

    async def deactivate_user(self, user_id: int) -> User:
        """
        Deactivate user account.

        Args:
            user_id: User ID

        Returns:
            Updated user

        Raises:
            NotFoundError: If user not found
        """
        user = await self.user_repo.get_by_user_id(user_id)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")

        user.is_active = False
        await self.session.commit()

        logger.info(f"User deactivated: user_id={user_id}")

        return user

    async def activate_user(self, user_id: int) -> User:
        """
        Activate user account.

        Args:
            user_id: User ID

        Returns:
            Updated user

        Raises:
            NotFoundError: If user not found
        """
        user = await self.user_repo.get_by_user_id(user_id)
        if not user:
            raise NotFoundError(f"User with ID {user_id} not found")

        user.is_active = True
        await self.session.commit()

        logger.info(f"User activated: user_id={user_id}")

        return user
