from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from v2hub_api.core.enums import ProviderAuthorizationStatus

from . import Base, TimestampMixin

if TYPE_CHECKING:
    from . import Provider, User


class ProviderAuthorization(TimestampMixin, Base):
    __tablename__ = "provider_authorizations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "provider_hash",
            "user_hash",
            name="pk_provider_authorizations",
        ),
        Index(
            "ix_provider_authorizations_user_hash",
            "user_hash",
        ),
    )

    provider_hash: Mapped[str] = mapped_column(
        ForeignKey("providers.provider_hash", ondelete="CASCADE"),
    )

    user_hash: Mapped[str] = mapped_column(
        ForeignKey("users.user_hash", ondelete="CASCADE"),
    )

    status: Mapped[ProviderAuthorizationStatus] = mapped_column(
        Enum(ProviderAuthorizationStatus),
        default=ProviderAuthorizationStatus.APPROVED,
        nullable=False,
    )

    # Relationships
    provider: Mapped[Provider] = relationship(
        "Provider",
        back_populates="authorizations",
        lazy="raise",
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="provider_authorizations",
        lazy="raise",
    )
