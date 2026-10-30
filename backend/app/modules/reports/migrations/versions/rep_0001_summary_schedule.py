"""reports: the one table this module owns.

``reports_summary_schedule`` — one row per clinic, saying whether its
one-page summary goes out on its own and to whom. Every figure the
module reports is still computed on demand from other modules' tables;
this is a standing order, not a cache.

Lives on its own Alembic branch (``reports``) per ADR 0002.

Revision ID: rep_0001
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "rep_0001"
# Chain off the foundational core revision so the branch has a base on a
# clean database, exactly as the other module branches do.
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("reports",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports_summary_schedule",
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cadence", sa.String(length=10), nullable=False, server_default="monthly"),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("last_sent_for", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("clinic_id"),
    )


def downgrade() -> None:
    op.drop_table("reports_summary_schedule")
