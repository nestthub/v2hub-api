"""
Regression tests for the GET /{token} endpoint crash introduced by the
"provider subscriptions visibility" change.

`SubscriptionService.get_subscription()` was narrowed to
`(*, token, user_hash)` (provider_hash removed), but
`api/endpoints/subscriptions.py::get_subscription` (used by BOTH the
self-service router and the provider router, since they're built from the
same `build_subscriptions_router` factory) still calls it with
`provider_hash=_provider_hash(actor)`.

That mismatch means `GET /subscriptions/{token}` and
`GET /providers/{user_id}/subscriptions/{token}` crash with a TypeError
for every request, self-service or provider -- this is the single most
user-facing regression in the diff.

These tests build a minimal FastAPI app around just
`subscriptions.user_router` / `subscriptions.provider_router`, with the
actor dependency overridden directly (bypassing token auth, Redis, etc.),
and drive it through Starlette's TestClient so the bug is caught exactly
where a real client would hit it -- at the HTTP boundary -- not just at
the service layer.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from v2hub_api.api.dependencies import ResolverServiceDep, SubscriptionServiceDep, get_actor
from v2hub_api.api.endpoints import subscriptions
from v2hub_api.db.models import User
from v2hub_api.services.subscription_service import SubscriptionService
from v2hub_api.services.user_service import UserService

pytestmark = pytest.mark.asyncio


def _build_test_app(db_session, user: User) -> FastAPI:
    """
    Minimal app exposing only the subscriptions routers, with the actor
    dependency overridden to always act as `user` (self-service) and the
    resolver mocked out (config counting is irrelevant to this bug).
    """
    app = FastAPI()
    app.include_router(subscriptions.user_router, prefix="/api/v1")
    app.include_router(subscriptions.provider_router, prefix="/api/v1")

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
    app.dependency_overrides[SubscriptionServiceDep.__metadata__[0].dependency] = _override_service
    app.dependency_overrides[ResolverServiceDep.__metadata__[0].dependency] = _override_resolver

    return app


class TestGetSubscriptionEndpointRegression:
    async def test_get_single_subscription_does_not_500(self, db_session):
        """
        GET /subscriptions/{token} must succeed for a subscription the
        user actually owns.

        Before the fix, this raises TypeError inside the endpoint because
        it calls SubscriptionService.get_subscription(..., provider_hash=...)
        against a signature that no longer accepts provider_hash --
        FastAPI turns that into a 500 for every caller.
        """
        user_service = UserService(db_session)
        user = await user_service.create_user(user_id=1)

        sub_service = SubscriptionService(db_session)
        subscription = await sub_service.create_subscription(user_hash=user.user_hash, name="Mine")

        app = _build_test_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(f"/api/v1/subscriptions/{subscription.token}")

        assert response.status_code == 200, (
            f"expected 200, got {response.status_code}: {response.text}"
        )
        assert response.json()["token"] == subscription.token

    async def test_get_single_subscription_returns_404_for_missing_token(self, db_session):
        """
        Sanity check that the route itself is reachable end-to-end and
        correctly maps SubscriptionNotFoundError -- not just checking
        we don't 500 on the happy path.
        """
        user_service = UserService(db_session)
        user = await user_service.create_user(user_id=1)

        app = _build_test_app(db_session, user)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/subscriptions/does-not-exist")

        assert response.status_code == 404, (
            f"expected 404, got {response.status_code}: {response.text}"
        )
