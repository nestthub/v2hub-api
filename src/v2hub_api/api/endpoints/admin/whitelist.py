"""
Admin API endpoints for IP whitelist management.

Provides secure endpoints for:
- Adding IP addresses and CIDR ranges to the whitelist
- Removing IP addresses from the whitelist
- Listing whitelisted IP addresses

All endpoints require admin request signature verification
and an allowed internal IP address.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from v2hub_api.schemas import (
    WhitelistAddRequest,
    WhitelistAddResponse,
    WhitelistEntry,
    WhitelistListResponse,
    WhitelistRemoveRequest,
    WhitelistRemoveResponse,
)
from v2hub_api.services.whitelist_service import get_whitelist_service

from .dependencies import AdminSecurityDep, InternalIPDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whitelist")


# ═══════════════════════════════════════════════════════════════════════════
# Whitelist Management Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "",
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
    "",
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
    "",
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
