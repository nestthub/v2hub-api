"""Tests for v2hub_api.services.provider_authorization_service.ProviderAuthorizationService.

Covers the provider <-> user consent relationship from issue #4:
grant/re-approve, revoke, authorization checks used by provider-facing
routes, and listing.

"""

import pytest

from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.core.exceptions import AuthorizationError, NotFoundError
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


async def _make_user(db_session, user_id: int):
    return await UserService(db_session).create_user(user_id=user_id)


async def _make_provider(db_session, owner_user_id: int, name: str):
    owner = await _make_user(db_session, owner_user_id)
    return await ProviderService(db_session).create_provider(
        owner_hash=owner.user_hash, provider_name=name
    )


class TestGrant:
    async def test_creates_approved_authorization(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        auth = await service.grant(provider.provider_hash, user.user_hash)

        assert auth.status == ProviderAuthorizationStatus.APPROVED
        assert auth.provider_hash == provider.provider_hash
        assert auth.user_hash == user.user_hash

    async def test_is_idempotent_when_already_approved(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        first = await service.grant(provider.provider_hash, user.user_hash)
        second = await service.grant(provider.provider_hash, user.user_hash)

        assert first.provider_hash == second.provider_hash
        assert second.status == ProviderAuthorizationStatus.APPROVED

    async def test_re_approves_a_revoked_authorization(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        await service.grant(provider.provider_hash, user.user_hash)
        await service.revoke(provider.provider_hash, user.user_hash)

        re_granted = await service.grant(provider.provider_hash, user.user_hash)
        assert re_granted.status == ProviderAuthorizationStatus.APPROVED

    @pytest.mark.xfail(
        reason=(
            "Issue #4 checklist item not implemented: 'Default authorization "
            "limit: 5 active providers per user' -- grant() never checks "
            "get_user_providers_count before approving a 6th provider."
        ),
        strict=True,
    )
    async def test_rejects_sixth_active_authorization_for_same_user(self, db_session):
        user = await _make_user(db_session, 100)
        service = ProviderAuthorizationService(db_session)

        for i in range(5):
            provider = await _make_provider(db_session, owner_user_id=i + 1, name=f"vpn{i}")
            await service.grant(provider.provider_hash, user.user_hash)

        sixth_provider = await _make_provider(db_session, owner_user_id=6, name="vpn6")

        with pytest.raises(Exception):  # noqa: B017 -- any rejection is acceptable here
            await service.grant(sixth_provider.provider_hash, user.user_hash)


class TestRevoke:
    async def test_sets_status_to_revoked(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)

        revoked = await service.revoke(provider.provider_hash, user.user_hash)
        assert revoked.status == ProviderAuthorizationStatus.REVOKED

    async def test_is_idempotent_when_already_revoked(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)
        await service.revoke(provider.provider_hash, user.user_hash)

        result = await service.revoke(provider.provider_hash, user.user_hash)
        assert result.status == ProviderAuthorizationStatus.REVOKED

    async def test_raises_not_found_when_authorization_missing(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        with pytest.raises(NotFoundError):
            await service.revoke(provider.provider_hash, user.user_hash)

    async def test_revoked_provider_can_no_longer_act_on_user(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)
        await service.revoke(provider.provider_hash, user.user_hash)

        assert await service.is_authorized(provider.provider_hash, user.user_hash) is False
        with pytest.raises(AuthorizationError):
            await service.require_authorized(provider.provider_hash, user.user_hash)

    async def test_revocation_deletes_providers_managed_subscriptions_for_user(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        auth_service = ProviderAuthorizationService(db_session)
        sub_service = SubscriptionService(db_session)

        await auth_service.grant(provider.provider_hash, user.user_hash)
        sub = await sub_service.create_subscription(
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
            name="managed-sub",
        )

        await auth_service.revoke(provider.provider_hash, user.user_hash)

        provider_remaining = await sub_service.list_subscriptions(
            user_hash=user.user_hash, provider_hash=provider.provider_hash
        )
        assert provider_remaining == [sub]

        user_remaining = await sub_service.list_subscriptions(user_hash=user.user_hash)
        assert user_remaining == []


class TestDeleteAuthorization:
    async def test_removes_authorization_permanently(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)

        await service.delete_authorization(provider.provider_hash, user.user_hash)

        assert await service.get_authorization(provider.provider_hash, user.user_hash) is None

    async def test_raises_not_found_when_missing(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        with pytest.raises(NotFoundError):
            await service.delete_authorization(provider.provider_hash, user.user_hash)


class TestIsAuthorized:
    async def test_true_when_approved(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)

        assert await service.is_authorized(provider.provider_hash, user.user_hash) is True

    async def test_false_when_no_authorization_exists(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        assert await service.is_authorized(provider.provider_hash, user.user_hash) is False

    async def test_false_when_revoked(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)
        await service.revoke(provider.provider_hash, user.user_hash)

        assert await service.is_authorized(provider.provider_hash, user.user_hash) is False


class TestRequireAuthorized:
    async def test_returns_authorization_when_approved(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)

        auth = await service.require_authorized(provider.provider_hash, user.user_hash)
        assert auth.status == ProviderAuthorizationStatus.APPROVED

    async def test_raises_when_missing(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        with pytest.raises(AuthorizationError):
            await service.require_authorized(provider.provider_hash, user.user_hash)


class TestGetStatus:
    async def test_returns_current_status(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)
        await service.grant(provider.provider_hash, user.user_hash)

        status = await service.get_status(provider.provider_hash, user.user_hash)
        assert status == ProviderAuthorizationStatus.APPROVED

    async def test_raises_when_no_authorization_exists(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user = await _make_user(db_session, 2)
        service = ProviderAuthorizationService(db_session)

        with pytest.raises(AuthorizationError):
            await service.get_status(provider.provider_hash, user.user_hash)


class TestListProvidersForUser:
    async def test_lists_all_authorizations_any_status(self, db_session):
        user = await _make_user(db_session, 100)
        provider1 = await _make_provider(db_session, 1, "vpn1")
        provider2 = await _make_provider(db_session, 2, "vpn2")
        service = ProviderAuthorizationService(db_session)

        await service.grant(provider1.provider_hash, user.user_hash)
        await service.grant(provider2.provider_hash, user.user_hash)
        await service.revoke(provider2.provider_hash, user.user_hash)

        authorizations = await service.list_providers_for_user(user.user_hash)
        assert len(authorizations) == 2

    async def test_empty_list_when_no_authorizations(self, db_session):
        user = await _make_user(db_session, 100)
        service = ProviderAuthorizationService(db_session)

        assert await service.list_providers_for_user(user.user_hash) == []


class TestListUsersForProvider:
    async def test_lists_all_users_any_status(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user1 = await _make_user(db_session, 10)
        user2 = await _make_user(db_session, 20)
        service = ProviderAuthorizationService(db_session)

        await service.grant(provider.provider_hash, user1.user_hash)
        await service.grant(provider.provider_hash, user2.user_hash)
        await service.revoke(provider.provider_hash, user2.user_hash)

        authorizations = await service.list_users_for_provider(provider.provider_hash)
        assert len(authorizations) == 2

    async def test_one_provider_authorized_by_unlimited_users(self, db_session):
        """
        Issue #4: 'one provider can be authorized by any number of users' —
        the 5-authorization cap applies per-user, not per-provider.
        """
        provider = await _make_provider(db_session, 1, "vpn1")
        service = ProviderAuthorizationService(db_session)

        for i in range(10):
            user = await _make_user(db_session, 1000 + i)
            await service.grant(provider.provider_hash, user.user_hash)

        authorizations = await service.list_users_for_provider(provider.provider_hash)
        assert len(authorizations) == 10
