"""Tests for v2hub_api.services.user_service.UserService."""

import pytest

from v2hub_api.core.exceptions import AuthenticationError, NotFoundError, ValidationError
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


class TestCreateUser:
    async def test_creates_user_with_generated_credentials(self, db_session):
        service = UserService(db_session)
        user = await service.create_user(user_id=42)

        assert user.user_id == 42
        assert user.is_active is True
        assert user.user_hash  # non-empty, generated
        assert user.api_token  # non-empty, generated

    async def test_raises_if_user_already_exists(self, db_session):
        service = UserService(db_session)
        await service.create_user(user_id=42)

        with pytest.raises(ValidationError):
            await service.create_user(user_id=42)

    async def test_generated_hashes_and_tokens_are_unique(self, db_session):
        service = UserService(db_session)
        user1 = await service.create_user(user_id=1)
        user2 = await service.create_user(user_id=2)

        assert user1.user_hash != user2.user_hash
        assert user1.api_token != user2.api_token


class TestGetUser:
    async def test_returns_user_when_found(self, db_session):
        service = UserService(db_session)
        await service.create_user(user_id=42)

        user = await service.get_user(user_id=42)
        assert user.user_id == 42

    async def test_raises_not_found_when_missing(self, db_session):
        service = UserService(db_session)
        with pytest.raises(NotFoundError):
            await service.get_user(user_id=999)


class TestSetActive:
    async def test_updates_active_status(self, db_session):
        service = UserService(db_session)
        await service.create_user(user_id=42)

        updated = await service.set_active(user_id=42, is_active=False)
        assert updated.is_active is False

    async def test_is_idempotent_when_status_unchanged(self, db_session):
        service = UserService(db_session)
        user = await service.create_user(user_id=42)

        result = await service.set_active(user_id=42, is_active=True)
        assert result.is_active is True
        # Same user row returned without error
        assert result.user_hash == user.user_hash

    async def test_raises_not_found_when_missing(self, db_session):
        service = UserService(db_session)
        with pytest.raises(NotFoundError):
            await service.set_active(user_id=999, is_active=False)


class TestDeleteUser:
    async def test_deletes_existing_user(self, db_session):
        service = UserService(db_session)
        await service.create_user(user_id=42)

        await service.delete_user(user_id=42)

        with pytest.raises(NotFoundError):
            await service.get_user(user_id=42)

    async def test_raises_validation_error_when_missing(self, db_session):
        service = UserService(db_session)
        with pytest.raises(ValidationError):
            await service.delete_user(user_id=999)


class TestRefreshToken:
    async def test_returns_new_token_and_persists_it(self, db_session):
        service = UserService(db_session)
        user = await service.create_user(user_id=42)
        old_token = user.api_token

        new_token = await service.refresh_token(user_id=42)

        assert new_token != old_token
        refetched = await service.get_by_token(new_token)
        assert refetched is not None
        assert refetched.user_id == 42

        # old token no longer valid
        assert await service.get_by_token(old_token) is None

    async def test_raises_not_found_when_missing(self, db_session):
        service = UserService(db_session)
        with pytest.raises(NotFoundError):
            await service.refresh_token(user_id=999)


class TestGetByToken:
    async def test_returns_user(self, db_session):
        service = UserService(db_session)
        user = await service.create_user(user_id=42)

        found = await service.get_by_token(user.api_token)
        assert found is not None
        assert found.user_id == 42

    async def test_returns_none_when_missing(self, db_session):
        service = UserService(db_session)
        assert await service.get_by_token("nonexistent") is None


class TestAuthenticateUser:
    async def test_succeeds_for_active_user(self, db_session):
        service = UserService(db_session)
        user = await service.create_user(user_id=42)

        authenticated = await service.authenticate_user(user.api_token)
        assert authenticated.user_id == 42

    async def test_raises_for_invalid_token(self, db_session):
        service = UserService(db_session)
        with pytest.raises(AuthenticationError):
            await service.authenticate_user("bad-token")

    async def test_raises_for_inactive_user(self, db_session):
        service = UserService(db_session)
        user = await service.create_user(user_id=42)
        await service.deactivate_user(user_id=42)

        with pytest.raises(AuthenticationError):
            await service.authenticate_user(user.api_token)


class TestDeactivateActivateUser:
    async def test_deactivate_user(self, db_session):
        service = UserService(db_session)
        await service.create_user(user_id=42)

        updated = await service.deactivate_user(user_id=42)
        assert updated.is_active is False

    async def test_activate_user(self, db_session):
        service = UserService(db_session)
        await service.create_user(user_id=42)
        await service.deactivate_user(user_id=42)

        updated = await service.activate_user(user_id=42)
        assert updated.is_active is True

    async def test_deactivate_raises_not_found(self, db_session):
        service = UserService(db_session)
        with pytest.raises(NotFoundError):
            await service.deactivate_user(user_id=999)

    async def test_activate_raises_not_found(self, db_session):
        service = UserService(db_session)
        with pytest.raises(NotFoundError):
            await service.activate_user(user_id=999)
