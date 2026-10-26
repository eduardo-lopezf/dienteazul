"""core — server errors move from a table to a log file.

``0026`` kept one row per unhandled exception so the operator's panel
could show where "Error del servidor" came from. They are a log —
written once, read in order, never updated, aged out — and now live in
``<ERROR_LOG_DIR>/errors.log``, one JSON line each, where an operator can
also tail, ship or grep them without a database client (ADR 0060).

Dropping the table discards what it holds. That is the trade the move
makes: the rows are diagnostics for failures already past, the oldest of
them under thirty days, and nothing references them. Keep a copy first if
a current incident is being worked from them.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_server_errors_occurred_at", table_name="server_errors")
    op.drop_table("server_errors")


def downgrade() -> None:
    """Rebuild the table, empty: what it held is not coming back.

    The shape is ``0026``'s, so a deployment that rolls back lands on a
    schema its code recognises.
    """
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
