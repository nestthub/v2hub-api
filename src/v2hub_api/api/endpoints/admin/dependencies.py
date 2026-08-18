"""
Security dependencies for admin API endpoints.

Provides:
- HMAC-SHA256 request signature verification
- Request timestamp validation to prevent replay attacks
- Internal IP address verification

All admin endpoints use these dependencies to enforce authenticated
and trusted internal access.
"""

import hashlib
import hmac
import logging
import time

from fastapi import Depends, Header, HTTPException, Request, status

from v2hub_api.core.config import settings
from v2hub_api.middlewares.rate_limit_middleware import get_client_ip

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Security Dependencies
# ═══════════════════════════════════════════════════════════════════════════


async def verify_request_signature(
    request: Request,
    x_signature: str | None = Header(None),
    x_timestamp: str | None = Header(None),
) -> None:
    """
    Verify request signature for admin endpoints.

    Uses HMAC-SHA256 for request signing:
    - Signature = HMAC-SHA256(secret_key, timestamp + method + path + body)

    Headers required:
    - X-Signature: HMAC signature
    - X-Timestamp: Unix timestamp in milliseconds

    Raises:
        HTTPException: If signature is invalid or missing
    """
    # Check if signature headers are present
    if not x_signature or not x_timestamp:
        logger.warning(
            "Admin endpoint accessed without signature from IP %s", get_client_ip(request)
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature headers (X-Signature, X-Timestamp required)",
        ) from None

    # Validate timestamp (prevent replay attacks)
    try:
        request_time = int(x_timestamp)
        current_time = int(time.time() * 1000)
        time_diff = abs(current_time - request_time)

        # Allow 1 minute window
        if time_diff > 60000:  # 1 minute in milliseconds
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp too old or in future",
            ) from None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid timestamp format"
        ) from None

    # Get request body
    body = await request.body()

    # Create signature payload
    method = request.method
    path = str(request.url.path)

    if request.url.query:
        path = f"{path}?{request.url.query}"

    payload = f"{x_timestamp}{method}{path}{body.decode('utf-8')}"

    # Calculate expected signature
    expected_signature = hmac.new(
        settings.admin_secret_key.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    # Compare signatures (constant-time comparison)
    if not hmac.compare_digest(x_signature, expected_signature):
        logger.warning(
            "Invalid admin signature from IP %s for %s %s", get_client_ip(request), method, path
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid request signature"
        ) from None

    logger.info(
        "Admin request authenticated from IP %s for %s %s", get_client_ip(request), method, path
    )


async def verify_internal_ip(request: Request) -> None:
    """
    Verify that request comes from allowed internal IP.

    Checks request IP against ADMIN_ALLOWED_IPS from environment.

    Raises:
        HTTPException: If IP is not in allowed list
    """
    client_ip = get_client_ip(request)

    if not settings.admin_allowed_ips:
        logger.error("No admin allowed IPs configured!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access not configured"
        ) from None

    if client_ip not in settings.admin_allowed_ips:
        logger.warning("Admin endpoint accessed from unauthorized IP: %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Access denied for IP: {client_ip}"
        ) from None


# Combine both security checks
AdminSecurityDep = Depends(verify_request_signature)
InternalIPDep = Depends(verify_internal_ip)
