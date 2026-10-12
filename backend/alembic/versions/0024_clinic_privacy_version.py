"""core — which version of the privacy agreement a clinic's holder accepted.

The agreement's text lives in the frontend and changes; a date alone does
not say which text was on the screen. ``NULL`` for a clinic that accepted
before versions were kept, and for one that has not accepted.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("privacy_accepted_version", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("clinics", "privacy_accepted_version")
