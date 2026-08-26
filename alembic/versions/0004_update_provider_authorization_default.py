"""Add PENDING to provider authorization status enum, default to PENDING

The `providerauthorizationstatus` Postgres enum was created (0002) with
only APPROVED/REVOKED, even though the Python-side
`ProviderAuthorizationStatus` enum has included PENDING since before
this migration. New rows also used to default to APPROVED at the
database level -- meaning any code path that inserted a
provider_authorizations row without specifying a status (relying on the
column default) silently created an already-approved authorization
instead of one still awaiting confirmation. See
`ProviderAuthorizationService.add_authorization` for the application-level
fix that made this explicit; this migration brings the schema itself in
line with the intended PENDING default.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_NAME = "providerauthorizationstatus"


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE cannot run inside the transaction Alembic
    # normally wraps migrations in (PostgreSQL restriction), so this
    # statement must be executed with autocommit.
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS 'PENDING' BEFORE 'APPROVED'")

    # Existing APPROVED-by-default rows are untouched; only the
    # column's default for *future* inserts changes. Any row created
    # via the ORM without an explicit status will now start PENDING.
    op.alter_column(
        "provider_authorizations",
        "status",
        existing_type=sa.Enum("PENDING", "APPROVED", "REVOKED", name=ENUM_NAME),
        server_default="PENDING",
    )


def downgrade() -> None:
    """Downgrade schema.

    PostgreSQL does not support removing a value from an enum type, so
    this only reverts the column default back to APPROVED. Any rows
    that ended up PENDING as a result of the changed default are left
    as-is -- there is no way to distinguish them from rows that were
    always PENDING.
    """
    op.alter_column(
        "provider_authorizations",
        "status",
        existing_type=sa.Enum("PENDING", "APPROVED", "REVOKED", name=ENUM_NAME),
        server_default="APPROVED",
    )
