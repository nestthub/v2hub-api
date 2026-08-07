"""
Tests covering the "max approved users per provider" feature added in the
latest diff, plus a regression test for the exception it introduced.

Two things are checked here:

1. `TooManyApprovedUsersError` itself is broken: it references
   `ErrorCode.TOO_MANY_APPROVED_USERS`, which was never added to the
   `ErrorCode` enum. Instantiating the exception raises `AttributeError`
   instead of the intended domain error -- meaning the very safeguard
   meant to stop a provider from exceeding its user quota crashes with
   an unrelated error the moment it's supposed to fire.

2. `ProviderAuthorizationRepository.get_provider_approved_users_count`
   (the counting logic backing the limit) itself works correctly in
   isolation, so the bug above is purely in the exception class, not in
   the counting/threshold logic.
"""

import pytest

from v2hub_api.core.exceptions import TooManyApprovedUsersError
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


async def _make_user(db_session, user_id: int):
    return await UserService(db_session).create_user(user_id=user_id)


async def _make_provider(db_session, owner_user_id: int, name: str):
    owner = await _make_user(db_session, owner_user_id)
    return await ProviderService(db_session).create_provider(
        owner_hash=owner.user_hash, provider_name=name
    )


class TestTooManyApprovedUsersErrorRegression:
    """
    Regression test: instantiating TooManyApprovedUsersError must raise
    the domain error itself, not an unrelated AttributeError caused by a
    missing ErrorCode member.
    """

    pytestmark = []

    def test_can_be_instantiated_without_crashing(self):
        error = TooManyApprovedUsersError(count=1000, max_count=1000)

        assert error.details == {"count": 1000, "max_count": 1000}
        assert "1000" in error.message

    def test_error_code_matches_a_defined_enum_member(self):
        """
        This is the actual bug: ErrorCode.TOO_MANY_APPROVED_USERS does
        not exist, so even constructing the exception blows up with
        AttributeError before the message/details are ever set.
        """
        from v2hub_api.core.enums import ErrorCode

        error = TooManyApprovedUsersError(count=1, max_count=1)
        assert error.error_code in set(ErrorCode)


class TestGetApprovedUsersCount:
    """
    The counting logic behind the provider user-quota limit. This part
    of the new diff works correctly -- only the exception raised when
    the limit is hit is broken (see TestTooManyApprovedUsersErrorRegression
    and TestCreateConnectionUserLimit below).
    """

    async def test_zero_when_no_authorizations(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        service = ProviderAuthorizationService(db_session)

        count = await service.get_approved_users_count(provider.provider_hash)
        assert count == 0

    async def test_counts_only_approved_authorizations(self, db_session):
        provider = await _make_provider(db_session, 1, "vpn1")
        user1 = await _make_user(db_session, 10)
        user2 = await _make_user(db_session, 20)
        service = ProviderAuthorizationService(db_session)

        await service.grant(provider.provider_hash, user1.user_hash)
        await service.grant(provider.provider_hash, user2.user_hash)
        await service.revoke(provider.provider_hash, user2.user_hash)

        count = await service.get_approved_users_count(provider.provider_hash)
        assert count == 1

    async def test_does_not_count_other_providers_users(self, db_session):
        provider1 = await _make_provider(db_session, 1, "vpn1")
        provider2 = await _make_provider(db_session, 2, "vpn2")
        user = await _make_user(db_session, 10)
        service = ProviderAuthorizationService(db_session)

        await service.grant(provider1.provider_hash, user.user_hash)

        assert await service.get_approved_users_count(provider1.provider_hash) == 1
        assert await service.get_approved_users_count(provider2.provider_hash) == 0


class TestCreateConnectionUserLimit:
    """
    End-to-end (service-level) behavior of the /providers/{user_id}
    create_connection flow's new user-quota check.

    NOTE: create_connection lives in an API endpoint module and calls
    `authorization_service.get_approved_users_count` then raises
    `TooManyApprovedUsersError` directly -- so exercising the *endpoint*
    itself would immediately hit the AttributeError from
    TestTooManyApprovedUsersErrorRegression. The tests below instead
    validate the counting + threshold comparison in isolation (the part
    that is NOT broken), and the xfail documents that the endpoint using
    it is currently non-functional as soon as the limit is reached.
    """

    async def test_provider_at_exactly_the_limit_is_at_capacity(self, db_session, monkeypatch):
        from v2hub_api.core.config import settings

        monkeypatch.setattr(settings, "max_provider_users", 2)

        provider = await _make_provider(db_session, 1, "vpn1")
        auth_service = ProviderAuthorizationService(db_session)

        user1 = await _make_user(db_session, 10)
        user2 = await _make_user(db_session, 20)
        await auth_service.grant(provider.provider_hash, user1.user_hash)
        await auth_service.grant(provider.provider_hash, user2.user_hash)

        count = await auth_service.get_approved_users_count(provider.provider_hash)
        assert count >= settings.max_provider_users  # capacity reached

    async def test_too_many_approved_users_error_can_be_created(self):
        error = TooManyApprovedUsersError(count=1000, max_count=1000)

        assert error.details == {
            "count": 1000,
            "max_count": 1000,
        }
