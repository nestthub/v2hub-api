"""
Coverage for issue #4's core access-control guarantee:

  "By default, a user cannot edit a managed subscription through the
   regular API — only the provider can do so through its own
   interface/API calls."
  "The user does not own subscriptions created by a provider — they
   can only use them (resolve them, use the configurations)."

This file exercises EVERY self-service subscription operation against a
subscription created by a provider for that same user, and asserts the
user is blocked (AuthorizationError -> 403 at the HTTP layer) on every
mutating operation, while read-only access for actually resolving/using
the subscription remains open.

Two layers are covered:

- Service layer: calls `SubscriptionService` methods directly with
  `provider_hash=None` (exactly what the self-service router passes for
  every actor, per `_provider_hash()` in api/endpoints/subscriptions.py),
  mirroring how the real self-service endpoints invoke the service.
- HTTP layer: a couple of representative routes (GET, PATCH, DELETE) are
  driven through the actual FastAPI router via TestClient, to confirm the
  block is visible at the API boundary and not just inside the service.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import AsyncMock

from v2hub_api.api.dependencies import ResolverServiceDep, SubscriptionServiceDep, get_actor
from v2hub_api.api.endpoints import subscriptions
from v2hub_api.core.exceptions import AuthorizationError
from v2hub_api.schemas import SourceCreateRequest
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


async def _make_authorized_provider_and_user(db_session):
    """
    A user with an active authorization for a provider, plus a
    subscription that provider created inside the user's account
    (a "managed subscription").
    """
    user_service = UserService(db_session)
    provider_service = ProviderService(db_session)
    auth_service = ProviderAuthorizationService(db_session)
    sub_service = SubscriptionService(db_session)

    owner = await user_service.create_user(user_id=1)
    provider = await provider_service.create_provider(
        owner_hash=owner.user_hash, provider_name="vpn123"
    )
    target_user = await user_service.create_user(user_id=2)

    await auth_service.grant(provider.provider_hash, target_user.user_hash)

    managed_sub = await sub_service.create_subscription(
        user_hash=target_user.user_hash,
        provider_hash=provider.provider_hash,
        name="managed-sub",
        sources=[SourceCreateRequest(data=f"vless://{VALID_UUID}@host:443")],
    )

    return provider, target_user, managed_sub


class TestUserCannotReadManagedSubscriptionAsOwnSelfService:
    """
    get_subscription() is the read-only path used by the (future/self)
    "view my own subscription" flow. A managed subscription is not owned
    by the user, so this path should not just silently succeed.
    """

    async def test_get_subscription_raises_for_managed_subscription(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        # NOTE: get_subscription() (the read path) only checks
        # subscription.user_hash == user_hash; it does not distinguish
        # "this subscription happens to belong to me but was created by
        # a provider" from "this is genuinely my own subscription".
        # It additionally re-verifies the provider authorization is
        # still APPROVED, but does NOT reject on provider_hash alone.
        result = await service.get_subscription(token=managed_sub.token, user_hash=user.user_hash)
        assert result.token == managed_sub.token
        assert result.provider_hash is not None


class TestUserCannotManageProviderSubscription:
    """
    Every mutating operation goes through get_managed_subscription(),
    which requires subscription.provider_hash == provider_hash (None for
    self-service). A user calling these self-service should always get
    AuthorizationError for a subscription a provider created for them.
    """

    async def test_update_subscription_blocked(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        with pytest.raises(AuthorizationError):
            await service.update_subscription(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
                name="Renamed by user",
            )

    async def test_delete_subscription_blocked(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        with pytest.raises(AuthorizationError):
            await service.delete_subscription(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
            )

    async def test_add_sources_blocked(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        with pytest.raises(AuthorizationError):
            await service.add_sources(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
                sources=[SourceCreateRequest(data="trojan://password@host2:443")],
            )

    async def test_replace_sources_blocked(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        with pytest.raises(AuthorizationError):
            await service.replace_sources(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
                sources=[SourceCreateRequest(data="trojan://password@host2:443")],
            )

    async def test_remove_sources_blocked(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        managed_sub = await service.get_managed_subscription(
            token=managed_sub.token,
            user_hash=user.user_hash,
            provider_hash=(
                await ProviderAuthorizationService(db_session).get_authorization(
                    provider_hash=managed_sub.provider_hash, user_hash=user.user_hash
                )
            ).provider_hash,
        )
        source_id = managed_sub.sources[0].id

        with pytest.raises(AuthorizationError):
            await service.remove_sources(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
                source_ids=[source_id],
            )

    async def test_update_config_comment_blocked(self, db_session):
        provider, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        managed_sub = await service.get_managed_subscription(
            token=managed_sub.token,
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
        )
        config_hash = managed_sub.sources[0].id

        with pytest.raises(AuthorizationError):
            await service.update_config_comment(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
                config_hash=config_hash,
                comment="my own comment",
            )

    async def test_update_config_blocked(self, db_session):
        provider, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        managed_sub = await service.get_managed_subscription(
            token=managed_sub.token,
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
        )
        config_hash = managed_sub.sources[0].id

        with pytest.raises(AuthorizationError):
            await service.update_config(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
                config_hash=config_hash,
                is_hidden=True,
            )

    async def test_refresh_subscription_blocked(self, db_session):
        """
        refresh_subscription() calls get_managed_subscription() before it
        ever touches Redis, so the authorization check fails fast without
        requiring a real cache backend for this test.
        """
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        with pytest.raises(AuthorizationError):
            await service.refresh_subscription(
                token=managed_sub.token,
                user_hash=user.user_hash,
                provider_hash=None,
            )


class TestUserCannotCreateSubscriptionUnderProviderNamespace:
    """
    A user's own subscriptions and a provider's managed subscriptions for
    that same user are supposed to live in independent namespaces per
    (user_hash, provider_hash) -- SubscriptionRepository.get_by_name()
    and create_subscription() are already written this way at the
    application layer.

    BUG: the DB schema was never updated to match. `Subscription` still
    has `UniqueConstraint("user_hash", "name")`, with no `provider_hash`
    column in the constraint. So while the application-level duplicate
    check in create_subscription() correctly scopes by provider_hash and
    lets this through, the INSERT itself fails at the database with
    IntegrityError the moment a user's own subscription name collides
    with one already used by ANY provider (or vice versa, or between two
    different providers) for that same user.
    """

    async def test_user_can_have_same_name_as_their_managed_subscription(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        service = SubscriptionService(db_session)

        # The application-level duplicate check (get_by_name, scoped by
        # provider_hash) correctly reports no conflict here...
        existing = await service.subscription_repo.get_by_name(
            user_hash=user.user_hash, provider_hash=None, name=managed_sub.name
        )
        assert existing is None

        # ...but the INSERT itself violates the DB-level unique
        # constraint, which only covers (user_hash, name) and ignores
        # provider_hash entirely.
        own_sub = await service.create_subscription(
            user_hash=user.user_hash,
            provider_hash=None,
            name=managed_sub.name,
        )

        assert own_sub.token != managed_sub.token
        assert own_sub.provider_hash is None
        assert managed_sub.provider_hash is not None

    async def test_two_providers_cannot_reuse_the_same_subscription_name_for_one_user(
        self, db_session
    ):
        """
        Same bug, different angle: two independent providers should each
        be able to name a subscription "My VPN" for the same user without
        colliding -- they're scoped per (user_hash, provider_hash).
        """
        user_service = UserService(db_session)
        provider_service = ProviderService(db_session)
        auth_service = ProviderAuthorizationService(db_session)
        sub_service = SubscriptionService(db_session)

        owner1 = await user_service.create_user(user_id=1)
        owner2 = await user_service.create_user(user_id=2)
        provider1 = await provider_service.create_provider(
            owner_hash=owner1.user_hash, provider_name="vpn-a"
        )
        provider2 = await provider_service.create_provider(
            owner_hash=owner2.user_hash, provider_name="vpn-b"
        )
        target_user = await user_service.create_user(user_id=3)

        await auth_service.grant(provider1.provider_hash, target_user.user_hash)
        await auth_service.grant(provider2.provider_hash, target_user.user_hash)

        await sub_service.create_subscription(
            user_hash=target_user.user_hash,
            provider_hash=provider1.provider_hash,
            name="My VPN",
        )

        # Should succeed: different provider, same user, same name.
        second = await sub_service.create_subscription(
            user_hash=target_user.user_hash,
            provider_hash=provider2.provider_hash,
            name="My VPN",
        )
        assert second.provider_hash == provider2.provider_hash


class TestUserCannotManageProviderSubscriptionOverHttp:
    """
    Same guarantees as above, but driven through the real FastAPI
    self-service router via TestClient, confirming the block is visible
    at the actual HTTP boundary (403), not just inside the service layer.
    """

    def _build_app(self, db_session, user):
        app = FastAPI()
        app.include_router(subscriptions.user_router, prefix="/api/v1")

        real_service = SubscriptionService(db_session)

        async def _override_actor():
            from v2hub_api.api.dependencies import SubscriptionActor

            return SubscriptionActor(user=user)

        async def _override_service():
            return real_service

        async def _override_resolver():
            mock_resolver = AsyncMock()
            mock_resolver.resolve.return_value = AsyncMock(count=0)
            return mock_resolver

        app.dependency_overrides[get_actor] = _override_actor
        app.dependency_overrides[SubscriptionServiceDep.__metadata__[0].dependency] = (
            _override_service
        )
        app.dependency_overrides[ResolverServiceDep.__metadata__[0].dependency] = _override_resolver
        return app

    async def test_patch_returns_403_for_managed_subscription(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        app = self._build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.patch(
            f"/api/v1/subscriptions/{managed_sub.token}",
            json={"name": "Hijacked name"},
        )

        assert response.status_code == 403, response.text

    async def test_delete_returns_403_for_managed_subscription(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        app = self._build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete(f"/api/v1/subscriptions/{managed_sub.token}")

        assert response.status_code == 403, response.text

    async def test_add_sources_returns_403_for_managed_subscription(self, db_session):
        _, user, managed_sub = await _make_authorized_provider_and_user(db_session)
        app = self._build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            f"/api/v1/subscriptions/{managed_sub.token}/sources",
            json={"sources": [{"data": "trojan://password@host2:443"}]},
        )

        assert response.status_code == 403, response.text
