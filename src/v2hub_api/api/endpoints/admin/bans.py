"""
Admin API endpoints for IP ban management.

Provides secure endpoints for:
- Banning IP addresses
- Unbanning IP addresses
- Listing banned IP addresses
- Checking IP ban status

All endpoints require admin request signature and internal IP verification.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from v2hub_api.schemas import (
    IPBanEntry,
    IPBanListResponse,
    IPBanRequest,
    IPBanStatusResponse,
    IPUnbanRequest,
    IPUnbanResponse,
)
from v2hub_api.services.ban_service import get_ban_service

from .dependencies import AdminSecurityDep, InternalIPDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bans")

# ═══════════════════════════════════════════════════════════════════════════
# IP Ban Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "",
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
    "",
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
    "",
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
    "/{ip_address}",
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
