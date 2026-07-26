from typing import Annotated

from pydantic import Field
from typing_extensions import deprecated

from v2hub_api.core.config import settings

from .base import BaseModelConfig


@deprecated(
    "The `CommentUpdateRequest` is deprecated; use `SourceUpdateRequest` instead.",
    category=None,
)
class CommentUpdateRequest(BaseModelConfig):
    """Request to update config comment."""

    config_id: Annotated[str, Field(description="Config id", min_length=1)]
    comment: Annotated[str | None, Field(None, description="Comment text", max_length=256)]


# ─────────────────────────────────────────────────────────
# Resolver models
# ─────────────────────────────────────────────────────────


class ResolvedConfig(BaseModelConfig):
    hash: str
    config: str
    is_hidden: bool | None = None
    max_depth: int | None = settings.max_nesting_depth


# ─────────────────────────────────────────────────────────
# Internal models
# ─────────────────────────────────────────────────────────


class UpsertUserRequest(BaseModelConfig):
    user_hash: str = Field(..., min_length=1)
    user_id: int = Field(..., gt=0)
    api_token: str = Field(..., min_length=1)
