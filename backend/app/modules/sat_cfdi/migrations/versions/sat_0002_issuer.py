"""sat_cfdi module — the issuer's SAT settings and CSD.

Revision ID: sat_0002
Revises: sat_0001
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "sat_0002"
down_revision: str | None = "sat_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sat_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("tax_regime", sa.String(length=3), nullable=True),
        sa.Column("expedition_postal_code", sa.String(length=5), nullable=True),
        sa.Column("environment", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sat_settings_clinic_id"), "sat_settings", ["clinic_id"], unique=True)

    op.create_table(
        "sat_certificates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("cer", sa.LargeBinary(), nullable=False),
        sa.Column("key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("certificate_number", sa.String(length=20), nullable=False),
        sa.Column("rfc", sa.String(length=13), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sat_certificates_clinic_id"), "sat_certificates", ["clinic_id"])
    op.create_index(
        "uq_sat_certificates_one_active",
        "sat_certificates",
        ["clinic_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_sat_certificates_one_active", table_name="sat_certificates")
    op.drop_index(op.f("ix_sat_certificates_clinic_id"), table_name="sat_certificates")
    op.drop_table("sat_certificates")
    op.drop_index(op.f("ix_sat_settings_clinic_id"), table_name="sat_settings")
    op.drop_table("sat_settings")
