"""
Tests for `v2hub_api.api.endpoints.me` (the `/me` self-service router,
added in #18):

- GET  /me                              -> current user info
- GET  /me/connections                  -> list of approved provider connections
- GET  /me/connections/{provider_name}  -> single provider connection status
- DELETE /me/connections/{provider_name} -> revoke a connection

These are exercised at the HTTP boundary (FastAPI TestClient) with the
`get_current_user` dependency overridden, following the same pattern as
`test_subscription_endpoint_regression.py`.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from v2hub_api.api.dependencies import get_current_user
from v2hub_api.api.endpoints import me as me_module
from v2hub_api.db.models import User
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


def _build_app(db_session, user: User) -> FastAPI:
    app = FastAPI()
    app.include_router(me_module.router, prefix="/api/v1")

    provider_service = ProviderService(db_session)
    authorization_service = ProviderAuthorizationService(db_session)

    async def _override_user():
        return user

    async def _override_provider_service():
        return provider_service

    async def _override_authorization_service():
        return authorization_service

    app.dependency_overrides[get_current_user] = _override_user

    from v2hub_api.api.dependencies import (
        get_provider_authorization_service,
        get_provider_service,
    )

    app.dependency_overrides[get_provider_service] = _override_provider_service
    app.dependency_overrides[get_provider_authorization_service] = _override_authorization_service

    return app


async def _make_user(db_session, user_id: int = 1) -> User:
    user_service = UserService(db_session)
    return await user_service.create_user(user_id=user_id)


class TestGetMe:
    async def test_returns_current_user_info(self, db_session):
        user = await _make_user(db_session, user_id=42)
        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me")

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == 42
        assert body["is_active"] is True
        # Internal identifiers must never be exposed via /me.
        assert "user_hash" not in body
        assert "api_token" not in body

    async def test_reflects_inactive_status(self, db_session):
        user = await _make_user(db_session, user_id=1)
        user_service = UserService(db_session)
        user = await user_service.set_active(user_id=1, is_active=False)

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me")

        assert response.status_code == 200
        assert response.json()["is_active"] is False


class TestGetConnections:
    async def test_returns_empty_list_when_no_connections(self, db_session):
        user = await _make_user(db_session)
        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200
        assert response.json() == {"connections": []}

    async def test_returns_only_approved_connections(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        approved = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="approved-prov"
        )
        pending_owner = await _make_user(db_session, user_id=3)
        pending = await provider_service.create_provider(
            owner_hash=pending_owner.user_hash, provider_name="pending-prov"
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=approved.provider_hash, user_hash=user.user_hash
        )
        # Create then immediately revoke -> should NOT show up in /me/connections.
        await authorization_service.grant(
            provider_hash=pending.provider_hash, user_hash=user.user_hash
        )
        await authorization_service.revoke(
            provider_hash=pending.provider_hash, user_hash=user.user_hash
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200
        connections = response.json()["connections"]
        assert len(connections) == 1
        assert connections[0]["provider_name"] == "approved-prov"
        assert connections[0]["is_authorized"] is True


class TestGetConnection:
    async def test_returns_authorized_true_when_connected(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )
        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash, user_hash=user.user_hash
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/vpn123")

        assert response.status_code == 200
        body = response.json()
        assert body["provider_name"] == "vpn123"
        assert body["is_authorized"] is True

    async def test_returns_authorized_false_when_not_connected(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        await provider_service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/vpn123")

        assert response.status_code == 200
        body = response.json()
        assert body["is_authorized"] is False

    async def test_returns_404_for_unknown_provider(self, db_session):
        user = await _make_user(db_session)
        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/does-not-exist")

        assert response.status_code == 404


class TestRevokeConnection:
    async def test_revokes_existing_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )
        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash, user_hash=user.user_hash
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/me/connections/vpn123")
        assert response.status_code == 204

        # Connection should no longer be reported as authorized.
        follow_up = client.get("/api/v1/me/connections/vpn123")
        assert follow_up.json()["is_authorized"] is False

    async def test_returns_404_for_unknown_provider(self, db_session):
        user = await _make_user(db_session)
        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/me/connections/does-not-exist")

        assert response.status_code == 404

    async def test_returns_404_when_never_authorized(self, db_session):
        """Revoking a provider the user never connected to should 404,
        not silently succeed (ProviderAuthorizationService.revoke raises
        NotFoundError when no authorization record exists)."""
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        await provider_service.create_provider(owner_hash=owner.user_hash, provider_name="vpn123")

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/me/connections/vpn123")

        assert response.status_code == 404
