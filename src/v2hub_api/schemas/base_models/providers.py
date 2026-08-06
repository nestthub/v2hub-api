from pydantic import Field

from v2hub_api.db.models.provider_authorization import ProviderAuthorizationStatus

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
