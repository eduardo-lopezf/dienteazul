"""calendar_feed: one subscription URL per user per clinic.

``token`` is the whole credential, so it carries a unique index: the
public endpoint looks a feed up by it and answers 404 for anything else
(ADR 0061). ``last_access_at`` starts NULL and is written on every poll
— it is what tells the user their subscription is alive.

Its own branch, hanging off the core root: this module has no foreign key
into another module's tables, so nothing orders it against them (issue
#56, ADR 0002).

Revision ID: cal_0001
Revises: 0001 (branch root)
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cal_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("calendar_feed",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_feeds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.UUID(), nullable=False),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_feeds_clinic_id", "calendar_feeds", ["clinic_id"], unique=False)
    op.create_index("ix_calendar_feeds_user_id", "calendar_feeds", ["user_id"], unique=False)
    op.create_index("ix_calendar_feeds_token", "calendar_feeds", ["token"], unique=True)
    op.create_index(
        "uq_calendar_feed_clinic_user", "calendar_feeds", ["clinic_id", "user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_calendar_feed_clinic_user", table_name="calendar_feeds")
    op.drop_index("ix_calendar_feeds_token", table_name="calendar_feeds")
    op.drop_index("ix_calendar_feeds_user_id", table_name="calendar_feeds")
    op.drop_index("ix_calendar_feeds_clinic_id", table_name="calendar_feeds")
    op.drop_table("calendar_feeds")
