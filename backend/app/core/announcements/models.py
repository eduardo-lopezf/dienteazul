"""An operator's notice to clinics, and what the clinics answer back."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

KINDS = ("maintenance", "feature", "survey")

#: How many questions a survey may ask. Ten is the ceiling the quality
#: survey was written to, and roughly where a questionnaire stops being
#: answered by busy people.
MAX_QUESTIONS = 10
MAX_QUESTION_TEXT = 200
#: The title the banner shows for a survey ("Encuesta de Calidad"): with
#: ten questions there is no single question to show there.
MAX_TITLE = 80
#: What a member may add to an answer — the elaboration on a yes/no, or
#: the whole of an open answer.
MAX_COMMENT = 1000

#: What a question asks for. ``yes_no`` is answered with a yes or a no and
#: may be elaborated on; ``open`` is prose only.
QUESTION_KINDS = ("yes_no", "open")


class Announcement(Base, TimestampMixin):
    """A short message shown beside the clinic's name at the top of the
    workspace while ``starts_at <= now < ends_at`` — to every clinic, or to
    the ones in ``clinic_ids``. Nothing personal: it is the operator's."""

    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('maintenance', 'feature', 'survey')", name="ck_announcements_kind"
        ),
        # A survey that asks nothing cannot be answered, and a notice that
        # is not a survey asks nothing.
        CheckConstraint(
            "(kind = 'survey') = (questions IS NOT NULL)", name="ck_announcements_survey_questions"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    #: ``maintenance`` (a window when the system may be unavailable),
    #: ``feature`` (something new to try) or ``survey`` (a question the
    #: clinic's members answer with one of ``options``).
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(280), nullable=False)
    #: What the banner shows for a survey — "Encuesta de Calidad". A
    #: questionnaire has no single question to put there, and ``message``
    #: becomes the line of introduction inside it.
    title: Mapped[str | None] = mapped_column(String(MAX_TITLE))
    #: A survey's questions, in the order they are asked, each
    #: ``{"id": str, "kind": "yes_no"|"open", "text": str}``. ``None`` for
    #: every other kind: they ask nothing.
    #:
    #: The ids are stable and generated when the survey is written, so an
    #: answer stays attached to its question when the operator reorders
    #: them or corrects a typo. Positions were what the first version
    #: recorded, and editing a published survey silently moved every
    #: answer to its neighbour.
    #:
    #: ``none_as_null`` because a JSONB column otherwise writes Python
    #: ``None`` as the JSON value ``null``, which *is not* SQL NULL: the
    #: check above read every maintenance notice as a survey with no
    #: questions and refused it.
    questions: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB(none_as_null=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: ``None``: until it is taken down.
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The clinics it is for, as strings; ``None`` is every clinic.
    clinic_ids: Mapped[list[str] | None] = mapped_column(JSONB)


class SurveyAnswer(Base, TimestampMixin):
    """One member's answer to one question of one survey.

    A row per member per question, so a survey half filled in is a survey
    half answered rather than nothing, and sending it again corrects what
    it holds instead of counting twice.

    **This keeps what a member wrote.** The first version did not — an
    answer was the index of a choice the operator had written, and no
    prose could travel with it. A questionnaire that lets people explain
    themselves gives that up: ``comment`` is a staff member describing
    their working day and may name a patient without meaning to. It is
    therefore treated like ``error_reports.description`` — read only in
    the operator's console, never sent to a model, never carried out in a
    subject export — and the form that collects it says so.
    """

    __tablename__ = "announcement_answers"
    __table_args__ = (
        UniqueConstraint(
            "announcement_id", "user_id", "question_id", name="uq_announcement_answers_question"
        ),
        # An answer says something: a yes, a no, or words. A row that is
        # neither is an answer nobody gave.
        CheckConstraint(
            "yes IS NOT NULL OR comment IS NOT NULL", name="ck_announcement_answers_said_something"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Which clinic answered, so the operator can read the result per
    #: inquilino as well as in total.
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: The ``id`` of the question in ``Announcement.questions``.
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The yes or the no. ``None`` for an open question, which has none.
    yes: Mapped[bool | None] = mapped_column(Boolean)
    #: What they added — the elaboration on a yes/no, or the whole of an
    #: open answer. Free text; see the class docstring.
    comment: Mapped[str | None] = mapped_column(Text)
