from typing import Annotated, Optional

from pydantic import Field

from .base import BaseModelConfig

from typing_extensions import deprecated

from src.core.config import settings



@deprecated(
    'The `CommentUpdateRequest` is deprecated; use `SourceUpdateRequest` instead.',
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
    is_hidden: Optional[bool] = None
    max_depth: Optional[int] = settings.max_nesting_depth


# ─────────────────────────────────────────────────────────
# Internal models
# ─────────────────────────────────────────────────────────

class UpsertUserRequest(BaseModelConfig):
    user_hash: str = Field(..., min_length=1)
    user_id: int = Field(..., gt=0)
    api_token: str = Field(..., min_length=1)




