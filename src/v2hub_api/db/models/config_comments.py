from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.core.constants import COMMENT_MAX_LENGTH, HASH_LENGTH, SUBSCRIPTION_TOKEN_LENGTH
from v2hub_api.db.models import Base, TimestampMixin

if TYPE_CHECKING:
    from . import ProxyConfig, Subscription

# ═══════════════════════════════════════════════════════════════════════════
# Config Comments
# ═══════════════════════════════════════════════════════════════════════════


class ConfigComment(TimestampMixin, Base):
    """
    Custom comments for proxy configs within specific subscriptions.

    This table implements the requested feature: storing comments separately
    from configurations. When a config is resolved for a specific subscription,
    the comment from this table is appended as a fragment (#comment).

    This allows:
    - Same config in multiple subscriptions with different comments
    - Updating comments without changing the config hash
    - Preserving original config data integrity
    """

    __tablename__ = "config_comments"
    __table_args__ = (
        UniqueConstraint("subscription_token", "config_hash", name="uq_config_comment_sub_config"),
        Index("ix_config_comments_subscription", "subscription_token"),
        Index("ix_config_comments_config", "config_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_token: Mapped[str] = mapped_column(
        String(SUBSCRIPTION_TOKEN_LENGTH),
        ForeignKey("subscriptions.token", ondelete="CASCADE"),
        nullable=False,
        comment="Subscription this comment belongs to",
    )
    config_hash: Mapped[str] = mapped_column(
        String(HASH_LENGTH),
        ForeignKey("proxy_configs.config_hash", ondelete="CASCADE"),
        nullable=False,
        comment="Config this comment applies to",
    )
    comment: Mapped[str] = mapped_column(
        String(COMMENT_MAX_LENGTH),
        nullable=False,
        comment="Comment text to append after # in config",
    )

    # Relationships
    subscription: Mapped[Subscription] = relationship(
        "Subscription", back_populates="config_comments"
    )
    proxy_config: Mapped[ProxyConfig] = relationship(
        "ProxyConfig", back_populates="config_comments"
    )

    def __repr__(self) -> str:
        return (
            f"<ConfigComment sub={self.subscription_token!r} "
            f"config={self.config_hash[:8]!r} comment={self.comment!r}>"
        )
