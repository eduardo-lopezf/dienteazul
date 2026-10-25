"""Persist error codes for migration, export and undo job failures.

Revision ID: mig_0009
Revises: mig_0008
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "mig_0009"
down_revision: str | None = "mig_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "migration_import_jobs", sa.Column("error_code", sa.String(120), nullable=True)
    )
    op.add_column(
        "migration_import_jobs", sa.Column("undo_error_code", sa.String(120), nullable=True)
    )
    op.add_column(
        "migration_import_export_jobs", sa.Column("error_code", sa.String(120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("migration_import_export_jobs", "error_code")
    op.drop_column("migration_import_jobs", "undo_error_code")
    op.drop_column("migration_import_jobs", "error_code")
