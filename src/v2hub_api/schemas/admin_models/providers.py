from typing import Annotated

from pydantic import ConfigDict, Field

from .base import AdminBaseModel


class ProviderCreateRequest(AdminBaseModel):
    """Request model for creating a new provider."""

    owner_hash: str = Field(..., description="Provider`s owner hash", min_length=36, max_length=36)
    provider_name: str = Field(..., description="Provider name", min_length=4, max_length=16)
    provider_url: str | None = Field(None, description="Provider address url", max_length=255)

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

    provider_hash: str = Field(..., description="Provider hash", min_length=36, max_length=36)
    owner_hash: str = Field(..., description="Owner hash", min_length=36, max_length=36)
    provider_name: str = Field(..., description="Provider name", min_length=4, max_length=16)
    api_token: str = Field(..., description="Generated API token", min_length=43, max_length=43)
    provider_url: str | None = Field(description="Provider url", max_length=255)
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
        Annotated[str, Field(min_length=4, max_length=16)],
        Annotated[str, Field(min_length=36, max_length=36)],
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

    provider_url: str | None = Field(max_length=255)


class ProviderNameUpdateRequest(AdminBaseModel):
    """Request model for updating provider name."""

    provider_name: str = Field(min_length=4, max_length=16)


class ProviderCreateResponse(ProviderResponse):
    """Response model for provider creation."""

    pass


class ProviderTokenRefreshRequest(AdminBaseModel):
    """Request model for refreshing provider token."""

    provider_hash: str = Field(..., description="Provider hash", min_length=36, max_length=36)

    model_config = ConfigDict(json_schema_extra={"example": {"provider_hash": "a1b2c3d4e5f6..."}})


class ProviderTokenRefreshResponse(AdminBaseModel):
    """Response model for token refresh."""

    provider_hash: str = Field(..., description="Provider hash", min_length=36, max_length=36)
    new_api_token: str = Field(..., description="New API token", min_length=43, max_length=43)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider_hash": "a1b2c3d4e5f6...",
                "new_api_token": "a1b2c3d4e5f6...:x9y8z7w6v5u4...",
            }
        }
    )
