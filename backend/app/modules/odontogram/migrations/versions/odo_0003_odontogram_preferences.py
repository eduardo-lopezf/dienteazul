"""Which dentition a patient's chart shows.

The chart follows the patient's age by default — deciduous, mixed or
permanent. A clinician may pick one for a patient; that choice is kept here,
one row per patient, and the chart reads it on every device. No row means
"follow the age".

Revision ID: odo_0003
Revises: odo_0002
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "odo_0003"
down_revision: str | None = "odo_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "odontogram_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("patient_id", sa.UUID(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("dentition", sa.String(length=20), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "patient_id", name="uq_odontogram_preference_patient"),
        sa.CheckConstraint(
            "dentition IN ('auto', 'deciduous', 'mixed', 'permanent')",
            name="ck_odontogram_preference_dentition",
        ),
    )
    op.create_index("ix_odontogram_preferences_clinic_id", "odontogram_preferences", ["clinic_id"])


def downgrade() -> None:
    op.drop_index("ix_odontogram_preferences_clinic_id", table_name="odontogram_preferences")
    op.drop_table("odontogram_preferences")
