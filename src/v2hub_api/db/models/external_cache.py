from __future__ import annotations

from datetime import datetime  # noqa: TC003

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from v2hub_api.core.constants import HASH_LENGTH, URL_MAX_LENGTH
from v2hub_api.db.models import Base, TimestampMixin

# ═══════════════════════════════════════════════════════════════════════════
# External Subscription Cache
# ═══════════════════════════════════════════════════════════════════════════


class ExternalCache(TimestampMixin, Base):
    """
    Persistent (L2) cache for external subscription URLs.

    Caching strategy:
    1. Celery worker refreshes periodically (e.g., every 10 minutes)
    2. Fresh data goes to both Redis (L1) and this table (L2)
    3. On cache miss in Redis, read from here and restore to Redis
    4. First-time requests fetch synchronously, then cache
    """

    __tablename__ = "external_cache"

    url_hash: Mapped[str] = mapped_column(
        String(HASH_LENGTH), primary_key=True, comment="Blake2b hash of canonical URL"
    )
    url: Mapped[str] = mapped_column(
        String(URL_MAX_LENGTH), nullable=False, comment="Original external subscription URL"
    )

    # Cache content
    raw_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Newline-separated proxy configs (NULL = never fetched)"
    )
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last successful fetch timestamp"
    )

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Last error message if fetch failed"
    )
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="Consecutive error count"
    )

    def __repr__(self) -> str:
        status = "cached" if self.raw_content is not None else "not fetched"
        return f"<ExternalCache url_hash={self.url_hash!r} status={status}>"

    @property
    def has_content(self) -> bool:
        """Check if cache has successfully fetched content."""
        return self.raw_content is not None

    @property
    def config_lines(self) -> list[str]:
        """Get cached configs as a list of strings."""
        if not self.raw_content:
            return []
        return [line for line in self.raw_content.splitlines() if line.strip()]
