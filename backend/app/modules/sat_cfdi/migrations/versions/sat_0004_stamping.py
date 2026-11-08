"""sat_cfdi module — receivers' fiscal profiles and what stamping needs.

Revision ID: sat_0004
Revises: sat_0003
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "sat_0004"
down_revision: str | None = "sat_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sat_receivers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("rfc", sa.String(length=13), nullable=False),
        sa.Column("tax_regime", sa.String(length=3), nullable=False),
        sa.Column("tax_zip_code", sa.String(length=5), nullable=False),
        sa.Column("cfdi_use", sa.String(length=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "rfc", name="uq_sat_receivers_rfc"),
    )
    op.create_index(op.f("ix_sat_receivers_clinic_id"), "sat_receivers", ["clinic_id"])

    op.add_column("sat_settings", sa.Column("product_code", sa.String(length=8), nullable=True))
    op.add_column(
        "sat_settings",
        sa.Column("unit_code", sa.String(length=3), nullable=False, server_default="E48"),
    )
    op.add_column(
        "sat_settings",
        sa.Column("stamp_delay_minutes", sa.Integer(), nullable=False, server_default="30"),
    )

    for name, column in (
        ("next_attempt_at", sa.DateTime(timezone=True)),
        ("cfdi_date", sa.String(length=19)),
        ("payment_method", sa.String(length=3)),
        ("payment_form", sa.String(length=2)),
        ("pac_id", sa.String(length=64)),
        ("xml", sa.Text()),
        ("stamped_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("sat_cfdi", sa.Column(name, column, nullable=True))


def downgrade() -> None:
    for name in (
        "stamped_at",
        "xml",
        "pac_id",
        "payment_form",
        "payment_method",
        "cfdi_date",
        "next_attempt_at",
    ):
        op.drop_column("sat_cfdi", name)
    op.drop_column("sat_settings", "stamp_delay_minutes")
    op.drop_column("sat_settings", "unit_code")
    op.drop_column("sat_settings", "product_code")
    op.drop_index(op.f("ix_sat_receivers_clinic_id"), table_name="sat_receivers")
    op.drop_table("sat_receivers")
