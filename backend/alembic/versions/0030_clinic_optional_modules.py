"""core — the optional modules a clinic has switched on.

``apps.json`` may mark some modules of an App as ``optional_modules``:
off for every clinic until its administrator switches them on from the
App's settings (ADR 0066). ``clinics.modules`` is the list of those it
switched on. Empty for every clinic that exists: nobody switched any on,
which is what "off by default" means.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("modules", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("clinics", "modules")
