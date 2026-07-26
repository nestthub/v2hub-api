"""
Admin API endpoints for internal configuration management.

Provides secure endpoints for:
- User creation and management
- Token regeneration
- IP ban/unban management
- Whitelist IP management
- Configuration updates

All endpoints require request signature verification.
"""

import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from v2hub_api.api.dependencies import UserServiceDep
from v2hub_api.core.config import settings
from v2hub_api.core.exceptions import to_http_exception
from v2hub_api.middlewares.rate_limit_middleware import get_client_ip
from v2hub_api.schemas import (
    IPBanEntry,
    IPBanListResponse,
    IPBanRequest,
    IPBanStatusResponse,
    IPUnbanRequest,
    IPUnbanResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserResponse,
    UserStatusUpdateRequest,
    WhitelistAddRequest,
    WhitelistAddResponse,
    WhitelistEntry,
    WhitelistListResponse,
    WhitelistRemoveRequest,
    WhitelistRemoveResponse,
)
from v2hub_api.services.ban_service import get_ban_service
from v2hub_api.services.whitelist_service import get_whitelist_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"], include_in_schema=False)

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


# ═══════════════════════════════════════════════════════════════════════════
# User Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/users",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new user",
    description="Create a new user account with generated API token",
)
async def create_user(
    request: UserCreateRequest,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> UserCreateResponse:
    """
    Create a new user account.

    Generates:
    - user_hash from user_id
    - unique API token

    Returns user credentials.
    """
    try:
        user = await user_service.create_user(user_id=request.user_id)

        logger.info("User created: user_id=%d, user_hash=%s", user.user_id, user.user_hash)

        return UserCreateResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise to_http_exception(e) from e


@router.get(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=UserResponse,
    summary="Get user info",
    description="Get user id, hash and api-token",
)
async def get_user(
    user_id: int,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> UserResponse:
    """
    Get user account info.

    Returns user credentials.
    """
    try:
        user = await user_service.get_user(user_id)

        return UserResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to return user: {e}")
        raise to_http_exception(e) from e


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description="Delete a user account",
)
async def delete_user(
    user_id: int,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> None:
    """
    Delete a user account.
    """
    try:
        await user_service.delete_user(user_id=user_id)

    except Exception as e:
        logger.error(f"Failed to delete user: {e}")
        raise to_http_exception(e) from e


@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user active status",
    description="Enable or disable user account",
)
async def update_user_status(
    user_id: int,
    request: UserStatusUpdateRequest,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> UserResponse:
    """
    Update user active status.

    Args:
        user_id: User ID
        is_active: True to activate, False to deactivate

    Returns:
        Updated user data
    """
    try:
        user = await user_service.set_active(
            user_id=user_id,
            is_active=request.is_active,
        )

        logger.info(
            "User status updated: user_id=%d, is_active=%s",
            user.user_id,
            user.is_active,
        )

        return UserResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
        )

    except Exception as e:
        logger.error(f"Failed to update user status: {e}")
        raise to_http_exception(e) from e


@router.post(
    "/users/refresh-token",
    response_model=TokenRefreshResponse,
    summary="Refresh user API token",
    description="Generate new API token for existing user",
)
async def refresh_user_token(
    request: TokenRefreshRequest,
    user_service: UserServiceDep,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> TokenRefreshResponse:
    """
    Refresh user's API token.

    Generates new unique token and invalidates the old one.
    """
    try:
        new_token = await user_service.refresh_token(user_id=request.user_id)

        logger.info("Token refreshed for user_id=%d", request.user_id)

        return TokenRefreshResponse(
            user_id=request.user_id,
            new_api_token=new_token,
        )

    except Exception as e:
        logger.error(f"Failed to refresh token: {e}")
        raise to_http_exception(e) from e


# ═══════════════════════════════════════════════════════════════════════════
# IP Ban Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/bans",
    response_model=IPBanStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ban IP address",
    description="Manually ban an IP address with optional duration",
)
async def ban_ip(
    request: IPBanRequest,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> IPBanStatusResponse:
    """
    Manually ban an IP address.

    Can specify custom ban duration or use default.
    """
    ban_service = await get_ban_service()

    if not ban_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ban service not available"
        ) from None

    try:
        # Ban the IP
        await ban_service.ban_ip(ip=request.ip_address, duration_seconds=request.duration_seconds)

        # Get ban info
        ban_info = await ban_service.get_ban_info(request.ip_address)

        logger.info(
            "IP manually banned: %s for %d seconds",
            request.ip_address,
            request.duration_seconds or ban_service.ban_duration,
        )

        return IPBanStatusResponse(
            ip_address=request.ip_address,
            is_banned=True,
            banned_until=ban_info["banned_until"] if ban_info else None,
            remaining_seconds=ban_info["remaining_seconds"] if ban_info else None,
        )

    except Exception as e:
        logger.error(f"Failed to ban IP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to ban IP: {e!s}"
        ) from None


@router.delete(
    "/bans",
    response_model=IPUnbanResponse,
    summary="Unban IP address",
    description="Remove IP address from ban list",
)
async def unban_ip(
    request: IPUnbanRequest,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> IPUnbanResponse:
    """
    Manually unban an IP address.

    Removes IP from ban list and clears violation history.
    """
    ban_service = await get_ban_service()

    if not ban_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ban service not available"
        ) from None

    try:
        was_banned = await ban_service.unban_ip(request.ip_address)

        logger.info("IP unban requested: %s (was_banned=%s)", request.ip_address, was_banned)

        return IPUnbanResponse(
            ip_address=request.ip_address,
            was_banned=was_banned,
            message="IP unbanned successfully" if was_banned else "IP was not banned",
        )

    except Exception as e:
        logger.error(f"Failed to unban IP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to unban IP: {e!s}"
        ) from None


@router.get(
    "/bans",
    response_model=IPBanListResponse,
    summary="List banned IPs",
    description="Get list of all currently banned IP addresses",
)
async def list_banlist(
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> IPBanListResponse:
    """
    Get list of all ban IPs.
    """
    ban_service = await get_ban_service()

    if not ban_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ban service not available"
        ) from None

    try:
        entries = await ban_service.list_all()

        return IPBanListResponse(
            entries=[
                IPBanEntry(ip_address=entry["ip"], banned_until=entry["banned_until"])
                for entry in entries
            ],
            total=len(entries),
        )

    except Exception as e:
        logger.error(f"Failed to list ban: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list ban: {e!s}"
        ) from None


@router.get(
    "/bans/{ip_address}",
    response_model=IPBanStatusResponse,
    summary="Check IP ban status",
    description="Get ban status and details for an IP address",
)
async def get_ban_status(
    ip_address: str,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> IPBanStatusResponse:
    """
    Check if IP is banned and get ban details.
    """
    ban_service = await get_ban_service()

    if not ban_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ban service not available"
        ) from None

    try:
        is_banned = await ban_service.is_banned(ip_address)
        ban_info = await ban_service.get_ban_info(ip_address) if is_banned else None

        return IPBanStatusResponse(
            ip_address=ip_address,
            is_banned=is_banned,
            banned_until=ban_info["banned_until"] if ban_info else None,
            remaining_seconds=ban_info["remaining_seconds"] if ban_info else None,
        )

    except Exception as e:
        logger.error(f"Failed to get ban status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ban status: {e!s}",
        ) from None


# ═══════════════════════════════════════════════════════════════════════════
# Whitelist Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/whitelist",
    response_model=WhitelistAddResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add IP to whitelist",
    description="Add IP address or CIDR range to whitelist",
)
async def add_to_whitelist(
    request: WhitelistAddRequest,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> WhitelistAddResponse:
    """
    Add IP address to whitelist.

    Whitelisted IPs are exempt from rate limiting.
    """
    whitelist_service = await get_whitelist_service()

    if not whitelist_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Whitelist service not available",
        ) from None

    try:
        await whitelist_service.add(ip_address=request.ip_address, description=request.description)

        logger.info(
            "IP added to whitelist: %s (%s)",
            request.ip_address,
            request.description or "no description",
        )

        return WhitelistAddResponse(
            ip_address=request.ip_address,
            description=request.description,
            message="IP added to whitelist successfully",
        )

    except Exception as e:
        logger.error(f"Failed to add to whitelist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add to whitelist: {e!s}",
        ) from None


@router.delete(
    "/whitelist",
    response_model=WhitelistRemoveResponse,
    summary="Remove IP from whitelist",
    description="Remove IP address from whitelist",
)
async def remove_from_whitelist(
    request: WhitelistRemoveRequest,
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> WhitelistRemoveResponse:
    """
    Remove IP address from whitelist.
    """
    whitelist_service = await get_whitelist_service()

    if not whitelist_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Whitelist service not available",
        ) from None

    try:
        removed = await whitelist_service.remove(request.ip_address)

        logger.info("IP removed from whitelist: %s (existed=%s)", request.ip_address, removed)

        return WhitelistRemoveResponse(
            ip_address=request.ip_address,
            was_whitelisted=removed,
            message="IP removed from whitelist" if removed else "IP was not in whitelist",
        )

    except Exception as e:
        logger.error(f"Failed to remove from whitelist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove from whitelist: {e!s}",
        ) from None


@router.get(
    "/whitelist",
    response_model=WhitelistListResponse,
    summary="List whitelisted IPs",
    description="Get all whitelisted IP addresses",
)
async def list_whitelist(
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> WhitelistListResponse:
    """
    Get list of all whitelisted IPs.
    """
    whitelist_service = await get_whitelist_service()

    if not whitelist_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Whitelist service not available",
        ) from None

    try:
        entries = await whitelist_service.list_all()

        return WhitelistListResponse(
            entries=[
                WhitelistEntry(
                    ip_address=entry["ip_address"],
                    description=entry.get("description"),
                    added_at=entry["added_at"],
                )
                for entry in entries
            ],
            total=len(entries),
        )

    except Exception as e:
        logger.error(f"Failed to list whitelist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list whitelist: {e!s}",
        ) from None
