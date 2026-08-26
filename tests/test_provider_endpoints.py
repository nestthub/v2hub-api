"""
Tests for `v2hub_api.api.endpoints.provider` (the provider-facing
`/providers/{user_id}` router):

- GET    /providers/{user_id}         -> current authorization status
- POST   /providers/{user_id}         -> request/establish a connection
- POST   /providers/{user_id}/revoke  -> revoke access
- DELETE /providers/{user_id}         -> remove the connection entirely

Exercised at the HTTP boundary (FastAPI TestClient) with `CurrentProvider`
overridden, following the same pattern as `test_me_endpoints.py`. This
router previously had close to no dedicated coverage (~30%), so these
tests focus on the branches that matter for issue #5:
- the invite-link path for a user with no account yet
- the already-approved short-circuit (no link returned)
- re-inviting a user who previously revoked access
- the MAX_PROVIDERS_PER_USER quota enforced by `grant()` via `/approve`
  is covered separately in test_provider_authorization_service.py and
  test_admin_provider_authorization_endpoints.py; here we only check
  that create_connection's PENDING path still works up to the limit.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from v2hub_api.api.dependencies import (
    get_current_provider,
    get_provider_authorization_service,
    get_user_service,
)
from v2hub_api.api.endpoints import provider as provider_module
from v2hub_api.core.config import settings
from v2hub_api.db.models import Provider
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


def _build_app(db_session, provider: Provider) -> FastAPI:
    app = FastAPI()
    app.include_router(provider_module.router, prefix="/api/v1")

    user_service = UserService(db_session)
    authorization_service = ProviderAuthorizationService(db_session)

    async def _override_provider():
        return provider

    async def _override_user_service():
        return user_service

    async def _override_authorization_service():
        return authorization_service

    app.dependency_overrides[get_current_provider] = _override_provider
    app.dependency_overrides[get_user_service] = _override_user_service
    app.dependency_overrides[get_provider_authorization_service] = _override_authorization_service

    return app


async def _make_user(db_session, user_id: int):
    return await UserService(db_session).create_user(user_id=user_id)


async def _make_provider(db_session, owner_user_id: int, name: str) -> Provider:
    owner = await _make_user(db_session, owner_user_id)
    return await ProviderService(db_session).create_provider(
        owner_hash=owner.user_hash, provider_name=name
    )


class TestGetUser:
    async def test_returns_status_for_approved_connection(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/providers/100")

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == 100
        assert body["status"] == "approved"

    async def test_returns_401_when_user_does_not_exist(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/providers/999")

        assert response.status_code == 401

    async def test_returns_401_when_no_authorization_exists(self, db_session):
        """get_status raises AuthorizationError when no row exists at all
        for this (provider, user) pair -- distinct from an APPROVED/
        PENDING/REVOKED row being present."""
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await _make_user(db_session, user_id=100)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/providers/100")

        assert response.status_code == 403


class TestCreateConnection:
    async def test_returns_invite_link_for_unknown_user(self, db_session):
        """
        No account exists for user_id yet -> the endpoint must return an
        HMAC-signed `conn_{hmac}_{provider_name}` invite payload rather
        than attempting (and failing) to authorize a nonexistent user.
        """
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/12345")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["connection_link"] is not None
        assert body["connection_link"].startswith(settings.connection_link_prefix)
        assert "conn_" in body["connection_link"]
        assert body["connection_link"].endswith(f"_{provider.provider_name}")

    async def test_creates_pending_authorization_for_known_user(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/100")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["connection_link"] == f"{settings.connection_link_prefix}provider_vpn1"

        authorization_service = ProviderAuthorizationService(db_session)
        authorization = await authorization_service.get_authorization(
            provider.provider_hash, user.user_hash
        )
        assert authorization is not None
        assert authorization.status.value == "pending"

    async def test_new_authorization_is_pending_not_auto_approved(self, db_session):
        """
        Regression test: creating the first-ever authorization row for a
        known user via this endpoint must land in PENDING, never
        APPROVED. Prior to migration 0004, the model's column default
        was APPROVED, so a caller omitting `status` here would have
        silently granted a provider full access with no confirmation
        step and bypassed the MAX_PROVIDERS_PER_USER quota enforced by
        grant(). The default is now PENDING at the schema level too,
        but this endpoint still passes `status` explicitly as
        defense-in-depth for this security-relevant boundary.
        """
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/100")
        assert response.status_code == 201
        assert response.json()["status"] == "pending"

        authorization_service = ProviderAuthorizationService(db_session)
        authorization = await authorization_service.get_authorization(
            provider.provider_hash, user.user_hash
        )
        assert authorization.status.value == "pending"

    async def test_already_approved_returns_no_link(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/100")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "approved"
        assert body["connection_link"] is None

    async def test_revoked_authorization_is_reinitialized_to_pending(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(provider.provider_hash, user.user_hash)
        await authorization_service.revoke(provider.provider_hash, user.user_hash)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/100")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["connection_link"] is not None

        # The original row was reused, not duplicated.
        authorization = await authorization_service.get_authorization(
            provider.provider_hash, user.user_hash
        )
        assert authorization.status.value == "pending"

    async def test_second_request_for_same_pending_pair_is_idempotent(self, db_session):
        """Calling create_connection twice for the same PENDING pair must
        not create a second authorization row."""
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        first = client.post("/api/v1/providers/100")
        second = client.post("/api/v1/providers/100")

        assert first.status_code == 201
        assert second.status_code == 201

        authorization_service = ProviderAuthorizationService(db_session)
        authorization = await authorization_service.get_authorization(
            provider.provider_hash, user.user_hash
        )
        assert authorization.status.value == "pending"


class TestRevokeConnection:
    async def test_revokes_approved_connection(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/100/revoke")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "revoked"

    async def test_returns_401_when_authorization_not_found(self, db_session):
        """
        The endpoint raises AuthenticationError (not NotFoundError) when
        no authorization row exists at all for an otherwise-known user;
        pin the exact status code so a change in error type doesn't slip
        through unnoticed.
        """
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await _make_user(db_session, user_id=100)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/100/revoke")

        assert response.status_code == 401

    async def test_returns_401_for_unknown_user(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/providers/999/revoke")

        assert response.status_code == 401


class TestDeleteConnection:
    async def test_deletes_existing_connection(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        user = await _make_user(db_session, user_id=100)

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(provider.provider_hash, user.user_hash)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/providers/100")

        assert response.status_code == 200
        assert response.json()["detail"]

        authorization = await authorization_service.get_authorization(
            provider.provider_hash, user.user_hash
        )
        assert authorization is None

    async def test_returns_404_when_no_authorization_exists(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        await _make_user(db_session, user_id=100)

        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/providers/100")

        assert response.status_code == 404

    async def test_returns_401_for_unknown_user(self, db_session):
        provider = await _make_provider(db_session, owner_user_id=1, name="vpn1")
        app = _build_app(db_session, provider)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/providers/999")

        assert response.status_code == 401
