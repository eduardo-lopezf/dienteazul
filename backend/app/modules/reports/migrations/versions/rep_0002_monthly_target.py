"""reports: monthly targets.

``reports_monthly_target`` — what a clinic said it wanted from a month,
one row per month, every goal optional. The actuals are still computed
on demand; only the goal is stored, because a goal is a decision and
nothing can derive it.

Revision ID: rep_0002
Revises: rep_0001
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "rep_0002"
down_revision: str | None = "rep_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports_monthly_target",
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("collected_target", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("production_target", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("new_patients_target", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("clinic_id", "month"),
    )


def downgrade() -> None:
    op.drop_table("reports_monthly_target")
