from pydantic import Field

from v2hub_api.core.constants import (
    AUTH_HMAC_LENGTH,
    PROVIDER_NAME_MAX_LENGTH,
    PROVIDER_NAME_MIN_LENGTH,
    USER_ID_MAX,
    USER_ID_MIN,
)
from v2hub_api.core.enums import ProviderAuthorizationStatus
from v2hub_api.schemas.admin_models.base import AdminBaseModel


class ProviderAuthorizationInfoResponse(AdminBaseModel):
    provider_name: str = Field(
        description="Provider name",
    )
    provider_url: str | None = Field(
        description="Provider URL",
    )
    user_id: int = Field(
        description="User ID",
        ge=USER_ID_MIN,
        le=USER_ID_MAX,
    )
    status: ProviderAuthorizationStatus | None = Field(
        default=None,
        description="Current authorization status",
    )


class ProviderAuthorizationBaseRequest(AdminBaseModel):
    user_id: int = Field(
        description="User ID",
        ge=USER_ID_MIN,
        le=USER_ID_MAX,
    )
    provider_name: str = Field(
        description="Provider name",
        min_length=PROVIDER_NAME_MIN_LENGTH,
        max_length=PROVIDER_NAME_MAX_LENGTH,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )


class ProviderAuthorizationRequest(ProviderAuthorizationBaseRequest):
    hmac: str | None = Field(
        default=None,
        description="Authorization HMAC",
        min_length=AUTH_HMAC_LENGTH,
        max_length=AUTH_HMAC_LENGTH,
    )


class ProviderAuthorizationDecisionRequest(ProviderAuthorizationBaseRequest):
    pass
