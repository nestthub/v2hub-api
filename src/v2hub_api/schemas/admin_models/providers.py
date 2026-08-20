from typing import Annotated

from pydantic import ConfigDict, Field

from v2hub_api.core.constants import (
    API_TOKEN_LENGTH,
    PROVIDER_NAME_MAX_LENGTH,
    PROVIDER_NAME_MIN_LENGTH,
    URL_MAX_LENGTH,
    UUID_LENGTH,
)

from .base import AdminBaseModel


class ProviderCreateRequest(AdminBaseModel):
    """Request model for creating a new provider."""

    owner_hash: str = Field(
        ..., description="Provider`s owner hash", min_length=UUID_LENGTH, max_length=UUID_LENGTH
    )
    provider_name: str = Field(
        ...,
        description="Provider name",
        min_length=PROVIDER_NAME_MIN_LENGTH,
        max_length=PROVIDER_NAME_MAX_LENGTH,
    )
    provider_url: str | None = Field(
        None, description="Provider address url", max_length=URL_MAX_LENGTH
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "owner_hash": "a1b2c3d4e5f6...",
                "provider_name": "vpn123",
                "provider_url": "https://t.me/examplebot",
            }
        }
    )


class ProviderResponse(AdminBaseModel):
    """Response model for provider."""

    provider_hash: str = Field(
        ..., description="Provider hash", min_length=UUID_LENGTH, max_length=UUID_LENGTH
    )
    owner_hash: str = Field(
        ..., description="Owner hash", min_length=UUID_LENGTH, max_length=UUID_LENGTH
    )
    provider_name: str = Field(
        ...,
        description="Provider name",
        min_length=PROVIDER_NAME_MIN_LENGTH,
        max_length=PROVIDER_NAME_MAX_LENGTH,
    )
    api_token: str = Field(
        ...,
        description="Generated API token",
        min_length=API_TOKEN_LENGTH,
        max_length=API_TOKEN_LENGTH,
    )
    provider_url: str | None = Field(description="Provider url", max_length=URL_MAX_LENGTH)
    is_active: bool = Field(..., description="Account status")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider_hash": "a1b2c3d4e5f6...",
                "owner_hash": "q1w2e3r4t5y6...",
                "provider_name": "vpn123",
                "api_token": "a1b2c3d4e5f6...",
                "provider_url": "https://t.me/examplebot",
                "is_active": True,
            }
        }
    )


class AllProvidersResponse(AdminBaseModel):
    """Response model for all providers."""

    provider_hashes: dict[
        Annotated[
            str, Field(min_length=PROVIDER_NAME_MIN_LENGTH, max_length=PROVIDER_NAME_MAX_LENGTH)
        ],
        Annotated[str, Field(min_length=UUID_LENGTH, max_length=UUID_LENGTH)],
    ] = Field(
        ...,
        description="Mapping of provider names to provider hashes",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider_hashes": {
                    "Provider A": "a1b2c3d4e5f6...",
                    "Provider B": "q9w8e7r6t5y4...",
                }
            }
        }
    )


class ProviderStatusUpdateRequest(AdminBaseModel):
    """Request model for updating provider status."""

    is_active: bool


class ProviderURLUpdateRequest(AdminBaseModel):
    """Request model for updating provider url."""

    provider_url: str | None = Field(max_length=URL_MAX_LENGTH)


class ProviderNameUpdateRequest(AdminBaseModel):
    """Request model for updating provider name."""

    provider_name: str = Field(
        min_length=PROVIDER_NAME_MIN_LENGTH, max_length=PROVIDER_NAME_MAX_LENGTH
    )


class ProviderCreateResponse(ProviderResponse):
    """Response model for provider creation."""

    pass


class ProviderTokenRefreshRequest(AdminBaseModel):
    """Request model for refreshing provider token."""

    provider_hash: str = Field(
        ..., description="Provider hash", min_length=UUID_LENGTH, max_length=UUID_LENGTH
    )

    model_config = ConfigDict(json_schema_extra={"example": {"provider_hash": "a1b2c3d4e5f6..."}})


class ProviderTokenRefreshResponse(AdminBaseModel):
    """Response model for token refresh."""

    provider_hash: str = Field(
        ..., description="Provider hash", min_length=UUID_LENGTH, max_length=UUID_LENGTH
    )
    new_api_token: str = Field(
        ..., description="New API token", min_length=API_TOKEN_LENGTH, max_length=API_TOKEN_LENGTH
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider_hash": "a1b2c3d4e5f6...",
                "new_api_token": "a1b2c3d4e5f6...:x9y8z7w6v5u4...",
            }
        }
    )
