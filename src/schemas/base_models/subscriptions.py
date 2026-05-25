from .base import BaseModelConfig, _clean_sources
from .sources import SourceOut

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import Field, computed_field, field_validator

from src.core.config import settings
from src.utils.config_parser import normalize_source




class SubscriptionResponse(BaseModelConfig):
    token: Annotated[str, Field(description="Unique subscription token", min_length=1)]
    name: Annotated[
        str, Field(description="User-defined subscription name", min_length=1, max_length=64)
    ]
    description: Annotated[str | None, Field(None, description="Optional description", max_length=64)]
    sources: Annotated[list[SourceOut], Field(default_factory=list, description="List of sources")]
    sources_count: Annotated[int, Field(description="Total resolved configs count", ge=0)]
    created_at: Annotated[datetime, Field(description="Creation timestamp")]
    updated_at: Annotated[datetime, Field(description="Last update timestamp")]

    model_config = {"from_attributes": True}


class SubscriptionListItem(BaseModelConfig):
    token: Annotated[str, Field(description="Unique subscription token", min_length=1)]
    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str | None, Field(None, max_length=64)]
    sources_count: Annotated[int, Field(ge=0)]
    created_at: Annotated[datetime, Field()]
    updated_at: Annotated[datetime, Field()]


# ─────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────

class SubscriptionCreateRequest(BaseModelConfig):
    name: Annotated[str, Field(description="Subscription name", min_length=1, max_length=64)]
    description: Annotated[
        str | None, Field(None, description="Optional description", max_length=64)
    ] = None
    sources: Annotated[list[str], Field(default_factory=list, description="Initial sources", max_length=settings.max_sources_per_subscription)]

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("sources", mode="before")
    @classmethod
    def clean_sources(cls, v: list[str]) -> list[str]:
        v = _clean_sources(v)
    
        cleaned = []
        for s in v:
            s = normalize_source(s, settings.max_comment_length)
            cleaned.append(s)
    
        if not cleaned:
            raise ValueError("sources list is empty after deduplication")
    
        return cleaned


class SubscriptionUpdateRequest(BaseModelConfig):
    name: Annotated[str | None, Field(None, description="New name", min_length=1, max_length=64)] = None
    description: Annotated[str | None, Field(None, description="New description", max_length=64)] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate subscription name."""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Subscription name cannot be empty")
        return v

class RefreshSubscriptionResponse(BaseModelConfig):
    refreshed: Annotated[int, Field(0, description="Number of successfully refreshed sources")]
    failed: Annotated[int, Field(0, description="Number of sources that failed to refresh")]
    skipped: Annotated[int, Field(0, description="Number of sources skipped during refresh")]

    @computed_field
    @property
    def total(self) -> int:
        return self.refreshed + self.failed + self.skipped

    message: Annotated[
        Optional[str],
        Field(None, description="Optional status message describing refresh result"),
    ]

    errors: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="List of errors per source (e.g. URL or config)",
            json_schema_extra={
                "example": [
                    "https://example.com: timeout",
                    "https://bad.url: invalid format",
                ]
            },
        ),
    ]
