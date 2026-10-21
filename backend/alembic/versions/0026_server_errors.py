"""core — the requests that ended in a server error.

One row per unhandled exception, kept thirty days, so the operator's
panel can show where "Error del servidor" came from: the route, the
exception, its message without the values it quoted, the chain of calls,
and the request, clinic and user identifiers.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("error_type", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("frames", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("clinic_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_server_errors_occurred_at", "server_errors", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_server_errors_occurred_at", table_name="server_errors")
    op.drop_table("server_errors")
