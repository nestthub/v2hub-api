from datetime import datetime
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator

from v2hub_api.core.config import settings
from v2hub_api.core.constants import COMMENT_MAX_LENGTH, HASH_LENGTH
from v2hub_api.core.enums import SourceType
from v2hub_api.utils.config_parser import _clean_sources, _normalize_sources

from .base import BaseModelConfig


class SourceOut(BaseModelConfig):
    """
    Simplified source model for the API.

    The `data` field contains:
    - For CONFIG: the configuration with an optional comment
    - For EXTERNAL_URL: the subscription URL
    - For INTERNAL_TOKEN: the token of another subscription
    """

    id: Annotated[
        str,
        Field(
            description="Unique source identifier (hash)",
            min_length=HASH_LENGTH,
            max_length=HASH_LENGTH,
        ),
    ]
    source_type: Annotated[SourceType, Field(description="Type of source")]
    data: Annotated[str, Field(description="Source data (config, URL, or token)", min_length=1)]
    order_index: Annotated[int, Field(description="Display order", ge=0)]

    is_hidden: Annotated[
        bool,
        Field(description="Whether the source is hidden from end users", default=False),
    ]

    max_depth: Annotated[
        int,
        Field(
            description="Maximum nesting depth for source visibility propagation (0-3)",
            ge=0,
            le=settings.max_nesting_depth,
            default=settings.max_nesting_depth,
        ),
    ]

    created_at: Annotated[datetime, Field(description="Creation timestamp")]
    updated_at: Annotated[datetime, Field(description="Last update timestamp")]


class SourceCreateRequest(BaseModelConfig):
    data: str

    is_hidden: bool | None = None

    max_depth: Annotated[
        int | None,
        Field(ge=0, le=settings.max_nesting_depth),
    ] = None


class SourcesAddRequest(BaseModelConfig):
    sources: Annotated[
        list[SourceCreateRequest],
        Field(..., min_length=1, max_length=settings.max_sources_per_subscription),
    ]

    @field_validator("sources", mode="before")
    @classmethod
    def clean_sources(cls, values: list[str | dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = _normalize_sources(values)

        if not cleaned:
            raise ValueError("sources list is empty after deduplication")

        return cleaned


class SourcesReplaceRequest(BaseModelConfig):
    sources: Annotated[
        list[SourceCreateRequest],
        Field(default_factory=list, max_length=settings.max_sources_per_subscription),
    ]

    @field_validator("sources", mode="before")
    @classmethod
    def clean_sources(cls, values: list[str | dict[str, Any]]) -> list[dict[str, Any]]:
        return _normalize_sources(values)


class SourcesRemoveRequest(BaseModelConfig):
    source_ids: Annotated[
        list[Annotated[str, Field(min_length=HASH_LENGTH, max_length=HASH_LENGTH)]],
        Field(..., min_length=1),
    ]

    @field_validator("source_ids", mode="before")
    @classmethod
    def clean_ids(cls, v: list[str]) -> list[str]:
        cleaned = _clean_sources(v)
        if not cleaned:
            raise ValueError("source_ids is empty")
        return cleaned


class SourceUpdateRequest(BaseModelConfig):
    """Request to update config settings."""

    config_hash: Annotated[
        str,
        Field(
            description="Config hash",
            min_length=HASH_LENGTH,
            max_length=HASH_LENGTH,
            validation_alias=AliasChoices("config_hash", "config_id"),
        ),
    ]

    comment: Annotated[
        str | None,
        Field(None, description="Comment text", max_length=COMMENT_MAX_LENGTH),
    ]

    is_hidden: Annotated[
        bool | None,
        Field(None, description="Whether the source is hidden from end users"),
    ]

    max_depth: Annotated[
        int | None,
        Field(
            None,
            description="Maximum nesting depth for source visibility propagation (0-3)",
            ge=0,
            le=settings.max_nesting_depth,
        ),
    ]
