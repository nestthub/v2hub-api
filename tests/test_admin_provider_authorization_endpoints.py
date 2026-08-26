"""
Tests for `v2hub_api.api.endpoints.admin.provider_authorization` (the
`/admin/providers/auth` router used by the internal admin bot):

- GET  /admin/providers/auth/{provider_name}/{user_id}  -> status lookup
- POST /admin/providers/auth                            -> process a
  connection request (optionally verifying an invite HMAC)
- POST /admin/providers/auth/approve                    -> approve a
  PENDING authorization
- POST /admin/providers/auth/reject                     -> reject a
  PENDING/APPROVED authorization

All four require `AdminSecurityDep` (HMAC request signature) and
`InternalIPDep` (IP allowlist) -- both are exercised directly against
`verify_request_signature`/`verify_internal_ip` in
`test_admin_security.py`, so here we override those dependencies to
focus on the authorization business logic itself, the same way
`test_me_endpoints.py` overrides authentication to focus on `/me`.

This router previously had close to no dedicated coverage (~24%), so
these tests specifically target:
- the ordering bug where a user record used to get created before the
  provider-exists check (see admin/provider_authorization.py comments)
- HMAC verification on process_provider_authorization_request
- the MAX_PROVIDERS_PER_USER quota surfacing through /approve
- the subscriptions-exist branch in /reject (revoke vs hard delete)
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from v2hub_api.api.dependencies import (
    get_provider_authorization_service,
    get_provider_service,
    get_subscription_service,
    get_user_service,
)
from v2hub_api.api.endpoints.admin import provider_authorization as admin_auth_module
from v2hub_api.api.endpoints.admin.dependencies import verify_internal_ip, verify_request_signature
from v2hub_api.core.config import settings
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService
from v2hub_api.utils.auth_hmac import generate_auth_hmac

pytestmark = pytest.mark.asyncio


def _build_app(db_session) -> FastAPI:
    """
    Build a minimal app exposing only the admin auth router, with the
    two security dependencies stubbed out (they're covered exhaustively
    in test_admin_security.py) so tests can focus on business logic.
    """
    app = FastAPI()
    app.include_router(admin_auth_module.router, prefix="/api/v1/admin/providers")

    user_service = UserService(db_session)
    provider_service = ProviderService(db_session)
    authorization_service = ProviderAuthorizationService(db_session)
    subscription_service = SubscriptionService(db_session, cache_service=None)

    async def _noop() -> None:
        return None

    app.dependency_overrides[verify_request_signature] = _noop
    app.dependency_overrides[verify_internal_ip] = _noop
    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_provider_service] = lambda: provider_service
    app.dependency_overrides[get_provider_authorization_service] = lambda: authorization_service
    app.dependency_overrides[get_subscription_service] = lambda: subscription_service

    return app


async def _make_user(db_session, user_id: int):
    return await UserService(db_session).create_user(user_id=user_id)


async def _make_provider(db_session, owner_user_id: int, name: str):
    owner = await _make_user(db_session, owner_user_id)
    return await ProviderService(db_session).create_provider(
        owner_hash=owner.user_hash, provider_name=name
    )


class TestGetProviderAndAuthorizationStatus:
    async def test_returns_status_when_authorization_exists(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)
        auth_service = ProviderAuthorizationService(db_session)
        await auth_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/admin/providers/auth/vpn1/100")

        assert response.status_code == 200
        body = response.json()
        assert body["provider_name"] == "vpn1"
        assert body["user_id"] == 100
        assert body["status"] == "approved"

    async def test_returns_none_status_when_no_authorization(self, db_session):
        await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await _make_user(db_session, user_id=100)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/admin/providers/auth/vpn1/100")

        assert response.status_code == 200
        assert response.json()["status"] is None

    async def test_returns_404_for_unknown_provider(self, db_session):
        await _make_user(db_session, user_id=100)
        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/admin/providers/auth/does-not-exist/100")

        assert response.status_code == 404

    async def test_returns_404_for_unknown_user(self, db_session):
        await _make_provider(db_session, owner_user_id=1, name="vpn1")
        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/admin/providers/auth/vpn1/999")

        assert response.status_code == 404


class TestProcessProviderAuthorizationRequest:
    async def test_creates_pending_authorization_with_valid_hmac(self, db_session):
        """
        The canonical invite-link flow: a user with no account yet opens
        a `conn_{hmac}_{provider_name}` link, and this endpoint creates
        both the user and a PENDING authorization once the HMAC checks
        out.
        """
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        auth_hmac = generate_auth_hmac(555, provider.provider_hash, settings.auth_hmac_secret)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth",
            json={"user_id": 555, "provider_name": "vpn1", "hmac": auth_hmac},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == 555
        assert body["status"] == "pending"

        user_service = UserService(db_session)
        created_user = await user_service.get_by_user_id(555)
        assert created_user is not None

    async def test_rejects_invalid_hmac(self, db_session):
        await _make_provider(db_session, owner_user_id=1, name="vpn1")

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth",
            json={"user_id": 555, "provider_name": "vpn1", "hmac": "0" * 24},
        )

        assert response.status_code == 401

    async def test_unknown_provider_does_not_create_a_user(self, db_session):
        """
        Regression test: a request for a nonexistent provider must 404
        without creating a user row for the given user_id as a side
        effect. Previously the endpoint called `create_user` before
        checking whether the provider existed at all.
        """
        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth",
            json={"user_id": 777, "provider_name": "does-not-exist"},
        )

        assert response.status_code == 404

        user_service = UserService(db_session)
        assert await user_service.get_by_user_id(777) is None

    async def test_without_hmac_and_no_existing_authorization_returns_none_status(self, db_session):
        """
        If no hmac is supplied and there's no existing authorization row,
        the endpoint reports the user/provider pair but does not create
        an authorization (hmac is required to prove the invite link is
        legitimate).
        """
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth",
            json={"user_id": 555, "provider_name": "vpn1"},
        )

        assert response.status_code == 200
        assert response.json()["status"] is None

        auth_service = ProviderAuthorizationService(db_session)
        user_service = UserService(db_session)
        user = await user_service.get_by_user_id(555)
        authorization = await auth_service.get_authorization(provider.provider_hash, user.user_hash)
        assert authorization is None

    async def test_existing_authorization_is_returned_without_hmac(self, db_session):
        """When an authorization already exists, the endpoint should
        simply report it -- hmac verification is only needed to *create*
        a brand-new one."""
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=555)
        auth_service = ProviderAuthorizationService(db_session)
        await auth_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth",
            json={"user_id": 555, "provider_name": "vpn1"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "approved"


class TestApproveProviderConnection:
    async def test_approves_pending_authorization(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)
        auth_service = ProviderAuthorizationService(db_session)
        from v2hub_api.core.enums import ProviderAuthorizationStatus

        await auth_service.add_authorization(
            provider.provider_hash, user.user_hash, status=ProviderAuthorizationStatus.PENDING
        )

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/approve",
            json={"user_id": 100, "provider_name": "vpn1"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    async def test_returns_404_when_authorization_missing(self, db_session):
        await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await _make_user(db_session, user_id=100)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/approve",
            json={"user_id": 100, "provider_name": "vpn1"},
        )

        assert response.status_code == 404

    async def test_returns_404_for_unknown_provider(self, db_session):
        await _make_user(db_session, user_id=100)
        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/approve",
            json={"user_id": 100, "provider_name": "does-not-exist"},
        )

        assert response.status_code == 404

    async def test_already_approved_is_returned_unchanged(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)
        auth_service = ProviderAuthorizationService(db_session)
        await auth_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/approve",
            json={"user_id": 100, "provider_name": "vpn1"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    async def test_enforces_max_providers_per_user_quota(self, db_session, monkeypatch):
        """
        End-to-end check that the MAX_PROVIDERS_PER_USER quota
        introduced for issue #5 is actually enforced through the admin
        approval flow, not just at the service layer.
        """
        monkeypatch.setattr(settings, "max_providers_per_user", 1)

        user = await _make_user(db_session, user_id=100)
        auth_service = ProviderAuthorizationService(db_session)

        from v2hub_api.core.enums import ProviderAuthorizationStatus

        first_provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await auth_service.grant(first_provider.provider_hash, user.user_hash)

        second_provider = await _make_provider(db_session, owner_user_id=2, name="vpn2")
        await auth_service.add_authorization(
            second_provider.provider_hash,
            user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/approve",
            json={"user_id": 100, "provider_name": "vpn2"},
        )

        assert response.status_code == 422


class TestRejectProviderConnection:
    async def test_deletes_authorization_with_no_subscriptions(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)
        auth_service = ProviderAuthorizationService(db_session)
        from v2hub_api.core.enums import ProviderAuthorizationStatus

        await auth_service.add_authorization(
            provider.provider_hash, user.user_hash, status=ProviderAuthorizationStatus.PENDING
        )

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/reject",
            json={"user_id": 100, "provider_name": "vpn1"},
        )

        assert response.status_code == 200
        assert response.json()["status"] is None

        authorization = await auth_service.get_authorization(provider.provider_hash, user.user_hash)
        assert authorization is None

    async def test_revokes_instead_of_deleting_when_subscriptions_exist(self, db_session):
        """
        Rejecting a connection that already produced subscriptions must
        not hard-delete the authorization (which would orphan/cascade
        those subscriptions silently) -- it should revoke instead,
        keeping an audit trail.
        """
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)
        auth_service = ProviderAuthorizationService(db_session)
        await auth_service.grant(provider.provider_hash, user.user_hash)

        subscription_service = SubscriptionService(db_session, cache_service=None)
        await subscription_service.create_subscription(
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
            name="my-sub",
        )

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/reject",
            json={"user_id": 100, "provider_name": "vpn1"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "revoked"

        authorization = await auth_service.get_authorization(provider.provider_hash, user.user_hash)
        assert authorization is not None
        assert authorization.status.value == "revoked"

    async def test_returns_404_when_authorization_missing(self, db_session):
        await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await _make_user(db_session, user_id=100)

        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/reject",
            json={"user_id": 100, "provider_name": "vpn1"},
        )

        assert response.status_code == 404

    async def test_returns_404_for_unknown_provider(self, db_session):
        await _make_user(db_session, user_id=100)
        app = _build_app(db_session)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/admin/providers/auth/reject",
            json={"user_id": 100, "provider_name": "does-not-exist"},
        )

        assert response.status_code == 404
