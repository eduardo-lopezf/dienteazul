"""inventory — implant traceability (layer 4).

The one table in this module that holds patient data. ``patient_id`` and
``professional_id`` carry **no foreign key**, for two reasons that both
matter: the trace has to survive the Patients App being switched off
(ADR 0037), and it has to survive the patient row being erased — which
is the point, since this record is the one that cannot be deleted on
request (ADR 0026, ``privacy.py``).

``movement_id`` does carry one: the trace and the ledger line that took
the device off the shelf are written together and must stay together
(ADR 0065).

Revision ID: inv_0003
Revises: inv_0002
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "inv_0003"
down_revision: str | None = "inv_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inv_implant_traces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("lot_id", sa.UUID(), nullable=False),
        sa.Column("movement_id", sa.UUID(), nullable=False),
        sa.Column("placed_on", sa.Date(), nullable=False),
        sa.Column("tooth_number", sa.Integer(), nullable=True),
        sa.Column("serial_number", sa.String(length=80), nullable=True),
        sa.Column("professional_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["inv_items.id"]),
        sa.ForeignKeyConstraint(["lot_id"], ["inv_lots.id"]),
        sa.ForeignKeyConstraint(["movement_id"], ["inv_movements.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inv_implant_traces_clinic_id"), "inv_implant_traces", ["clinic_id"])
    op.create_index("idx_inv_trace_clinic_lot", "inv_implant_traces", ["clinic_id", "lot_id"])
    op.create_index(
        "idx_inv_trace_clinic_patient", "inv_implant_traces", ["clinic_id", "patient_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_inv_trace_clinic_patient", table_name="inv_implant_traces")
    op.drop_index("idx_inv_trace_clinic_lot", table_name="inv_implant_traces")
    op.drop_index(op.f("ix_inv_implant_traces_clinic_id"), table_name="inv_implant_traces")
    op.drop_table("inv_implant_traces")
