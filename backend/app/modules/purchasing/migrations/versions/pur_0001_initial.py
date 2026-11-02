"""purchasing module — initial schema (suppliers, orders, order lines).

``pur_order_lines.item_id`` points at ``inv_items``, so this branch is
declared to depend on the `inventory` one. ``depends_on`` rather than
hanging ``down_revision`` off the inventory head: that would merge the
two branches and drag purchasing into
``alembic downgrade inventory@base`` (issue #56, ADR 0002).

Revision ID: pur_0001
Revises: 0001
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "pur_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("purchasing",)
depends_on: str | Sequence[str] | None = ("inventory",)


def upgrade() -> None:
    op.create_table(
        "pur_suppliers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_id", sa.String(length=30), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "name", name="uq_pur_supplier_clinic_name"),
    )
    op.create_index(op.f("ix_pur_suppliers_clinic_id"), "pur_suppliers", ["clinic_id"])
    op.create_index("idx_pur_supplier_clinic_status", "pur_suppliers", ["clinic_id", "status"])

    op.create_table(
        "pur_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["pur_suppliers.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "number", name="uq_pur_order_clinic_number"),
    )
    op.create_index(op.f("ix_pur_orders_clinic_id"), "pur_orders", ["clinic_id"])
    op.create_index(op.f("ix_pur_orders_supplier_id"), "pur_orders", ["supplier_id"])
    op.create_index(
        "idx_pur_order_clinic_status", "pur_orders", ["clinic_id", "status", "order_date"]
    )

    op.create_table(
        "pur_order_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("quantity_ordered", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "quantity_received",
            sa.Numeric(precision=12, scale=3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity_ordered > 0", name="ck_pur_line_quantity_positive"),
        sa.CheckConstraint("quantity_received >= 0", name="ck_pur_line_received_non_negative"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_pur_line_cost_non_negative"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["pur_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["inv_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pur_order_lines_clinic_id"), "pur_order_lines", ["clinic_id"])
    op.create_index("idx_pur_line_order", "pur_order_lines", ["order_id"])


def downgrade() -> None:
    op.drop_index("idx_pur_line_order", table_name="pur_order_lines")
    op.drop_index(op.f("ix_pur_order_lines_clinic_id"), table_name="pur_order_lines")
    op.drop_table("pur_order_lines")
    op.drop_index("idx_pur_order_clinic_status", table_name="pur_orders")
    op.drop_index(op.f("ix_pur_orders_supplier_id"), table_name="pur_orders")
    op.drop_index(op.f("ix_pur_orders_clinic_id"), table_name="pur_orders")
    op.drop_table("pur_orders")
    op.drop_index("idx_pur_supplier_clinic_status", table_name="pur_suppliers")
    op.drop_index(op.f("ix_pur_suppliers_clinic_id"), table_name="pur_suppliers")
    op.drop_table("pur_suppliers")
