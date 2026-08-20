from pydantic import ConfigDict, Field

from .base import AdminBaseModel


class UserCreateRequest(AdminBaseModel):
    """Request model for creating a new user."""

    user_id: int = Field(..., description="External user ID", gt=0, le=999_999_999_999)

    model_config = ConfigDict(json_schema_extra={"example": {"user_id": 12345}})


class UserResponse(AdminBaseModel):
    """Response model for user."""

    user_hash: str = Field(..., description="Generated user hash", min_length=36, max_length=36)
    user_id: int = Field(..., description="User ID", gt=0, le=999_999_999_999)
    api_token: str = Field(..., description="Generated API token", min_length=43, max_length=43)
    is_active: bool = Field(..., description="Account status")
    provider_hash: str | None = Field(
        None, description="Provider hash associated with the user", min_length=36, max_length=36
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_hash": "a1b2c3d4e5f6...",
                "user_id": 12345,
                "api_token": "12345:a1b2c3d4e5f6...",
                "is_active": True,
                "provider_hash": None,
            }
        }
    )


class UserStatusUpdateRequest(AdminBaseModel):
    is_active: bool


class UserCreateResponse(UserResponse):
    """Response model for user creation."""

    pass


class TokenRefreshRequest(AdminBaseModel):
    """Request model for refreshing user token."""

    user_id: int = Field(..., description="User ID", gt=0, le=999_999_999_999)

    model_config = ConfigDict(json_schema_extra={"example": {"user_id": 12345}})


class TokenRefreshResponse(AdminBaseModel):
    """Response model for token refresh."""

    user_id: int = Field(..., description="User ID", gt=0, le=999_999_999_999)
    new_api_token: str = Field(..., description="New API token", min_length=43, max_length=43)

    model_config = ConfigDict(
        json_schema_extra={"example": {"user_id": 12345, "new_api_token": "12345_x9y8z7w6v5u4..."}}
    )
