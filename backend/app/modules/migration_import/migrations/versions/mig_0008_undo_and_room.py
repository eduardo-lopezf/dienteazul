"""migration_import — an import can be undone, and says the space it needs.

``migration_import_created_rows`` is the ledger of every row an import
inserted, recorded as it inserts them: undoing removes exactly those
(and what hangs from them), never a row the import only linked to. Jobs
run before this ledger existed cannot be undone (``tracks_created``).

``expected_storage_bytes`` is what the file's documents will take in the
clinic's storage, worked out at preview and checked before running.

Revision ID: mig_0008
Revises: mig_0007
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "mig_0008"
down_revision: str | None = "mig_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOBS = "migration_import_jobs"
_STATUS = "ck_migration_import_job_status"
_BEFORE = (
    "'mapping','uploaded','validating','validated','previewing','executing','completed','failed'"
)


def upgrade() -> None:
    op.create_table(
        "migration_import_created_rows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{_JOBS}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_name", sa.String(80), nullable=False),
        sa.Column("pk_column", sa.String(60), nullable=False),
        sa.Column("row_key", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_migration_import_created_rows_job_id", "migration_import_created_rows", ["job_id"]
    )
    op.add_column(
        _JOBS,
        sa.Column("tracks_created", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(_JOBS, sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        _JOBS,
        sa.Column(
            "undone_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
    )
    op.add_column(_JOBS, sa.Column("undo_error", sa.Text(), nullable=True))
    op.add_column(_JOBS, sa.Column("expected_storage_bytes", sa.BigInteger(), nullable=True))
    op.drop_constraint(_STATUS, _JOBS, type_="check")
    op.create_check_constraint(_STATUS, _JOBS, f"status IN ({_BEFORE},'undoing','undone')")


def downgrade() -> None:
    op.execute(
        "UPDATE migration_import_jobs SET status = 'completed' WHERE status IN ('undoing', 'undone')"
    )
    op.drop_constraint(_STATUS, _JOBS, type_="check")
    op.create_check_constraint(_STATUS, _JOBS, f"status IN ({_BEFORE})")
    for column in (
        "expected_storage_bytes",
        "undo_error",
        "undone_by",
        "undone_at",
        "tracks_created",
    ):
        op.drop_column(_JOBS, column)
    op.drop_index(
        "ix_migration_import_created_rows_job_id", table_name="migration_import_created_rows"
    )
    op.drop_table("migration_import_created_rows")
