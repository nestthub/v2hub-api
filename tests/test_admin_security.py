"""
Tests for `v2hub_api.api.endpoints.admin.dependencies`:

- `verify_request_signature`: HMAC-SHA256 admin request signing, including
  the query-string fix from 57c7cb3 (signature payload must include
  `?query=string` or the signature can be replayed against a different
  query without invalidating it).
- `verify_internal_ip`: IP allowlist enforcement for admin endpoints.

These dependencies gate *every* admin endpoint but had no dedicated tests,
so regressions here (e.g. reverting the query-string fix, or a broken
timestamp window) would silently reopen an admin auth bypass.
"""

import hashlib
import hmac
import time

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from v2hub_api.api.endpoints.admin.dependencies import (
    verify_internal_ip,
    verify_request_signature,
)
from v2hub_api.core.config import settings

pytestmark = pytest.mark.asyncio


def _sign(method: str, path: str, body: bytes, timestamp: str, secret: str | None = None) -> str:
    """Build a valid HMAC-SHA256 signature the same way the dependency does."""
    secret = secret if secret is not None else settings.admin_secret_key
    payload = f"{timestamp}{method}{path}{body.decode('utf-8')}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _now_ms() -> str:
    return str(int(time.time() * 1000))


def _build_signature_app() -> FastAPI:
    """Minimal app with a single route protected only by verify_request_signature."""
    from fastapi import Depends

    app = FastAPI()

    @app.post("/protected2")
    async def protected2(_signature: None = Depends(verify_request_signature)) -> dict:
        return {"ok": True}

    return app


class TestVerifyRequestSignature:
    async def test_accepts_valid_signature(self):
        app = _build_signature_app()
        client = TestClient(app, raise_server_exceptions=False)

        ts = _now_ms()
        sig = _sign("POST", "/protected2", b"", ts)

        response = client.post(
            "/protected2",
            headers={"X-Signature": sig, "X-Timestamp": ts},
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_rejects_missing_signature_headers(self):
        app = _build_signature_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/protected2")

        assert response.status_code == 401
        assert "Missing signature headers" in response.json()["detail"]

    async def test_rejects_invalid_signature(self):
        app = _build_signature_app()
        client = TestClient(app, raise_server_exceptions=False)

        ts = _now_ms()

        response = client.post(
            "/protected2",
            headers={"X-Signature": "deadbeef" * 8, "X-Timestamp": ts},
        )

        assert response.status_code == 401
        assert "Invalid request signature" in response.json()["detail"]

    async def test_rejects_stale_timestamp(self):
        app = _build_signature_app()
        client = TestClient(app, raise_server_exceptions=False)

        # 2 minutes old -> outside the 60s replay window
        stale_ts = str(int(time.time() * 1000) - 120_000)
        sig = _sign("POST", "/protected2", b"", stale_ts)

        response = client.post(
            "/protected2",
            headers={"X-Signature": sig, "X-Timestamp": stale_ts},
        )

        assert response.status_code == 401
        assert "too old or in future" in response.json()["detail"]

    async def test_rejects_non_numeric_timestamp(self):
        app = _build_signature_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/protected2",
            headers={"X-Signature": "abc123", "X-Timestamp": "not-a-number"},
        )

        assert response.status_code == 401
        assert "Invalid timestamp format" in response.json()["detail"]

    async def test_signature_covers_request_body(self):
        """
        A signature computed for one body must not validate a request with
        a different body -- otherwise an attacker who observes one signed
        request could replay it with arbitrary tampered content.
        """
        app = FastAPI()

        from fastapi import Depends

        @app.post("/echo")
        async def echo(_signature: None = Depends(verify_request_signature)) -> dict:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)

        ts = _now_ms()
        sig = _sign("POST", "/echo", b'{"amount": 1}', ts)

        response = client.post(
            "/echo",
            content=b'{"amount": 999}',
            headers={
                "X-Signature": sig,
                "X-Timestamp": ts,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401

    async def test_signature_covers_query_string(self):
        """
        Regression test for 57c7cb3 ("fix: include query string in admin
        request signature validation").

        A signature computed for a request with no query string must NOT
        validate the same request with a query string appended -- otherwise
        an attacker could take a legitimately signed request and replay it
        against a different resource by tacking on query parameters (e.g.
        redirecting a signed POST toward a different target via a filter
        param the endpoint trusts).
        """
        app = FastAPI()

        from fastapi import Depends

        @app.post("/query-target")
        async def query_target(_signature: None = Depends(verify_request_signature)) -> dict:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)

        ts = _now_ms()
        # Signature computed WITHOUT any query string.
        sig = _sign("POST", "/query-target", b"", ts)

        response = client.post(
            "/query-target?user_id=999",
            headers={"X-Signature": sig, "X-Timestamp": ts},
        )

        assert response.status_code == 401

    async def test_signature_with_matching_query_string_is_accepted(self):
        """Complementary case: signing WITH the query string must succeed."""
        app = FastAPI()

        from fastapi import Depends

        @app.post("/query-target")
        async def query_target(_signature: None = Depends(verify_request_signature)) -> dict:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)

        ts = _now_ms()
        sig = _sign("POST", "/query-target?user_id=999", b"", ts)

        response = client.post(
            "/query-target?user_id=999",
            headers={"X-Signature": sig, "X-Timestamp": ts},
        )

        assert response.status_code == 200


class TestVerifyInternalIp:
    async def test_allows_whitelisted_ip(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_allowed_ips", ["203.0.113.5"])
        app = FastAPI()

        from fastapi import Depends

        @app.get("/ip-protected")
        async def ip_protected(_ip: None = Depends(verify_internal_ip)) -> dict:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        # get_client_ip() prefers X-Real-IP over the raw connection address,
        # so we simulate the nginx-forwarded client IP explicitly.
        response = client.get("/ip-protected", headers={"X-Real-IP": "203.0.113.5"})

        assert response.status_code == 200

    async def test_rejects_non_whitelisted_ip(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_allowed_ips", ["10.0.0.1"])
        app = FastAPI()

        from fastapi import Depends

        @app.get("/ip-protected")
        async def ip_protected(_ip: None = Depends(verify_internal_ip)) -> dict:
            return {"ok": True}

        # TestClient's default client host is 'testclient', which get_client_ip
        # will not find in the allowlist regardless -- this asserts the deny path.
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/ip-protected")

        assert response.status_code == 403

    async def test_rejects_when_no_ips_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_allowed_ips", [])
        app = FastAPI()

        from fastapi import Depends

        @app.get("/ip-protected")
        async def ip_protected(_ip: None = Depends(verify_internal_ip)) -> dict:
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/ip-protected")

        assert response.status_code == 403
        assert "not configured" in response.json()["detail"]


class TestVerifyRequestSignatureUnitLevel:
    """
    Direct coroutine-level checks (no HTTP layer) for edge cases that are
    awkward to trigger through TestClient/Starlette routing.
    """

    async def test_raises_http_exception_type_directly(self):
        class _FakeURL:
            path = "/x"
            query = ""

        class _FakeRequest:
            method = "GET"
            url = _FakeURL()
            headers = {}
            client = None

            async def body(self) -> bytes:
                return b""

        with pytest.raises(HTTPException) as exc_info:
            await verify_request_signature(_FakeRequest(), x_signature=None, x_timestamp=None)

        assert exc_info.value.status_code == 401
