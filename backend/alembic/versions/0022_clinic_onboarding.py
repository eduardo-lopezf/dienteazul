"""core — the welcome a new clinic's holder goes through.

``onboarding_pending`` marks a clinic the control plane created whose
holder has not yet reviewed it and accepted the privacy agreement;
``privacy_accepted_at`` is when they did. False for every clinic that
exists: nobody is sent back through a welcome.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clinics",
        sa.Column("onboarding_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "clinics", sa.Column("privacy_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clinics", "privacy_accepted_at")
    op.drop_column("clinics", "onboarding_pending")
