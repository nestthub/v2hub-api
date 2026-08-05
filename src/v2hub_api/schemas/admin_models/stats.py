from typing import Annotated

from pydantic import ConfigDict, Field

from .base import AdminBaseModel


class GeneralStats(AdminBaseModel):
    """General business metrics for the platform."""

    total_users: Annotated[int, Field(description="Total number of registered users")]
    new_users: Annotated[int, Field(description="New users within the selected period")]
    new_subscriptions: Annotated[
        int, Field(description="New subscriptions within the selected period")
    ]


class StatsResponse(AdminBaseModel):
    """Complete statistics response payload."""

    general: GeneralStats

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"general": {"total_users": 1542, "new_users": 45, "new_subscriptions": 12}}
        }
    )
