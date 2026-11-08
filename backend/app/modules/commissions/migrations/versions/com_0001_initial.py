"""commissions module — initial schema.

`commission_agreements` carries a foreign key to `professionals.id`, so
that module migrates first. The ordering is declared with `depends_on`
rather than by hanging `down_revision` off the professionals head, which
would merge the branches (issue #56, ADR 0002).

Revision ID: com_0001
Revises: 0001
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "com_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("commissions",)
depends_on: str | Sequence[str] | None = ("professionals",)


def upgrade() -> None:
    op.create_table(
        "commission_agreements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("professional_id", sa.UUID(), nullable=False),
        sa.Column("basis", sa.String(length=10), nullable=False),
        sa.Column("default_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "default_percent >= 0 AND default_percent <= 100",
            name="ck_commission_agreement_percent_range",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["professional_id"], ["professionals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "professional_id", name="uq_commission_agreement"),
    )
    op.create_index(
        op.f("ix_commission_agreements_clinic_id"), "commission_agreements", ["clinic_id"]
    )
    op.create_index(
        op.f("ix_commission_agreements_professional_id"),
        "commission_agreements",
        ["professional_id"],
    )

    op.create_table(
        "commission_rates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("agreement_id", sa.UUID(), nullable=False),
        sa.Column("catalog_item_id", sa.UUID(), nullable=False),
        sa.Column("percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "percent >= 0 AND percent <= 100", name="ck_commission_rate_percent_range"
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["agreement_id"], ["commission_agreements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agreement_id", "catalog_item_id", name="uq_commission_rate_item"),
    )
    op.create_index(op.f("ix_commission_rates_clinic_id"), "commission_rates", ["clinic_id"])
    op.create_index(op.f("ix_commission_rates_agreement_id"), "commission_rates", ["agreement_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_commission_rates_agreement_id"), table_name="commission_rates")
    op.drop_index(op.f("ix_commission_rates_clinic_id"), table_name="commission_rates")
    op.drop_table("commission_rates")
    op.drop_index(
        op.f("ix_commission_agreements_professional_id"), table_name="commission_agreements"
    )
    op.drop_index(op.f("ix_commission_agreements_clinic_id"), table_name="commission_agreements")
    op.drop_table("commission_agreements")
