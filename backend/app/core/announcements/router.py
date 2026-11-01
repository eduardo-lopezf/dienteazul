"""What a clinic's members read: the operator's notices in force for it,
and — when a notice is a survey — the answers they give back."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context
from app.core.schemas import ApiResponse
from app.database import get_db

from .models import MAX_COMMENT, MAX_QUESTIONS, Announcement, SurveyAnswer

router = APIRouter(prefix="/announcements", tags=["announcements"])


class Question(BaseModel):
    """One thing a survey asks."""

    id: str
    kind: Literal["yes_no", "open"]
    text: str


class MyAnswer(BaseModel):
    """What this member has already said to one question."""

    model_config = ConfigDict(from_attributes=True)

    question_id: str
    yes: bool | None = None
    comment: str | None = None


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Literal["maintenance", "feature", "survey"]
    message: str
    starts_at: datetime
    ends_at: datetime | None
    #: What the banner shows for a survey; ``None`` for the other kinds,
    #: where ``message`` is the line itself.
    title: str | None = None
    #: A survey's questions, in order; ``None`` for the other kinds.
    questions: list[Question] | None = None
    #: What *this* member has already answered, so the questionnaire opens
    #: on what they said rather than empty.
    answers: list[MyAnswer] = Field(default_factory=list)


class AnswerWrite(BaseModel):
    """One answer as the questionnaire sends it.

    Neither field given means the member cleared the answer; the row is
    removed rather than kept as an answer nobody gave.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=40)
    yes: bool | None = None
    comment: str | None = Field(default=None, max_length=MAX_COMMENT)

    @field_validator("comment")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AnswersWrite(BaseModel):
    """What the member is sending back, in one go."""

    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerWrite] = Field(max_length=MAX_QUESTIONS)


async def in_force(db: AsyncSession, clinic_id: UUID) -> list[Announcement]:
    """The notices shown to ``clinic_id`` now, newest first."""
    now = datetime.now(UTC)
    rows = await db.scalars(
        select(Announcement)
        .where(
            Announcement.starts_at <= now,
            or_(Announcement.ends_at.is_(None), Announcement.ends_at > now),
        )
        .order_by(Announcement.starts_at.desc())
    )
    return [a for a in rows if a.clinic_ids is None or str(clinic_id) in a.clinic_ids]


@router.get("", response_model=ApiResponse[list[AnnouncementResponse]])
async def list_announcements(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AnnouncementResponse]]:
    """The operator's notices in force for the caller's clinic. Every member
    reads them: they are about the system, never about anyone."""
    notices = await in_force(db, ctx.clinic_id)
    # This member's own answers, in one query rather than one per survey.
    mine: dict[UUID, list[MyAnswer]] = {}
    rows = await db.scalars(
        select(SurveyAnswer).where(
            SurveyAnswer.user_id == ctx.user_id,
            SurveyAnswer.announcement_id.in_([a.id for a in notices] or [None]),
        )
    )
    for row in rows:
        mine.setdefault(row.announcement_id, []).append(MyAnswer.model_validate(row))

    return ApiResponse(
        data=[
            AnnouncementResponse.model_validate(a).model_copy(
                update={"answers": mine.get(a.id, [])}
            )
            for a in notices
        ]
    )


@router.put("/{announcement_id}/answers", status_code=status.HTTP_204_NO_CONTENT)
async def answer_survey(
    announcement_id: UUID,
    submission: AnswersWrite,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Answer a survey, or correct what was answered before.

    Any member may: a survey asks the people who use the software, not the
    ones who administer it. Only a survey in force for *their* clinic can
    be answered — one that has ended, or was never theirs, is not theirs
    to answer now.

    Every question is optional. A questionnaire that refuses to be sent
    until all ten are filled in is a questionnaire busy people abandon, so
    what arrives is kept and the rest stays unanswered. Sending it again
    replaces the answers it names and leaves the others alone.
    """
    notice = next((a for a in await in_force(db, ctx.clinic_id) if a.id == announcement_id), None)
    if notice is None or notice.kind != "survey":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Survey not found")

    asked = {q["id"]: q["kind"] for q in notice.questions or []}
    for answer in submission.answers:
        if answer.question_id not in asked:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No such question")
        if asked[answer.question_id] == "open" and answer.yes is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "An open question has no yes or no"
            )

    existing = {
        row.question_id: row
        for row in await db.scalars(
            select(SurveyAnswer).where(
                SurveyAnswer.announcement_id == announcement_id,
                SurveyAnswer.user_id == ctx.user_id,
            )
        )
    }
    for answer in submission.answers:
        row = existing.get(answer.question_id)
        if answer.yes is None and answer.comment is None:
            # Cleared. An empty row would count as somebody having
            # answered when they have not.
            if row is not None:
                await db.delete(row)
            continue
        if row is None:
            db.add(
                SurveyAnswer(
                    announcement_id=announcement_id,
                    clinic_id=ctx.clinic_id,
                    user_id=ctx.user_id,
                    question_id=answer.question_id,
                    yes=answer.yes,
                    comment=answer.comment,
                )
            )
        else:
            row.yes = answer.yes
            row.comment = answer.comment
    await db.flush()
