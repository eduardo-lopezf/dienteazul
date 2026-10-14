"""migration_import — a job can wait for its columns to be assigned.

A spreadsheet upload creates the job in ``mapping`` until the person says
which column is which field and it is converted to a ``.dpm``.

Revision ID: mig_0007
Revises: mig_0006
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "mig_0007"
down_revision: str | None = "mig_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "migration_import_jobs"
_NAME = "ck_migration_import_job_status"
_BEFORE = "'uploaded','validating','validated','previewing','executing','completed','failed'"


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, f"status IN ('mapping',{_BEFORE})")


def downgrade() -> None:
    # A job still waiting for its columns cannot be kept under the old rule.
    op.execute("UPDATE migration_import_jobs SET status = 'failed' WHERE status = 'mapping'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, f"status IN ({_BEFORE})")
