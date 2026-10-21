"""Eruption status per tooth, and a clinic's own eruption chronology.

`tooth_records.eruption_status` says where a tooth is in its life — not yet
erupted, coming through, in the mouth, fallen out (a primary tooth), absent
from birth, or retained in the bone. NULL means "not said" and the chart goes
by the eruption chronology, so existing rows need no backfill.

`odontogram_clinic_settings` holds a clinic's chronology when it sets one;
with no row the default applies.

Revision ID: odo_0004
Revises: odo_0003
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "odo_0004"
down_revision: str | None = "odo_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tooth_records", sa.Column("eruption_status", sa.String(length=24)))
    op.create_check_constraint(
        "ck_tooth_records_eruption_status",
        "tooth_records",
        "eruption_status IS NULL OR eruption_status IN ('unerupted', 'erupting', "
        "'erupted', 'exfoliated', 'congenitally_missing', 'impacted')",
    )
    op.create_table(
        "odontogram_clinic_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("eruption_ages", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_odontogram_clinic_settings_clinic_id",
        "odontogram_clinic_settings",
        ["clinic_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_odontogram_clinic_settings_clinic_id", table_name="odontogram_clinic_settings"
    )
    op.drop_table("odontogram_clinic_settings")
    op.drop_constraint("ck_tooth_records_eruption_status", "tooth_records", type_="check")
    op.drop_column("tooth_records", "eruption_status")
