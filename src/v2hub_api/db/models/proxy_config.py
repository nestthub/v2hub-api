from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.db.models import Base, TimestampMixin

if TYPE_CHECKING:
    from . import ConfigComment, Source

# ═══════════════════════════════════════════════════════════════════════════
# Proxy Configuration Storage
# ═══════════════════════════════════════════════════════════════════════════


class ProxyConfig(TimestampMixin, Base):
    """
    Normalized proxy configuration without comments.

    Stores the actual proxy configuration (vless://, vmess://, etc.) without
    the fragment (#comment) part. This allows multiple subscriptions to
    reference the same config with different comments.
    """

    __tablename__ = "proxy_configs"

    config_hash: Mapped[str] = mapped_column(
        String(32), primary_key=True, comment="Blake2b hash of normalized config (without fragment)"
    )
    config_data: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Proxy configuration URI without fragment"
    )
    protocol: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        comment="Proxy protocol (vless, vmess, trojan, ss, etc.)",
    )

    # Relationships
    sources: Mapped[list[Source]] = relationship(
        "Source",
        back_populates="proxy_config",
    )
    config_comments: Mapped[list[ConfigComment]] = relationship(
        "ConfigComment",
        back_populates="proxy_config",
    )

    def __repr__(self) -> str:
        return f"<ProxyConfig hash={self.config_hash!r} protocol={self.protocol!r}>"
