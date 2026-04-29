from .base import BaseModelConfig, _clean_sources

from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from src.core.config import settings
from src.core.enums import SourceType



class SourceOut(BaseModelConfig):
    """
    Упрощенная модель источника для API.
    
    Поле data содержит:
    - Для CONFIG: конфиг с комментом (если есть)
    - Для EXTERNAL_URL: URL подписки
    - Для INTERNAL_TOKEN: токен другой подписки
    """
    id: Annotated[str, Field(description="Unique source identifier (hash)", min_length=1)]
    source_type: Annotated[SourceType, Field(description="Type of source")]
    data: Annotated[str, Field(description="Source data (config, URL, or token)", min_length=1)]
    order_index: Annotated[int, Field(description="Display order", ge=0)]
    created_at: Annotated[datetime, Field(description="Creation timestamp")]
    updated_at: Annotated[datetime, Field(description="Last update timestamp")]





class SourceAddRequest(BaseModelConfig):
    sources: Annotated[
        list[str],
        Field(..., min_length=1, max_length=settings.max_sources_per_subscription),
    ]

    @field_validator("sources", mode="before")
    @classmethod
    def clean_sources(cls, v: list[str]) -> list[str]:
        v = _clean_sources(v)
        if not v:
            raise ValueError("sources list is empty after deduplication")
        return v


class SourceReplaceRequest(BaseModelConfig):
    sources: Annotated[
        list[str],
        Field(default_factory=list, max_length=settings.max_sources_per_subscription),
    ]

    @field_validator("sources", mode="before")
    @classmethod
    def clean_sources(cls, v: list[str]) -> list[str]:
        return _clean_sources(v)

class SourceRemoveRequest(BaseModelConfig):
    source_ids: Annotated[list[str], Field(..., min_length=1)]

    @field_validator("source_ids", mode="before")
    @classmethod
    def clean_ids(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("source_ids is empty")
        return cleaned
