"""core — a clinic's own limits, over its tier's.

``clinics.limits`` holds what the operator set for this clinic alone:
``{"extra_users": 6}`` overrides that limit and leaves the other to the
tier (``tier_limits``); a key holding ``null`` is "no limit" for this
clinic. ``NULL`` — every clinic that exists — inherits both.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("limits", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("clinics", "limits")
