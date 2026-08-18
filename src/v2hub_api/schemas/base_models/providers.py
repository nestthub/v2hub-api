from pydantic import Field

from v2hub_api.core.enums import ProviderAuthorizationStatus

from .base import BaseModelConfig


class ProviderConnectionRequest(BaseModelConfig):
    user_id: int = Field(
        description="Target user ID",
        gt=0,
    )


class ProviderConnectionResponse(BaseModelConfig):
    user_id: int = Field(
        description="User ID",
    )

    status: ProviderAuthorizationStatus = Field(
        description="Authorization status",
    )


class ProviderConnectionDeleteResponse(BaseModelConfig):
    detail: str = Field(
        description="Operation result",
    )


class ProviderInfoResponse(BaseModelConfig):
    provider_name: str = Field(
        description="Provider name",
    )
    provider_url: str = Field(description="Provider url")
