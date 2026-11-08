"""sat_cfdi module — each clinic's own Facturama account.

Revision ID: sat_0005
Revises: sat_0004
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "sat_0005"
down_revision: str | None = "sat_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("facturama_sandbox_user", sa.String(length=120)),
    ("facturama_sandbox_password_encrypted", sa.Text()),
    ("facturama_production_user", sa.String(length=120)),
    ("facturama_production_password_encrypted", sa.Text()),
)


def upgrade() -> None:
    for name, column in _COLUMNS:
        op.add_column("sat_settings", sa.Column(name, column, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("sat_settings", name)
