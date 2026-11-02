"""inventory — materials per treatment (layer 3).

``catalog_item_id`` deliberately carries no foreign key into
``treatment_catalog_items``: a constraint there would make the inventory
unusable whenever the Treatments App is disabled, which is the one thing
this module refuses to be (ADR 0037). The link is a contract, not a
join (ADR 0039).

Revision ID: inv_0002
Revises: inv_0001
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "inv_0002"
down_revision: str | None = "inv_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inv_treatment_materials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("catalog_item_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("quantity_base", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity_base > 0", name="ck_inv_material_quantity_positive"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["inv_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clinic_id", "catalog_item_id", "item_id", name="uq_inv_material_treatment_item"
        ),
    )
    op.create_index(
        op.f("ix_inv_treatment_materials_clinic_id"), "inv_treatment_materials", ["clinic_id"]
    )
    op.create_index(
        "idx_inv_material_clinic_treatment",
        "inv_treatment_materials",
        ["clinic_id", "catalog_item_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_inv_material_clinic_treatment", table_name="inv_treatment_materials")
    op.drop_index(
        op.f("ix_inv_treatment_materials_clinic_id"), table_name="inv_treatment_materials"
    )
    op.drop_table("inv_treatment_materials")
