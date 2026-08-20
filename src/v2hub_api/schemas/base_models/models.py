from typing import Annotated

from pydantic import AliasChoices, Field
from typing_extensions import deprecated

from v2hub_api.core.config import settings
from v2hub_api.core.constants import (
    API_TOKEN_LENGTH,
    COMMENT_MAX_LENGTH,
    HASH_LENGTH,
    USER_ID_MAX,
    USER_ID_MIN,
    UUID_LENGTH,
)

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
            min_length=HASH_LENGTH,
            max_length=HASH_LENGTH,
            validation_alias=AliasChoices("config_hash", "config_id"),
        ),
    ]
    comment: Annotated[
        str | None, Field(None, description="Comment text", max_length=COMMENT_MAX_LENGTH)
    ]


# ─────────────────────────────────────────────────────────
# Resolver models
# ─────────────────────────────────────────────────────────


class ResolvedConfig(BaseModelConfig):
    hash: str = Field(
        ..., description="Source hash", min_length=HASH_LENGTH, max_length=HASH_LENGTH
    )
    config: str = Field(..., description="Config")
    is_hidden: bool | None = None
    max_depth: int | None = settings.max_nesting_depth


# ─────────────────────────────────────────────────────────
# Internal models
# ─────────────────────────────────────────────────────────


class UpsertUserRequest(BaseModelConfig):
    user_hash: str = Field(
        ..., description="User hash (UUID)", min_length=UUID_LENGTH, max_length=UUID_LENGTH
    )
    user_id: int = Field(..., description="User ID", ge=USER_ID_MIN, le=USER_ID_MAX)
    api_token: str = Field(
        ...,
        description="User's API-token",
        min_length=API_TOKEN_LENGTH,
        max_length=API_TOKEN_LENGTH,
    )
