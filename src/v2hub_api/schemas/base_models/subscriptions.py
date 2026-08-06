from datetime import datetime
from typing import Annotated, Any

from pydantic import ConfigDict, Field, computed_field, field_validator

from v2hub_api.core.config import settings
from v2hub_api.utils.config_parser import _normalize_sources

from .base import BaseModelConfig
from .sources import SourceCreateRequest, SourceOut


class SubscriptionBase(BaseModelConfig):
    token: Annotated[str, Field(description="Unique subscription token", min_length=1)]
    name: Annotated[
        str, Field(description="User-defined subscription name", min_length=1, max_length=64)
    ]
    provider_name: Annotated[str | None, Field(None, description="Provider name")]
    description: Annotated[
        str | None, Field(None, description="Optional description", max_length=64)
    ]
    sources_count: Annotated[int, Field(description="Total resolved configs count", ge=0)]
    created_at: Annotated[datetime, Field(description="Creation timestamp")]
    updated_at: Annotated[datetime, Field(description="Last update timestamp")]


class SubscriptionResponse(SubscriptionBase):
    sources: Annotated[
        list[SourceOut],
        Field(default_factory=list, description="List of sources"),
    ]

    model_config = ConfigDict(from_attributes=True)


class SubscriptionListItem(SubscriptionBase):
    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────


class SubscriptionCreateRequest(BaseModelConfig):
    name: Annotated[str, Field(description="Subscription name", min_length=1, max_length=64)]
    description: Annotated[
        str | None, Field(None, description="Optional description", max_length=64)
    ] = None
    sources: Annotated[
        list[SourceCreateRequest],
        Field(
            default_factory=list,
            description="Initial sources",
            max_length=settings.max_sources_per_subscription,
        ),
    ]

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("sources", mode="before")
    @classmethod
    def clean_sources(cls, values: list[str | dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = _normalize_sources(values)

        if not cleaned:
            raise ValueError("sources list is empty after deduplication")

        return cleaned


class SubscriptionUpdateRequest(BaseModelConfig):
    name: Annotated[
        str | None, Field(None, description="New name", min_length=1, max_length=64)
    ] = None
    description: Annotated[
        str | None, Field(None, description="New description", max_length=64)
    ] = None

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
    def total(self) -> int:
        return self.refreshed + self.failed + self.skipped

    message: Annotated[
        str | None,
        Field(None, description="Optional status message describing refresh result"),
    ]

    errors: Annotated[
        list[str],
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
