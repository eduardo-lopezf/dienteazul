"""The regulation a consent letter named when it was signed.

Revision ID: con_0003
Revises: con_0002
Create Date: 2026-10-13

Letters signed before this named none, and stay that way.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "con_0003"
down_revision: str | None = "con_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("consents_consent", sa.Column("regulation", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("consents_consent", "regulation")
