from typing import Annotated

from pydantic import Field

from .base import BaseModelConfig


class ConnectionResponse(BaseModelConfig):
    """
    Authorized provider connection for the current user.

    Represents a provider that is currently authorized to manage
    the user's subscriptions.
    """

    provider_name: Annotated[
        str,
        Field(description="Provider name", min_length=4, max_length=16),
    ]

    provider_url: Annotated[
        str | None,
        Field(
            description="Provider API URL",
            max_length=255,
        ),
    ]

    is_authorized: Annotated[
        bool,
        Field(
            description="Whether the provider is currently authorized to manage the user's subscriptions",
        ),
    ]


class ConnectionsResponse(BaseModelConfig):
    """
    Response containing the current user's provider connections.

    Only providers that are currently authorized are included.
    """

    connections: Annotated[
        list[ConnectionResponse],
        Field(
            description="List of provider connections authorized for the current user",
        ),
    ]


class MeResponse(BaseModelConfig):
    """
    Information about the currently authenticated user.

    Contains only public user information that is relevant to the
    self-service API. Internal identifiers such as user hashes are
    not exposed.
    """

    user_id: Annotated[
        int,
        Field(description="User identifier", gt=0, le=999_999_999_999),
    ]

    is_active: Annotated[
        bool,
        Field(
            description="Whether the user account is currently active",
        ),
    ]
