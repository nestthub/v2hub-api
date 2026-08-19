from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.db.models import Base, TimestampMixin

if TYPE_CHECKING:
    from . import ProviderAuthorization, Subscription, User

# ═══════════════════════════════════════════════════════════════════════════
# Provider Management
# ═══════════════════════════════════════════════════════════════════════════


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    provider_hash: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="Unique public identifier of the provider",
    )

    owner_hash: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.user_hash", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="Hash of the user account that owns this provider",
    )

    provider_name: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, comment="Unique provider name."
    )

    api_token: Mapped[str] = mapped_column(
        String(43),
        unique=True,
        nullable=False,
        index=True,
        comment="Provider API authentication token",
    )

    provider_url: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Provider website or bot URL",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("TRUE"),
        nullable=False,
        comment="Whether the provider account is active",
    )

    # Relationships
    owner: Mapped[User] = relationship(
        "User",
        back_populates="provider",
        lazy="raise",
    )

    authorizations: Mapped[list[ProviderAuthorization]] = relationship(
        "ProviderAuthorization",
        back_populates="provider",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription",
        back_populates="provider",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Provider provider_hash={self.provider_hash!r} owner_hash={self.owner_hash!r}>"
