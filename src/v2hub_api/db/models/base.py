"""
Database models for VPN Subscription API.

Architecture:
- User: Stores user authentication data
- Subscription: Represents a named collection of proxy sources
- Source: Individual proxy config, external URL, or internal reference
- ProxyConfig: Normalized proxy configurations (without comments)
- ConfigComment: Maps subscription + config to custom comments
- ExternalCache: Persistent cache for external subscription URLs
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("NOW()"),
    )
