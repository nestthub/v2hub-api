from typing import Annotated

from pydantic import AliasChoices, Field
from typing_extensions import deprecated

from v2hub_api.core.config import settings

from .base import BaseModelConfig


@deprecated(
    "The `CommentUpdateRequest` is deprecated; use `SourceUpdateRequest` instead.",
    category=None,
)
class CommentUpdateRequest(BaseModelConfig):
    """Request to update config comment."""

    config_hash: Annotated[
        str,
        Field(
            description="Config hash",
            min_length=32,
            max_length=32,
            validation_alias=AliasChoices("config_hash", "config_id"),
        ),
    ]
    comment: Annotated[str | None, Field(None, description="Comment text", max_length=255)]


# ─────────────────────────────────────────────────────────
# Resolver models
# ─────────────────────────────────────────────────────────


class ResolvedConfig(BaseModelConfig):
    hash: str = Field(..., description="Source hash", min_length=32, max_length=32)
    config: str = Field(..., description="Config")
    is_hidden: bool | None = None
    max_depth: int | None = settings.max_nesting_depth


# ─────────────────────────────────────────────────────────
# Internal models
# ─────────────────────────────────────────────────────────


class UpsertUserRequest(BaseModelConfig):
    user_hash: str = Field(..., description="User hash (UUID)", min_length=36, max_length=36)
    user_id: int = Field(..., description="User ID", gt=0, le=999_999_999_999)
    api_token: str = Field(..., description="User's API-token", min_length=43, max_length=43)
