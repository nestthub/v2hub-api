from typing import Annotated

from pydantic import ConfigDict, Field

from ..base import AdminBaseModel


class IPBanRequest(AdminBaseModel):
    """Request model for banning an IP."""

    ip_address: str = Field(..., description="IP address to ban")
    duration_seconds: int | None = Field(
        default=None, description="Ban duration in seconds (default: use system setting)"
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"ip_address": "192.168.1.100", "duration_seconds": 3600}}
    )


class IPUnbanRequest(AdminBaseModel):
    """Request model for unbanning an IP."""

    ip_address: Annotated[str, Field(description="IP address to unban", min_length=8)]

    model_config = ConfigDict(json_schema_extra={"example": {"ip_address": "192.168.1.100"}})


class IPUnbanResponse(AdminBaseModel):
    """Response from unban operation."""

    ip_address: Annotated[str, Field(description="IP address")]
    was_banned: Annotated[bool, Field(description="Whether IP was previously banned")]
    message: Annotated[str, Field(description="Result message")]


class IPBanStatusResponse(AdminBaseModel):
    """Response model for ban status."""

    ip_address: Annotated[str, Field(description="Banned IP address")]
    is_banned: Annotated[bool, Field(description="Whether IP is now banned")]
    banned_until: Annotated[str | None, Field(None, description="Ban expiration time")]
    remaining_seconds: Annotated[int | None, Field(None, description="Seconds until unban", ge=0)]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ip_address": "192.168.1.100",
                "is_banned": True,
                "banned_until": "2026-04-20T12:00:00",
                "remaining_seconds": 3600,
            }
        }
    )


class IPBanEntry(AdminBaseModel):
    """Banlist entry model."""

    ip_address: Annotated[str, Field(description="Banned IP address")]
    banned_until: Annotated[str | None, Field(description="Ban expiration time")] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"ip_address": "192.168.1.100", "banned_until": "2026-04-20T10:00:00"}
        }
    )


class IPBanListResponse(AdminBaseModel):
    """Response model for banlist listing."""

    entries: list[IPBanEntry]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entries": [{"ip_address": "192.168.1.100", "banned_until": "2026-04-20T10:00:00"}],
                "total": 1,
            }
        }
    )
