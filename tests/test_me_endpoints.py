"""
Tests for `v2hub_api.api.endpoints.me` (the `/me` self-service router,
added in #18):

- GET  /me                              -> current user info
- GET  /me/connections                  -> list of approved and pending provider connections
- GET  /me/connections/{provider_name}  -> single provider connection status
- POST /me/connections/{provider_name}/approve -> approve pending connection
- POST /me/connections/{provider_name}/reject  -> reject pending connection
- DELETE /me/connections/{provider_name} -> revoke a connection

These are exercised at the HTTP boundary (FastAPI TestClient) with the
`get_current_user` dependency overridden, following the same pattern as
`test_subscription_endpoint_regression.py`.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from v2hub_api.api.dependencies import (
    get_current_user,
    get_provider_authorization_service,
    get_provider_service,
    get_subscription_service,
)
from v2hub_api.api.endpoints import me as me_module
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.db.models import User
from v2hub_api.services.provider_authorization_service import ProviderAuthorizationService
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


def _build_app(db_session, user: User) -> FastAPI:
    app = FastAPI()
    app.include_router(me_module.router, prefix="/api/v1")

    provider_service = ProviderService(db_session)
    authorization_service = ProviderAuthorizationService(db_session)
    subscription_service = SubscriptionService(db_session, cache_service=None)

    async def _override_user():
        return user

    async def _override_provider_service():
        return provider_service

    async def _override_authorization_service():
        return authorization_service

    async def _override_subscription_service():
        return subscription_service

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_provider_service] = _override_provider_service
    app.dependency_overrides[get_provider_authorization_service] = _override_authorization_service
    app.dependency_overrides[get_subscription_service] = _override_subscription_service

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

    async def test_returns_approved_and_pending_connections_but_not_revoked(
        self,
        db_session,
    ):
        user = await _make_user(db_session, user_id=1)

        approved_owner = await _make_user(db_session, user_id=2)
        pending_owner = await _make_user(db_session, user_id=3)
        revoked_owner = await _make_user(db_session, user_id=4)

        provider_service = ProviderService(db_session)

        approved = await provider_service.create_provider(
            owner_hash=approved_owner.user_hash,
            provider_name="approved-prov",
        )
        pending = await provider_service.create_provider(
            owner_hash=pending_owner.user_hash,
            provider_name="pending-prov",
        )
        revoked = await provider_service.create_provider(
            owner_hash=revoked_owner.user_hash,
            provider_name="revoked-prov",
        )

        authorization_service = ProviderAuthorizationService(db_session)

        await authorization_service.grant(
            provider_hash=approved.provider_hash,
            user_hash=user.user_hash,
        )

        await authorization_service.add_authorization(
            provider_hash=pending.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        await authorization_service.grant(
            provider_hash=revoked.provider_hash,
            user_hash=user.user_hash,
        )
        await authorization_service.revoke(
            provider_hash=revoked.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200

        connections = response.json()["connections"]
        assert len(connections) == 2

        by_name = {connection["provider_name"]: connection for connection in connections}

        assert by_name["approved-prov"]["status"] == "approved"
        assert by_name["approved-prov"]["is_authorized"] is True

        assert by_name["pending-prov"]["status"] == "pending"
        assert by_name["pending-prov"]["is_authorized"] is False

        assert "revoked-prov" not in by_name

    async def test_returns_provider_information_for_pending_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200

        connection = response.json()["connections"][0]
        assert connection["provider_name"] == provider.provider_name
        assert connection["provider_url"] == provider.provider_url
        assert connection["status"] == "pending"
        assert connection["is_authorized"] is False


class TestGetConnection:
    async def test_returns_authorized_true_when_connected(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/vpn123")

        assert response.status_code == 200

        body = response.json()
        assert body["provider_name"] == "vpn123"
        assert body["status"] == "approved"
        assert body["is_authorized"] is True

    async def test_returns_authorized_false_when_not_connected(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/vpn123")

        assert response.status_code == 200

        body = response.json()
        assert body["is_authorized"] is False
        assert body["status"] is None

    async def test_returns_pending_status_when_connection_is_pending(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/vpn123")

        assert response.status_code == 200

        body = response.json()
        assert body["provider_name"] == "vpn123"
        assert body["status"] == "pending"
        assert body["is_authorized"] is False

    async def test_returns_revoked_status_when_connection_is_revoked(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        await authorization_service.revoke(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/vpn123")

        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "revoked"
        assert body["is_authorized"] is False

    async def test_returns_404_for_unknown_provider(self, db_session):
        user = await _make_user(db_session)
        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/me/connections/does-not-exist")

        assert response.status_code == 404


class TestApproveConnection:
    async def test_approves_pending_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/approve")

        assert response.status_code == 200

        body = response.json()
        assert body["provider_name"] == "vpn123"
        assert body["status"] == "approved"
        assert body["is_authorized"] is True

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is not None
        assert authorization.status == ProviderAuthorizationStatus.APPROVED

    async def test_approve_is_idempotent_for_already_approved_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/approve")

        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "approved"
        assert body["is_authorized"] is True

        current = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert current is not None
        assert current.status == ProviderAuthorizationStatus.APPROVED

    async def test_approve_rejects_revoked_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        await authorization_service.revoke(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/approve")

        assert response.status_code == 409

        body = response.json()
        assert body["detail"]["error"] == "invalid_authorization_status"
        assert body["detail"]["details"]["status"] == "revoked"

    async def test_approve_returns_422_when_provider_quota_reached(
        self,
        db_session,
        monkeypatch,
    ):
        """
        Regression coverage: MAX_PROVIDERS_PER_USER is enforced through
        this user-facing endpoint too, not just the admin /approve
        endpoint (see test_admin_provider_authorization_endpoints.py for
        that side). grant() raises TooManyProvidersError, which must
        surface as 422 here.
        """
        from v2hub_api.core.config import settings

        monkeypatch.setattr(settings, "max_providers_per_user", 1)

        user = await _make_user(db_session, user_id=1)
        owner_1 = await _make_user(db_session, user_id=2)
        owner_2 = await _make_user(db_session, user_id=3)

        provider_service = ProviderService(db_session)
        first_provider = await provider_service.create_provider(
            owner_hash=owner_1.user_hash,
            provider_name="vpn111",
        )
        second_provider = await provider_service.create_provider(
            owner_hash=owner_2.user_hash,
            provider_name="vpn222",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=first_provider.provider_hash,
            user_hash=user.user_hash,
        )
        await authorization_service.add_authorization(
            provider_hash=second_provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn222/approve")

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "too_many_providers"

        current = await authorization_service.get_authorization(
            provider_hash=second_provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert current is not None
        assert current.status == ProviderAuthorizationStatus.PENDING

    async def test_approve_returns_404_when_authorization_missing(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/approve")

        assert response.status_code == 404

    async def test_approve_returns_404_for_unknown_provider(self, db_session):
        user = await _make_user(db_session)

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/does-not-exist/approve")

        assert response.status_code == 404

    async def test_approved_connection_appears_in_connection_list(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/approve")

        assert response.status_code == 200

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200

        connections = response.json()["connections"]
        assert len(connections) == 1
        assert connections[0]["provider_name"] == "vpn123"
        assert connections[0]["status"] == "approved"
        assert connections[0]["is_authorized"] is True


class TestRejectConnection:
    async def test_rejects_pending_connection_without_subscriptions(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/reject")

        assert response.status_code == 200

        body = response.json()
        assert body["provider_name"] == "vpn123"
        assert body["status"] is None
        assert body["is_authorized"] is False

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is None

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200
        assert response.json() == {"connections": []}

    async def test_reject_preserves_authorization_when_subscriptions_exist(
        self,
        db_session,
    ):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        subscription_service = SubscriptionService(db_session, cache_service=None)
        await subscription_service.create_subscription(
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
            name="existing-subscription",
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/reject")

        assert response.status_code == 200

        body = response.json()
        assert body["provider_name"] == "vpn123"
        assert body["status"] == "revoked"
        assert body["is_authorized"] is False

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is not None
        assert authorization.status == ProviderAuthorizationStatus.REVOKED

        subscriptions = await subscription_service.list_subscriptions(
            user_hash=user.user_hash,
            provider_hash=provider.provider_hash,
        )
        assert subscriptions

        response = client.get("/api/v1/me/connections")

        assert response.status_code == 200
        assert response.json() == {"connections": []}

    async def test_reject_rejects_approved_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/reject")

        assert response.status_code == 409

        body = response.json()
        assert body["detail"]["error"] == "invalid_authorization_status"
        assert body["detail"]["details"]["status"] == "approved"

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is not None
        assert authorization.status == ProviderAuthorizationStatus.APPROVED

    async def test_reject_rejects_revoked_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        await authorization_service.revoke(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/reject")

        assert response.status_code == 409

        body = response.json()
        assert body["detail"]["error"] == "invalid_authorization_status"
        assert body["detail"]["details"]["status"] == "revoked"

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is not None
        assert authorization.status == ProviderAuthorizationStatus.REVOKED

    async def test_reject_returns_404_when_authorization_missing(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/vpn123/reject")

        assert response.status_code == 404

    async def test_reject_returns_404_for_unknown_provider(self, db_session):
        user = await _make_user(db_session)

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/me/connections/does-not-exist/reject")

        assert response.status_code == 404


class TestRevokeConnection:
    async def test_revokes_existing_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.grant(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/me/connections/vpn123")

        assert response.status_code == 204

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is not None
        assert authorization.status == ProviderAuthorizationStatus.REVOKED

        follow_up = client.get("/api/v1/me/connections/vpn123")

        assert follow_up.status_code == 200
        assert follow_up.json()["status"] == "revoked"
        assert follow_up.json()["is_authorized"] is False

    async def test_revoke_pending_connection(self, db_session):
        user = await _make_user(db_session, user_id=1)
        owner = await _make_user(db_session, user_id=2)

        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        authorization_service = ProviderAuthorizationService(db_session)
        await authorization_service.add_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
            status=ProviderAuthorizationStatus.PENDING,
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/me/connections/vpn123")

        assert response.status_code == 204

        authorization = await authorization_service.get_authorization(
            provider_hash=provider.provider_hash,
            user_hash=user.user_hash,
        )
        assert authorization is not None
        assert authorization.status == ProviderAuthorizationStatus.REVOKED

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
        await provider_service.create_provider(
            owner_hash=owner.user_hash,
            provider_name="vpn123",
        )

        app = _build_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/api/v1/me/connections/vpn123")

        assert response.status_code == 404
