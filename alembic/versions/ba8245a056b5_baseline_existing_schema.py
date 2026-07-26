"""baseline: existing schema (no-op placeholder)

This revision represents the database schema as it already existed in
production before Alembic history was tracked in this repository. The
actual migrations that produced this schema were never committed to
version control, so this is a no-op placeholder that anchors the known
production revision id (read from the `alembic_version` table) as the
root of the migration chain.

Do NOT run this against a fresh/empty database expecting it to create
the schema — it does nothing. For a fresh install, either restore from
a production dump or use `Base.metadata.create_all` once, then
`alembic stamp head`.

Revision ID: ba8245a056b5
Revises:
Create Date: 2026-07-16 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ba8245a056b5"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: schema already exists in production as of this baseline."""
    pass


def downgrade() -> None:
    """No-op: this is the baseline, nothing to revert to."""
    pass
