"""Tests for v2hub_api.services.provider_service.ProviderService.

Covers what's implemented per issue #4 (VPN Provider, Authorization,
Managed Subscriptions, and Limits):

- Provider entity CRUD (create/get/delete/list)
- Token generation & refresh
- Authentication by api_token (incl. inactive provider rejection)
- Activate/deactivate

NOT covered here because not implemented yet (see issue checklist):
- Limit on number of connected users per provider (default 1000) — no
  enforcement exists anywhere in ProviderService/ProviderRepository.
- A "connected users" counter field on the Provider model — the issue
  requires the provider to store this, but no such column exists.
"""

import pytest

from v2hub_api.core.exceptions import AuthenticationError, NotFoundError, ValidationError
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


async def _make_owner(db_session, user_id: int = 1):
    user_service = UserService(db_session)
    return await user_service.create_user(user_id=user_id)


class TestCreateProvider:
    async def test_creates_provider_with_generated_credentials(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)

        provider = await service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
            provider_url="https://t.me/examplebot",
        )

        assert provider.owner_hash == owner.user_hash
        assert provider.provider_name == "vpn123"
        assert provider.provider_url == "https://t.me/examplebot"
        assert provider.provider_hash  # non-empty, generated
        assert provider.api_token  # non-empty, generated
        assert provider.is_active is True

    async def test_provider_url_is_optional(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)

        provider = await service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        assert provider.provider_url is None

    async def test_raises_if_provider_already_exists_for_owner(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)

        await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        with pytest.raises(ValidationError):
            await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn456")

    async def test_generated_hashes_and_tokens_are_unique(self, db_session):
        owner1 = await _make_owner(db_session, user_id=1)
        owner2 = await _make_owner(db_session, user_id=2)
        service = ProviderService(db_session)

        p1 = await service.create_provider(owner_hash=owner1.user_hash, provider_name="vpn1")
        p2 = await service.create_provider(owner_hash=owner2.user_hash, provider_name="vpn2")

        assert p1.provider_hash != p2.provider_hash
        assert p1.api_token != p2.api_token


class TestGetProvider:
    async def test_returns_provider_when_found(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        provider = await service.get_provider(created.provider_hash)
        assert provider.provider_hash == created.provider_hash

    async def test_raises_not_found_when_missing(self, db_session):
        service = ProviderService(db_session)
        with pytest.raises(NotFoundError):
            await service.get_provider("nonexistent-hash")


class TestGetByOwnerHash:
    async def test_returns_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        found = await service.get_by_owner_hash(owner.user_hash)
        assert found is not None
        assert found.provider_hash == created.provider_hash

    async def test_returns_none_when_missing(self, db_session):
        service = ProviderService(db_session)
        assert await service.get_by_owner_hash("nonexistent") is None


class TestGetAllProviders:
    async def test_returns_all_providers(self, db_session):
        owner1 = await _make_owner(db_session, user_id=1)
        owner2 = await _make_owner(db_session, user_id=2)
        service = ProviderService(db_session)
        await service.create_provider(owner_hash=owner1.user_hash, provider_name="vpn1")
        await service.create_provider(owner_hash=owner2.user_hash, provider_name="vpn2")

        providers = await service.get_all_providers()
        assert len(providers) == 2

    async def test_when_no_providers(self, db_session):
        service = ProviderService(db_session)
        assert await service.get_all_providers() == []


class TestSetActive:
    async def test_updates_active_status(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        updated = await service.set_active(created.provider_hash, is_active=False)
        assert updated.is_active is False

    async def test_is_idempotent_when_status_unchanged(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        result = await service.set_active(created.provider_hash, is_active=True)
        assert result.is_active is True
        assert result.provider_hash == created.provider_hash

    async def test_raises_not_found_when_missing(self, db_session):
        service = ProviderService(db_session)
        with pytest.raises(NotFoundError):
            await service.set_active("nonexistent-hash", is_active=False)


class TestActivateDeactivateProvider:
    async def test_deactivate_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        updated = await service.deactivate_provider(created.provider_hash)
        assert updated.is_active is False

    async def test_activate_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")
        await service.deactivate_provider(created.provider_hash)

        updated = await service.activate_provider(created.provider_hash)
        assert updated.is_active is True


class TestUpdateProviderUrl:
    async def test_updates_url(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        updated = await service.update_provider_url(
            created.provider_hash, "https://new-url.example"
        )
        assert updated.provider_url == "https://new-url.example"

    async def test_can_clear_url(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123", provider_url="https://x.example"
        )

        updated = await service.update_provider_url(created.provider_hash, None)
        assert updated.provider_url is None

    async def test_raises_not_found_when_missing(self, db_session):
        service = ProviderService(db_session)
        with pytest.raises(NotFoundError):
            await service.update_provider_url("nonexistent-hash", "https://x.example")


class TestDeleteProvider:
    async def test_deletes_existing_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        await service.delete_provider(created.provider_hash)

        with pytest.raises(NotFoundError):
            await service.get_provider(created.provider_hash)

    async def test_raises_not_found_when_missing(self, db_session):
        service = ProviderService(db_session)
        with pytest.raises(NotFoundError):
            await service.delete_provider("nonexistent-hash")


class TestRefreshProviderToken:
    async def test_returns_new_token_and_persists_it(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")
        old_token = created.api_token

        new_token = await service.refresh_provider_token(created.provider_hash)

        assert new_token != old_token
        refetched = await service.get_by_token(new_token)
        assert refetched is not None
        assert refetched.provider_hash == created.provider_hash

        # old token no longer valid
        assert await service.get_by_token(old_token) is None

    async def test_raises_not_found_when_missing(self, db_session):
        service = ProviderService(db_session)
        with pytest.raises(NotFoundError):
            await service.refresh_provider_token("nonexistent-hash")


class TestGetByToken:
    async def test_returns_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        found = await service.get_by_token(created.api_token)
        assert found is not None
        assert found.provider_hash == created.provider_hash

    async def test_returns_none_when_missing(self, db_session):
        service = ProviderService(db_session)
        assert await service.get_by_token("nonexistent-token") is None


class TestAuthenticateProvider:
    async def test_succeeds_for_active_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        authenticated = await service.authenticate_provider(created.api_token)
        assert authenticated.provider_hash == created.provider_hash

    async def test_raises_for_invalid_token(self, db_session):
        service = ProviderService(db_session)
        with pytest.raises(AuthenticationError):
            await service.authenticate_provider("bad-token")

    async def test_raises_for_inactive_provider(self, db_session):
        owner = await _make_owner(db_session)
        service = ProviderService(db_session)
        created = await service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")
        await service.deactivate_provider(created.provider_hash)

        with pytest.raises(AuthenticationError):
            await service.authenticate_provider(created.api_token)


class TestResolveManagedUserHash:
    """
    Covers ProviderService.resolve_managed_user_hash — the choke point
    that turns (provider, user_id from path) into a trusted user_hash
    for /providers/{user_id}/subs style routes.
    """

    async def test_returns_user_hash_when_authorized(self, db_session):
        owner = await _make_owner(db_session, user_id=1)
        target_user = await _make_owner(db_session, user_id=2)
        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )

        await provider_service.authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=target_user.user_hash,
        )

        resolved_hash = await provider_service.resolve_managed_user_hash(
            provider=provider, user_id=target_user.user_id
        )
        assert resolved_hash == target_user.user_hash

    async def test_raises_not_found_for_unknown_user_id(self, db_session):
        owner = await _make_owner(db_session, user_id=1)
        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )

        with pytest.raises(NotFoundError):
            await provider_service.resolve_managed_user_hash(provider=provider, user_id=9999)

    async def test_raises_authorization_error_when_not_authorized(self, db_session):
        from v2hub_api.core.exceptions import AuthorizationError

        owner = await _make_owner(db_session, user_id=1)
        target_user = await _make_owner(db_session, user_id=2)
        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )
        # No authorization granted.

        with pytest.raises(AuthorizationError):
            await provider_service.resolve_managed_user_hash(
                provider=provider, user_id=target_user.user_id
            )

    async def test_raises_authorization_error_after_revocation(self, db_session):
        from v2hub_api.core.exceptions import AuthorizationError

        owner = await _make_owner(db_session, user_id=1)
        target_user = await _make_owner(db_session, user_id=2)
        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )
        await provider_service.authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=target_user.user_hash,
        )
        await provider_service.authorization_service.revoke(
            provider_hash=provider.provider_hash,
            user_hash=target_user.user_hash,
        )

        with pytest.raises(AuthorizationError):
            await provider_service.resolve_managed_user_hash(
                provider=provider, user_id=target_user.user_id
            )
