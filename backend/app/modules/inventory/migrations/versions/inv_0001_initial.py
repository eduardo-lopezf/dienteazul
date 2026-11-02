"""inventory module — initial schema (articles, locations, lots, ledger, levels).

Hangs off the core chain rather than another module's: the only foreign
keys are ``clinics.id`` and ``users.id``, both core tables, so threading
through a sibling's revisions would buy nothing and cost uninstall safety
(issue #56, ADR 0002).

The unique index on ``inv_stock_levels`` is ``NULLS NOT DISTINCT``
(PostgreSQL 15+). Without it every movement of an article that tracks no
lot would insert a new level row — Postgres treats two NULLs as different
values — and one article's stock would be scattered across one row per
movement with every constraint still satisfied.

Revision ID: inv_0001
Revises: 0001
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "inv_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("inventory",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inv_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("base_unit", sa.String(length=20), nullable=False),
        sa.Column(
            "purchase_presentations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("tracks_lots", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reorder_point", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("reorder_quantity", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("cost_per_base_unit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="active"),
        sa.Column("low_stock_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reorder_point IS NULL OR reorder_point >= 0",
            name="ck_inv_item_reorder_point_non_negative",
        ),
        sa.CheckConstraint(
            "reorder_quantity IS NULL OR reorder_quantity > 0",
            name="ck_inv_item_reorder_quantity_positive",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "code", name="uq_inv_item_clinic_code"),
    )
    op.create_index(op.f("ix_inv_items_clinic_id"), "inv_items", ["clinic_id"])
    op.create_index("idx_inv_item_clinic_status", "inv_items", ["clinic_id", "status"])

    op.create_table(
        "inv_locations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        # No FK to `cabinets`: a constraint there would make the inventory
        # unusable whenever the Agenda App is off (ADR 0037).
        sa.Column("cabinet_id", sa.UUID(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "name", name="uq_inv_location_clinic_name"),
    )
    op.create_index(op.f("ix_inv_locations_clinic_id"), "inv_locations", ["clinic_id"])
    op.create_index("idx_inv_location_clinic_status", "inv_locations", ["clinic_id", "status"])

    op.create_table(
        "inv_lots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("lot_code", sa.String(length=60), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("expiry_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["inv_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "item_id", "lot_code", name="uq_inv_lot_clinic_item_code"),
    )
    op.create_index(op.f("ix_inv_lots_clinic_id"), "inv_lots", ["clinic_id"])
    op.create_index(op.f("ix_inv_lots_item_id"), "inv_lots", ["item_id"])
    op.create_index("idx_inv_lot_clinic_expiry", "inv_lots", ["clinic_id", "expires_on"])

    op.create_table(
        "inv_movements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column("lot_id", sa.UUID(), nullable=True),
        sa.Column("quantity_base", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("performed_by", sa.UUID(), nullable=True),
        sa.Column("cost_per_base_unit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity_base <> 0", name="ck_inv_movement_quantity_non_zero"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["inv_items.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["inv_locations.id"]),
        sa.ForeignKeyConstraint(["lot_id"], ["inv_lots.id"]),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inv_movements_clinic_id"), "inv_movements", ["clinic_id"])
    op.create_index(
        "idx_inv_movement_clinic_item", "inv_movements", ["clinic_id", "item_id", "created_at"]
    )
    op.create_index("idx_inv_movement_clinic_created", "inv_movements", ["clinic_id", "created_at"])

    op.create_table(
        "inv_stock_levels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column("lot_id", sa.UUID(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["inv_items.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["inv_locations.id"]),
        sa.ForeignKeyConstraint(["lot_id"], ["inv_lots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "location_id",
            "lot_id",
            name="uq_inv_stock_level_item_location_lot",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_inv_stock_levels_clinic_id"), "inv_stock_levels", ["clinic_id"])
    op.create_index("idx_inv_stock_level_clinic_item", "inv_stock_levels", ["clinic_id", "item_id"])


def downgrade() -> None:
    op.drop_index("idx_inv_stock_level_clinic_item", table_name="inv_stock_levels")
    op.drop_index(op.f("ix_inv_stock_levels_clinic_id"), table_name="inv_stock_levels")
    op.drop_table("inv_stock_levels")
    op.drop_index("idx_inv_movement_clinic_created", table_name="inv_movements")
    op.drop_index("idx_inv_movement_clinic_item", table_name="inv_movements")
    op.drop_index(op.f("ix_inv_movements_clinic_id"), table_name="inv_movements")
    op.drop_table("inv_movements")
    op.drop_index("idx_inv_lot_clinic_expiry", table_name="inv_lots")
    op.drop_index(op.f("ix_inv_lots_item_id"), table_name="inv_lots")
    op.drop_index(op.f("ix_inv_lots_clinic_id"), table_name="inv_lots")
    op.drop_table("inv_lots")
    op.drop_index("idx_inv_location_clinic_status", table_name="inv_locations")
    op.drop_index(op.f("ix_inv_locations_clinic_id"), table_name="inv_locations")
    op.drop_table("inv_locations")
    op.drop_index("idx_inv_item_clinic_status", table_name="inv_items")
    op.drop_index(op.f("ix_inv_items_clinic_id"), table_name="inv_items")
    op.drop_table("inv_items")
