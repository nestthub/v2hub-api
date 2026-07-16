from __future__ import annotations
from typing import List, Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import TimestampMixin, Base

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
        UniqueConstraint(
            "user_hash",
            "name",
            name="uq_subscription_user_name"
        ),
        Index("ix_subscriptions_user_hash", "user_hash"),
    )
    
    token: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Unique public identifier for subscription"
    )
    name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="User-defined name for subscription"
    )
    user_hash: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("users.user_hash", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="Optional description of subscription purpose"
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="subscriptions"
    )
    sources: Mapped[List["Source"]] = relationship(
        "Source",
        back_populates="subscription",
        cascade="all, delete-orphan",
        order_by="Source.order_index, Source.created_at",
        lazy="raise",
    )
    config_comments: Mapped[List["ConfigComment"]] = relationship(
        "ConfigComment",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Subscription token={self.token!r} name={self.name!r}>"
