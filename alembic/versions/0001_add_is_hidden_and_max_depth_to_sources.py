"""add is_hidden and max_depth to sources

Revision ID: 0001
Revises: ba8245a056b5
Create Date: 2026-07-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = "ba8245a056b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sources",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether the source is hidden from end users",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "max_depth",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
            comment="Maximum nesting depth for source visibility propagation (0-3)",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sources", "max_depth")
    op.drop_column("sources", "is_hidden")
