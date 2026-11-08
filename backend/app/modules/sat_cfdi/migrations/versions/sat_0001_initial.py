"""sat_cfdi module — initial schema.

`sat_cfdi` carries a foreign key to `invoices.id`, so billing migrates
first. The ordering is declared with `depends_on` rather than by hanging
`down_revision` off billing's head (issue #56, ADR 0002).

Revision ID: sat_0001
Revises: 0001
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "sat_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("sat_cfdi",)
depends_on: str | Sequence[str] | None = "bil_0001"


def upgrade() -> None:
    op.create_table(
        "sat_cfdi",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=1), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("related_cfdi_id", sa.UUID(), nullable=True),
        sa.Column("uuid", sa.String(length=36), nullable=True),
        sa.Column("cancel_reason", sa.String(length=2), nullable=True),
        sa.Column("substitute_cfdi_id", sa.UUID(), nullable=True),
        sa.Column("cancel_requested_by", sa.UUID(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('I', 'E', 'P')", name="ck_sat_cfdi_kind"),
        sa.CheckConstraint(
            "state IN ('pending', 'stamped', 'rejected', 'cancel_requested', 'cancelled')",
            name="ck_sat_cfdi_state",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["related_cfdi_id"], ["sat_cfdi.id"]),
        sa.ForeignKeyConstraint(["substitute_cfdi_id"], ["sat_cfdi.id"]),
        sa.ForeignKeyConstraint(["cancel_requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(op.f("ix_sat_cfdi_clinic_id"), "sat_cfdi", ["clinic_id"])
    op.create_index(op.f("ix_sat_cfdi_invoice_id"), "sat_cfdi", ["invoice_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sat_cfdi_invoice_id"), table_name="sat_cfdi")
    op.drop_index(op.f("ix_sat_cfdi_clinic_id"), table_name="sat_cfdi")
    op.drop_table("sat_cfdi")
