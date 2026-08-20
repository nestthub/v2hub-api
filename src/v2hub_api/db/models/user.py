from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.core.constants import API_TOKEN_LENGTH, UUID_LENGTH
from v2hub_api.db.models import Base, TimestampMixin

if TYPE_CHECKING:
    from . import Provider, ProviderAuthorization, Subscription

# ═══════════════════════════════════════════════════════════════════════════
# User Management
# ═══════════════════════════════════════════════════════════════════════════


class User(TimestampMixin, Base):
    """
    User account with authentication credentials.

    The user_hash serves as the primary key and is derived from external
    user identification. The api_token is used for API authentication.
    """

    __tablename__ = "users"

    user_hash: Mapped[str] = mapped_column(
        String(UUID_LENGTH), primary_key=True, comment="Stable hash derived from external user ID"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
        comment="Original user ID from external system",
    )
    api_token: Mapped[str] = mapped_column(
        String(API_TOKEN_LENGTH),
        unique=True,
        nullable=False,
        index=True,
        comment="API authentication token",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("TRUE"), comment="Whether user account is active"
    )

    # Relationships
    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    provider: Mapped[Provider | None] = relationship(
        "Provider",
        back_populates="owner",
        uselist=False,
        lazy="raise",
    )

    provider_authorizations: Mapped[list[ProviderAuthorization]] = relationship(
        "ProviderAuthorization",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<User user_id={self.user_id} active={self.is_active}>"
