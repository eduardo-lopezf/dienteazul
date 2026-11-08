"""sat_cfdi module — where Facturama holds each CSD.

Revision ID: sat_0003
Revises: sat_0002
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "sat_0003"
down_revision: str | None = "sat_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sat_certificates",
        sa.Column("registered_sandbox_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sat_certificates",
        sa.Column("registered_production_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("sat_certificates", sa.Column("registration_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sat_certificates", "registration_error")
    op.drop_column("sat_certificates", "registered_production_at")
    op.drop_column("sat_certificates", "registered_sandbox_at")
