"""core — a survey becomes a questionnaire.

``0028`` gave a notice one question and a list of choices, answered with
a click in the banner. The quality survey asks ten things, nine of them a
yes or a no that the member may explain, and one of them prose: "¿Qué
nueva característica o mejora propondrías para esta aplicación?". A
single ``options`` list cannot hold that, and the banner's popover cannot
show it — it now shows the survey's ``title`` ("Encuesta de Calidad") and
opens the questionnaire.

So the shape is replaced rather than extended:

* ``announcements.options`` → ``questions``, each
  ``{"id", "kind": "yes_no"|"open", "text"}`` with a **stable id**, so an
  answer stays attached to its question when the operator reorders them
  or fixes a typo. ``0028`` recorded positions, and editing a published
  survey moved every answer to its neighbour.
* ``announcements.title``, what the banner shows for a survey.
* ``announcement_responses`` (one row per member, holding an index) →
  ``announcement_answers`` (one row per member **per question**, holding
  a yes/no and a comment), so a half-filled survey is half answered.

The two formats do not map onto each other — a choice among labels is not
a yes with an explanation — so the surveys written under ``0028`` and
their answers are removed rather than guessed at. Nothing else is
touched: ``maintenance`` and ``feature`` notices carry on unchanged, and
this migration leaves their rows alone.

**What this keeps that ``0028`` did not: what a member wrote.** See
``SurveyAnswer`` for why that is a change of posture and how it is
handled.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The old format goes first: its rows cannot satisfy the new check,
    # and its answers point at positions that no longer mean anything.
    op.drop_table("announcement_responses")
    op.execute("DELETE FROM announcements WHERE kind = 'survey'")

    op.drop_constraint("ck_announcements_survey_options", "announcements", type_="check")
    op.drop_column("announcements", "options")
    op.add_column("announcements", sa.Column("title", sa.String(80), nullable=True))
    op.add_column("announcements", sa.Column("questions", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_announcements_survey_questions",
        "announcements",
        "(kind = 'survey') = (questions IS NOT NULL)",
    )

    op.create_table(
        "announcement_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", sa.String(40), nullable=False),
        sa.Column("yes", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # One answer per member per question: sending the survey again
        # corrects it instead of counting twice.
        sa.UniqueConstraint(
            "announcement_id", "user_id", "question_id", name="uq_announcement_answers_question"
        ),
        # An answer says something: a yes, a no, or words.
        sa.CheckConstraint(
            "yes IS NOT NULL OR comment IS NOT NULL", name="ck_announcement_answers_said_something"
        ),
    )
    op.create_index(
        "ix_announcement_answers_announcement_id", "announcement_answers", ["announcement_id"]
    )
    op.create_index("ix_announcement_answers_clinic_id", "announcement_answers", ["clinic_id"])


def downgrade() -> None:
    op.drop_index("ix_announcement_answers_clinic_id", table_name="announcement_answers")
    op.drop_index("ix_announcement_answers_announcement_id", table_name="announcement_answers")
    op.drop_table("announcement_answers")

    op.execute("DELETE FROM announcements WHERE kind = 'survey'")
    op.drop_constraint("ck_announcements_survey_questions", "announcements", type_="check")
    op.drop_column("announcements", "questions")
    op.drop_column("announcements", "title")
    op.add_column("announcements", sa.Column("options", postgresql.JSONB(), nullable=True))
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
        sa.UniqueConstraint("announcement_id", "user_id", name="uq_announcement_responses_user"),
    )
    op.create_index(
        "ix_announcement_responses_announcement_id", "announcement_responses", ["announcement_id"]
    )
    op.create_index("ix_announcement_responses_clinic_id", "announcement_responses", ["clinic_id"])
