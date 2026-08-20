from pydantic import Field

from v2hub_api.core.constants import (
    PROVIDER_NAME_MAX_LENGTH,
    PROVIDER_NAME_MIN_LENGTH,
    URL_MAX_LENGTH,
    USER_ID_MAX,
    USER_ID_MIN,
)
from v2hub_api.core.enums import ProviderAuthorizationStatus

from .base import BaseModelConfig


class ProviderConnectionRequest(BaseModelConfig):
    user_id: int = Field(
        description="Target user ID",
        ge=USER_ID_MIN,
        le=USER_ID_MAX,
    )


class ProviderConnectionResponse(BaseModelConfig):
    user_id: int = Field(
        description="User ID",
        ge=USER_ID_MIN,
        le=USER_ID_MAX,
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
        min_length=PROVIDER_NAME_MIN_LENGTH,
        max_length=PROVIDER_NAME_MAX_LENGTH,
    )
    provider_url: str = Field(description="Provider url", max_length=URL_MAX_LENGTH)
