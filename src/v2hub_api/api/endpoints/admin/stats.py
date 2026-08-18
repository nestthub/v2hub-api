"""
Admin API endpoints for platform statistics.

Provides secure endpoints for:
- Retrieving aggregated API usage statistics
- Filtering statistics by date range
- Retrieving statistics for predefined periods

All endpoints require admin request signature verification
and an allowed internal IP address.
"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from v2hub_api.api.dependencies import StatsServiceDep
from v2hub_api.schemas import (
    StatsResponse,
)

from .dependencies import AdminSecurityDep, InternalIPDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats")


# ═══════════════════════════════════════════════════════════════════════════
# Business Metrics & Statistics
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "",
    response_model=StatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get API usage statistics",
    description="Retrieve aggregated business metrics with optional time filtering.",
)
async def get_statistics(
    stats_service: StatsServiceDep,
    start_date: datetime | None = Query(None, description="Start date (ISO 8601)"),
    end_date: datetime | None = Query(None, description="End date (ISO 8601)"),
    period: Literal["day", "week", "month"] | None = Query(None, description="Predefined period"),
    _signature: None = AdminSecurityDep,
    _ip: None = InternalIPDep,
) -> StatsResponse:
    """
    Get platform statistics.

    Defaults to all-time stats if no date filters are provided.
    Protected by admin signature and IP restrictions.
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )

    try:
        return await stats_service.get_statistics(
            start_date=start_date,
            end_date=end_date,
            period=period,
        )
    except Exception as e:
        logger.error(f"Failed to retrieve statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to aggregate statistics",
        ) from e
