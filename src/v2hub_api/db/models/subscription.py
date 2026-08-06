from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.db.models import Base, TimestampMixin

if TYPE_CHECKING:
    from . import ConfigComment, Provider, Source, User

# ═══════════════════════════════════════════════════════════════════════════
# Subscription Management
# ═══════════════════════════════════════════════════════════════════════════


class Subscription(TimestampMixin, Base):
    """
    Named collection of proxy sources belonging to a user.

    Each subscription has a unique token that serves as the public identifier
    for accessing the subscription's resolved configuration.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index(
            "uq_user_subscription_name",
            "user_hash",
            "name",
            unique=True,
            postgresql_where=text("provider_hash IS NULL"),
            sqlite_where=text("provider_hash IS NULL"),
        ),
        Index(
            "uq_provider_subscription_name",
            "user_hash",
            "provider_hash",
            "name",
            unique=True,
            postgresql_where=text("provider_hash IS NOT NULL"),
            sqlite_where=text("provider_hash IS NOT NULL"),
        ),
        Index(
            "ix_subscriptions_user_hash",
            "user_hash",
        ),
    )

    token: Mapped[str] = mapped_column(
        String(255), primary_key=True, comment="Unique public identifier for subscription"
    )
    name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="User-defined name for subscription"
    )
    user_hash: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("users.user_hash", ondelete="CASCADE"),
        nullable=False,
    )

    provider_hash: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("providers.provider_hash", ondelete="CASCADE"),
        nullable=True,
        comment="Provider that owns this subscription. NULL for user-owned subscriptions.",
    )

    description: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Optional description of subscription purpose"
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="subscriptions")
    provider: Mapped[Provider | None] = relationship(
        "Provider",
        back_populates="subscriptions",
        lazy="raise",
    )
    sources: Mapped[list[Source]] = relationship(
        "Source",
        back_populates="subscription",
        cascade="all, delete-orphan",
        order_by="Source.order_index, Source.created_at",
        lazy="raise",
    )
    config_comments: Mapped[list[ConfigComment]] = relationship(
        "ConfigComment",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Subscription token={self.token!r} name={self.name!r}>"
