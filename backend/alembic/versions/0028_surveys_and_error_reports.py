"""core — the two things that come back from a clinic to the operator.

A notice can now be a **survey**: ``kind = 'survey'`` with ``options``,
answered from the same discreet banner that shows it
(``PUT /api/v1/announcements/{id}/response``), one row per member in
``announcement_responses``. And a member can file an **error report** in
their own words from the Help drawer (``POST /api/v1/error-reports``),
kept in ``error_reports``. The operator reads both in the control panel's
*Mensajes*, through ``/api/v1/ops``.

Both tables are the clinic's writes and the operator's reads. Neither
holds a patient's record: a survey answer is the index of a choice the
operator wrote, and a report is a staff member's prose about the
software.

Existing notices keep working: ``options`` is nullable and the new check
is satisfied by every row that is not a survey.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- A notice can be a survey ---------------------------------------
    # The column lands before the constraints that talk about it, and the
    # old constraint goes before the kind it forbids can be written.
    op.add_column("announcements", sa.Column("options", postgresql.JSONB(), nullable=True))
    op.drop_constraint("ck_announcements_kind", "announcements", type_="check")
    op.create_check_constraint(
        "ck_announcements_kind",
        "announcements",
        "kind IN ('maintenance', 'feature', 'survey')",
    )
    op.create_check_constraint(
        "ck_announcements_survey_options",
        "announcements",
        "(kind = 'survey') = (options IS NOT NULL)",
    )

    op.create_table(
        "announcement_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # One answer per member per survey: a second click changes it.
        sa.UniqueConstraint("announcement_id", "user_id", name="uq_announcement_responses_user"),
    )
    op.create_index(
        "ix_announcement_responses_announcement_id", "announcement_responses", ["announcement_id"]
    )
    op.create_index("ix_announcement_responses_clinic_id", "announcement_responses", ["clinic_id"])

    # --- A member can report an error ------------------------------------
    op.create_table(
        "error_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("app_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("state", sa.String(20), nullable=False, server_default="new"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("state IN ('new', 'read', 'archived')", name="ck_error_reports_state"),
    )
    op.create_index("ix_error_reports_clinic_id", "error_reports", ["clinic_id"])
    op.create_index("ix_error_reports_state", "error_reports", ["state"])


def downgrade() -> None:
    op.drop_index("ix_error_reports_state", table_name="error_reports")
    op.drop_index("ix_error_reports_clinic_id", table_name="error_reports")
    op.drop_table("error_reports")

    op.drop_index("ix_announcement_responses_clinic_id", table_name="announcement_responses")
    op.drop_index("ix_announcement_responses_announcement_id", table_name="announcement_responses")
    op.drop_table("announcement_responses")

    # Surveys go with the table that held their answers.
    op.execute("DELETE FROM announcements WHERE kind = 'survey'")
    op.drop_constraint("ck_announcements_survey_options", "announcements", type_="check")
    op.drop_constraint("ck_announcements_kind", "announcements", type_="check")
    op.create_check_constraint(
        "ck_announcements_kind", "announcements", "kind IN ('maintenance', 'feature')"
    )
    op.drop_column("announcements", "options")
