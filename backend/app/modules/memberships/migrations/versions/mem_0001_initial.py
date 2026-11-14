"""memberships module — initial schema.

`patient_memberships` carries a foreign key to `patients.id`, so that
module migrates first, declared with `depends_on` (issue #56, ADR 0002).

Revision ID: mem_0001
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "mem_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("memberships",)
depends_on: str | Sequence[str] | None = ("pat_0001",)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "membership_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("fee", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("general_discount_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("fee >= 0", name="ck_membership_plan_fee_nonneg"),
        sa.CheckConstraint("period IN ('monthly', 'annual')", name="ck_membership_plan_period"),
        sa.CheckConstraint(
            "general_discount_percent >= 0 AND general_discount_percent <= 100",
            name="ck_membership_plan_discount_range",
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_membership_plan_status"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_membership_plans_clinic_id"), "membership_plans", ["clinic_id"])

    op.create_table(
        "membership_plan_benefits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("catalog_item_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("discount_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "(kind = 'included' AND quantity >= 1 AND discount_percent IS NULL) "
            "OR (kind = 'discount' AND quantity IS NULL "
            "AND discount_percent >= 0 AND discount_percent <= 100)",
            name="ck_membership_benefit_kind",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["membership_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "catalog_item_id", name="uq_membership_benefit_item"),
    )
    op.create_index(
        op.f("ix_membership_plan_benefits_clinic_id"), "membership_plan_benefits", ["clinic_id"]
    )
    op.create_index(
        op.f("ix_membership_plan_benefits_plan_id"), "membership_plan_benefits", ["plan_id"]
    )

    op.create_table(
        "patient_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled')", name="ck_patient_membership_status"
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["membership_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patient_memberships_clinic_id"), "patient_memberships", ["clinic_id"])
    op.create_index(
        op.f("ix_patient_memberships_patient_id"), "patient_memberships", ["patient_id"]
    )
    op.create_index(op.f("ix_patient_memberships_plan_id"), "patient_memberships", ["plan_id"])
    op.create_index(
        "uq_patient_membership_active",
        "patient_memberships",
        ["clinic_id", "patient_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "membership_periods",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("refunded_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_membership_period_range"),
        sa.CheckConstraint("status IN ('paid', 'refunded')", name="ck_membership_period_status"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["patient_memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_membership_periods_clinic_id"), "membership_periods", ["clinic_id"])
    op.create_index(
        op.f("ix_membership_periods_membership_id"), "membership_periods", ["membership_id"]
    )
    op.create_index(op.f("ix_membership_periods_payment_id"), "membership_periods", ["payment_id"])

    op.create_table(
        "membership_benefit_usages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("catalog_item_id", sa.UUID(), nullable=False),
        sa.Column("treatment_id", sa.UUID(), nullable=False),
        sa.Column("cycle_start", sa.Date(), nullable=False),
        sa.Column("used_on", sa.Date(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["patient_memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "treatment_id", name="uq_membership_usage_treatment"),
    )
    op.create_index(
        op.f("ix_membership_benefit_usages_clinic_id"), "membership_benefit_usages", ["clinic_id"]
    )
    op.create_index(
        op.f("ix_membership_benefit_usages_membership_id"),
        "membership_benefit_usages",
        ["membership_id"],
    )


def downgrade() -> None:
    op.drop_table("membership_benefit_usages")
    op.drop_table("membership_periods")
    op.drop_index("uq_patient_membership_active", table_name="patient_memberships")
    op.drop_table("patient_memberships")
    op.drop_table("membership_plan_benefits")
    op.drop_table("membership_plans")
