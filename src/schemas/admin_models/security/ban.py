from typing import Annotated, List, Optional
from pydantic import Field

from ..base import AdminBaseModel



class IPBanRequest(AdminBaseModel):
    """Request model for banning an IP."""
    ip_address: str = Field(..., description="IP address to ban")
    duration_seconds: Optional[int] = Field(
        default=None,
        description="Ban duration in seconds (default: use system setting)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "192.168.1.100",
                "duration_seconds": 3600
            }
        }


class IPUnbanRequest(AdminBaseModel):
    """Request model for unbanning an IP."""
    ip_address: Annotated[str, Field(description="IP address to unban", min_length=8)]
    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "192.168.1.100"
            }
        }

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
    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "192.168.1.100",
                "is_banned": True,
                "banned_until": "2026-04-20T12:00:00",
                "remaining_seconds": 3600
            }
        }

class IPBanEntry(AdminBaseModel):
    """Banlist entry model."""
    ip_address: Annotated[str, Field(description="Banned IP address")]
    banned_until: Annotated[Optional[str], Field(description="Ban expiration time")] = None

    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "192.168.1.100",
                "banned_until": "2026-04-20T10:00:00"
            }
        }


class IPBanListResponse(AdminBaseModel):
    """Response model for banlist listing."""
    entries: List[IPBanEntry]
    total: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "entries": [
                    {
                        "ip_address": "192.168.1.100",
                        "banned_until": "2026-04-20T10:00:00"
                    }
                ],
                "total": 1
            }
        }
