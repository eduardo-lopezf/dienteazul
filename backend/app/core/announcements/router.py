"""What a clinic's members read: the operator's notices in force for it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context
from app.core.schemas import ApiResponse
from app.database import get_db

from .models import Announcement

router = APIRouter(prefix="/announcements", tags=["announcements"])


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Literal["maintenance", "feature"]
    message: str
    starts_at: datetime
    ends_at: datetime | None


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
    return ApiResponse(
        data=[AnnouncementResponse.model_validate(a) for a in await in_force(db, ctx.clinic_id)]
    )
