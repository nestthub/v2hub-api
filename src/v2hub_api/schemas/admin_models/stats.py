from typing import Annotated
from pydantic import ConfigDict, Field
from .base import AdminBaseModel

class GeneralStats(AdminBaseModel):
    """General business metrics for the platform."""
    total_users: Annotated[int, Field(description="Total number of registered users")]
    new_users: Annotated[int, Field(description="New users within the selected period")]
    new_subscriptions: Annotated[int, Field(description="New subscriptions within the selected period")]
    new_providers: Annotated[int, Field(description="New proxy configs (providers) within the selected period")]

class ProviderStats(AdminBaseModel):
    """Metrics related to proxy providers."""
    active_providers: Annotated[int, Field(description="Total active proxy configs")]
    users_connected_to_providers: Annotated[int, Field(description="Distinct users with active proxy sources")]

class StatsResponse(AdminBaseModel):
    """Complete statistics response payload."""
    general: GeneralStats
    providers: ProviderStats

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "general": {
                    "total_users": 1542,
                    "new_users": 45,
                    "new_subscriptions": 12,
                    "new_providers": 3
                },
                "providers": {
                    "active_providers": 89,
                    "users_connected_to_providers": 1200
                }
            }
        }
    )