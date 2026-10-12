"""core — when a clinic's holder declined the privacy agreement.

Declining deactivates the clinic, and so does the operator: this is what
tells the two apart afterwards. Cleared when the agreement is accepted.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clinics", sa.Column("privacy_declined_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clinics", "privacy_declined_at")
