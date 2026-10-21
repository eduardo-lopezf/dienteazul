"""core — notices the operator shows to clinics.

A short message — a maintenance window, a new feature — shown discreetly
beside the clinic's name at the top of the workspace, between two dates,
to every clinic or to the ones named. Written by the control plane
(``/api/v1/ops/announcements``), read by each clinic's members
(``GET /api/v1/announcements``).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("message", sa.String(280), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clinic_ids", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('maintenance', 'feature')", name="ck_announcements_kind"),
    )
    op.create_index("ix_announcements_starts_at", "announcements", ["starts_at"])


def downgrade() -> None:
    op.drop_index("ix_announcements_starts_at", table_name="announcements")
    op.drop_table("announcements")
