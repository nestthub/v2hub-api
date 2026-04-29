from typing import Annotated, Optional
from pydantic import Field

from ..base import AdminBaseModel



class WhitelistAddRequest(AdminBaseModel):
    """Request model for adding IP to whitelist."""
    ip_address: str = Field(..., description="IP address or CIDR to whitelist")
    description: Optional[str] = Field(
        None,
        max_length=255,
        description="Description/reason for whitelisting"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "10.0.0.0/24",
                "description": "Internal office network"
            }
        }

class WhitelistAddResponse(AdminBaseModel):
    """Response from whitelist add operation."""

    ip_address: Annotated[str, Field(description="Whitelisted IP/CIDR")]
    description: Annotated[str | None, Field(None, description="Description")]
    message: Annotated[str, Field(description="Result message")]


class WhitelistRemoveRequest(AdminBaseModel):
    """Request model for removing IP from whitelist."""
    ip_address: str = Field(..., description="IP address to remove")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "10.0.0.0/24"
            }
        }

class WhitelistRemoveResponse(AdminBaseModel):
    """Response from whitelist remove operation."""

    ip_address: Annotated[str, Field(description="IP address")]
    was_whitelisted: Annotated[bool, Field(description="Whether IP was previously whitelisted")]
    message: Annotated[str, Field(description="Result message")]


class WhitelistEntry(AdminBaseModel):
    """Whitelist entry model."""
    ip_address: str
    description: Optional[str] = None
    added_at: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "ip_address": "10.0.0.0/24",
                "description": "Internal office network",
                "added_at": "2026-04-20T10:00:00"
            }
        }


class WhitelistListResponse(AdminBaseModel):
    """Response model for whitelist listing."""

    entries: Annotated[
        list[WhitelistEntry],
        Field(default_factory=list, description="List of whitelisted IPs"),
    ]
    total: Annotated[int, Field(description="Total number of entries", ge=0)]
    class Config:
        json_schema_extra = {
            "example": {
                "entries": [
                    {
                        "ip_address": "10.0.0.0/24",
                        "description": "Internal office network",
                        "added_at": "2026-04-20T10:00:00"
                    }
                ],
                "total": 1
            }
        }
