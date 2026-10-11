"""core — what each account tier is allowed.

How many users a clinic of a tier may add besides its holder, and how
much disk its files may take. Empty on purpose: a tier with no row has
no limit, which is every tier of an installation nobody set limits on.
The control plane fills it in (``PUT /api/v1/ops/limits``).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tier_limits",
        sa.Column("tier", sa.String(20), primary_key=True),
        sa.Column("extra_users", sa.Integer(), nullable=True),
        sa.Column("storage_mb", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tier_limits")
