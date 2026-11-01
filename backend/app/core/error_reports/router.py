"""What a clinic's user files from the Help drawer, and nothing else.

Writing is all a clinic can do here: a member files a report, and that is
the end of their side of it. Reading them is the operator's, through
``GET /api/v1/ops/error-reports`` — a report is about the software, so it
is not a clinic's record to browse, and one member's account of their
afternoon is not for their colleagues to read either.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context
from app.core.auth.router import bearer_rate_key, limiter
from app.core.schemas import ApiResponse
from app.database import get_db

from .models import MAX_DESCRIPTION, ErrorReport

router = APIRouter(prefix="/error-reports", tags=["error-reports"])


class ErrorReportWrite(BaseModel):
    """A report as the Help drawer sends it."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    #: The route they were on. Its query string is dropped here as well
    #: as in the browser, because that is where identifiers travel.
    path: str = Field(min_length=1, max_length=300)
    #: The build of the interface. The deployment may not state one.
    app_version: str = Field(default="", max_length=40)

    @field_validator("description")
    @classmethod
    def said_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The description is empty")
        return value.strip()


class ErrorReportFiled(BaseModel):
    """Only that it arrived, and under which id — nothing to read back."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID


@router.post("", response_model=ApiResponse[ErrorReportFiled], status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour", key_func=bearer_rate_key)
async def file_error_report(
    request: Request,
    data: ErrorReportWrite,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ErrorReportFiled]:
    """File a report. Any member may: being stuck is not a permission.

    Capped per user, so a frustrated afternoon cannot bury the operator's
    console under one person's retries.
    """
    row = ErrorReport(
        clinic_id=ctx.clinic_id,
        user_id=ctx.user_id,
        description=data.description,
        path=data.path.split("?", 1)[0],
        app_version=data.app_version.strip(),
    )
    db.add(row)
    await db.flush()
    return ApiResponse(data=ErrorReportFiled.model_validate(row))
