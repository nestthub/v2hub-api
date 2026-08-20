from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.core.constants import HASH_LENGTH, SUBSCRIPTION_TOKEN_LENGTH, URL_MAX_LENGTH
from v2hub_api.db.models import Base, TimestampMixin

if TYPE_CHECKING:
    from . import ProxyConfig, Subscription

# ═══════════════════════════════════════════════════════════════════════════
# Source Management
# ═══════════════════════════════════════════════════════════════════════════


class Source(TimestampMixin, Base):
    """
    Single entry in a subscription.

    Can be one of three types:
    - CONFIG: Direct reference to a ProxyConfig
    - EXTERNAL_URL: HTTPS URL to third-party subscription
    - INTERNAL_TOKEN: Token of another subscription (same user only)
    """

    __tablename__ = "sources"
    __table_args__ = (
        PrimaryKeyConstraint("subscription_token", "id"),
        Index("ix_sources_subscription_token", "subscription_token"),
        Index("ix_sources_type", "source_type"),
        Index("ix_sources_config_hash", "config_hash"),
    )

    subscription_token: Mapped[str] = mapped_column(
        String(SUBSCRIPTION_TOKEN_LENGTH),
        ForeignKey("subscriptions.token", ondelete="CASCADE"),
        nullable=False,
    )

    id: Mapped[str] = mapped_column(
        String(HASH_LENGTH),
        nullable=False,
        comment="Unique identifier for this source within subscription",
    )
    source_type: Mapped[str] = mapped_column(
        String(15), nullable=False, comment="Type: CONFIG, EXTERNAL_URL, or INTERNAL_TOKEN"
    )

    # For CONFIG type: references proxy_configs table
    config_hash: Mapped[str | None] = mapped_column(
        String(HASH_LENGTH),
        ForeignKey("proxy_configs.config_hash", ondelete="SET NULL"),
        nullable=True,
        comment="Reference to ProxyConfig (for CONFIG type)",
    )

    # For INTERNAL_TOKEN types: stores the token
    internal_token: Mapped[str | None] = mapped_column(
        String(SUBSCRIPTION_TOKEN_LENGTH), nullable=True, comment="Token for INTERNAL_TOKEN"
    )

    # For EXTERNAL_URL types: stores the URL
    external_url: Mapped[str | None] = mapped_column(
        String(URL_MAX_LENGTH), nullable=True, comment="URL for EXTERNAL_URL"
    )

    is_hidden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the source is hidden from end users",
    )

    max_depth: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
        comment="Maximum nesting depth for source visibility propagation (0-3)",
    )

    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="User-defined ordering within subscription",
    )

    # Relationships
    subscription: Mapped[Subscription] = relationship(
        "Subscription", back_populates="sources", lazy="raise"
    )
    proxy_config: Mapped[ProxyConfig | None] = relationship(
        "ProxyConfig", back_populates="sources", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<Source id={self.id!r} type={self.source_type!r}>"
