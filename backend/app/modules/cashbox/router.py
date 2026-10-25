"""Cashbox module FastAPI router.

Endpoints under ``/api/v1/cashbox/``. Phase 1 is the movements surface;
``/closings`` and ``/periods`` join it in the phases that follow.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .errors import cashbox_error, service_error
from .schemas import (
    CashClosingCreate,
    CashClosingReopen,
    CashClosingResponse,
    CashMovementCreate,
    CashMovementDayTotals,
    CashMovementResponse,
    CashMovementUpdate,
    CashPeriod,
    CashPosition,
    LateEntry,
    LateEntryAcknowledge,
    PeriodKind,
)
from .service import (
    CashboxError,
    ClosingService,
    LateEntryService,
    MovementService,
    PeriodService,
)

# No prefix here: `_mount_one` mounts every module router at
# ``/api/v1/<module name>``, so declaring one gives
# ``/api/v1/cashbox/cashbox/...``.
router = APIRouter(tags=["cashbox"])


# Declared before ``/movements/{movement_id}``: FastAPI resolves routes in
# registration order, and "totals" would otherwise parse as a movement id.
# The same trap cost `payments` a 422 on ``/reports/refunds``.
@router.get("/movements/totals", response_model=ApiResponse[CashMovementDayTotals])
async def get_day_totals(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.movement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    business_date: Annotated[date, Query()],
) -> ApiResponse[CashMovementDayTotals]:
    totals = await MovementService.day_totals(db, ctx.clinic_id, ctx.clinic.currency, business_date)
    return ApiResponse(data=totals)


@router.get("/movements", response_model=ApiResponse[list[CashMovementResponse]])
async def list_movements(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.movement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    direction: str | None = None,
    category: str | None = None,
) -> ApiResponse[list[CashMovementResponse]]:
    """Not paginated, and that is a decision rather than an omission.

    A till's movements are bounded by the days asked for, and the screen
    that uses this asks for one. A clinic that manages fifty rows in a day
    has a different problem than pagination solves.
    """
    movements = await MovementService.list(
        db,
        ctx.clinic_id,
        date_from=date_from,
        date_to=date_to,
        direction=direction,
        category=category,
    )
    return ApiResponse(data=[CashMovementResponse.model_validate(m) for m in movements])


@router.post(
    "/movements",
    response_model=ApiResponse[CashMovementResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_movement(
    data: CashMovementCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.movement.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CashMovementResponse]:
    movement = await MovementService.create(
        db,
        ctx.clinic_id,
        ctx.clinic.currency,
        ctx.user_id,
        data.model_dump(),
    )
    await db.commit()
    reloaded = await MovementService.get(db, ctx.clinic_id, movement.id)
    return ApiResponse(data=CashMovementResponse.model_validate(reloaded))


@router.get("/movements/{movement_id}", response_model=ApiResponse[CashMovementResponse])
async def get_movement(
    movement_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.movement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CashMovementResponse]:
    movement = await MovementService.get(db, ctx.clinic_id, movement_id)
    if movement is None:
        raise cashbox_error("cashbox.movement.not_found")
    return ApiResponse(data=CashMovementResponse.model_validate(movement))


@router.put("/movements/{movement_id}", response_model=ApiResponse[CashMovementResponse])
async def update_movement(
    movement_id: UUID,
    data: CashMovementUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.movement.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CashMovementResponse]:
    try:
        movement = await MovementService.update(
            db,
            ctx.clinic_id,
            movement_id,
            data.model_dump(exclude_unset=True),
        )
    except CashboxError as exc:
        raise service_error(exc) from exc
    if movement is None:
        raise cashbox_error("cashbox.movement.not_found")
    await db.commit()
    reloaded = await MovementService.get(db, ctx.clinic_id, movement_id)
    return ApiResponse(data=CashMovementResponse.model_validate(reloaded))


@router.delete("/movements/{movement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movement(
    movement_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.movement.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        deleted = await MovementService.delete(db, ctx.clinic_id, movement_id)
    except CashboxError as exc:
        raise service_error(exc) from exc
    if not deleted:
        raise cashbox_error("cashbox.movement.not_found")
    await db.commit()


# --- The arqueo -------------------------------------------------------


@router.get("/position", response_model=ApiResponse[CashPosition])
async def get_position(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.closing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    business_date: Annotated[date, Query()],
) -> ApiResponse[CashPosition]:
    """What the drawer should hold for a day, and the workings behind it.

    Carries `expected_cash`, which the counting screen must **not** show
    before the count is entered — see `CashPosition`. The endpoint returns
    it anyway because the same call serves the history view, where the day
    is already counted and there is nothing left to bias.
    """
    position = await ClosingService.position(
        db,
        ctx.clinic_id,
        ctx.clinic.currency,
        ctx.clinic.timezone,
        business_date,
    )
    return ApiResponse(data=position)


@router.get("/closings", response_model=ApiResponse[list[CashClosingResponse]])
async def list_closings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.closing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    include_superseded: bool = False,
) -> ApiResponse[list[CashClosingResponse]]:
    """The history of counts, which is where the difference stops being noise.

    Superseded counts are hidden by default and available on request: the
    day-to-day question is "what stands", while "who recounted this and
    why" is an audit, asked deliberately.
    """
    closings = await ClosingService.list(
        db,
        ctx.clinic_id,
        date_from=date_from,
        date_to=date_to,
        include_superseded=include_superseded,
    )
    return ApiResponse(data=[CashClosingResponse.model_validate(c) for c in closings])


@router.post(
    "/closings",
    response_model=ApiResponse[CashClosingResponse],
    status_code=status.HTTP_201_CREATED,
)
async def close_day(
    data: CashClosingCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.closing.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CashClosingResponse]:
    try:
        closing = await ClosingService.close(
            db,
            ctx.clinic_id,
            ctx.clinic.currency,
            ctx.clinic.timezone,
            ctx.user_id,
            data.model_dump(),
        )
    except CashboxError as exc:
        raise service_error(exc) from exc
    await db.commit()
    reloaded = await ClosingService.get(db, ctx.clinic_id, closing.id)
    return ApiResponse(data=CashClosingResponse.model_validate(reloaded))


@router.get("/closings/{closing_id}", response_model=ApiResponse[CashClosingResponse])
async def get_closing(
    closing_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.closing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CashClosingResponse]:
    closing = await ClosingService.get(db, ctx.clinic_id, closing_id)
    if closing is None:
        raise cashbox_error("cashbox.closing.not_found")
    return ApiResponse(data=CashClosingResponse.model_validate(closing))


@router.post(
    "/closings/{closing_id}/reopen",
    response_model=ApiResponse[CashClosingResponse],
)
async def reopen_closing(
    closing_id: UUID,
    data: CashClosingReopen,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    # Narrower than `closing.write` on purpose: reopening throws away a
    # count a person made and signed off, which is administration's call,
    # not the counter's. Same narrowing `treatment_plan` applies to
    # reopening a plan, and for the same reason.
    _: Annotated[None, Depends(require_permission("cashbox.closing.reopen"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CashClosingResponse]:
    try:
        closing = await ClosingService.reopen(
            db, ctx.clinic_id, closing_id, ctx.user_id, data.reason
        )
    except CashboxError as exc:
        raise service_error(exc) from exc
    if closing is None:
        raise cashbox_error("cashbox.closing.not_found")
    await db.commit()
    reloaded = await ClosingService.get(db, ctx.clinic_id, closing_id)
    return ApiResponse(data=CashClosingResponse.model_validate(reloaded))


# --- Period cuts ------------------------------------------------------


@router.get("/periods", response_model=ApiResponse[CashPeriod])
async def get_period(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.closing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    kind: Annotated[PeriodKind, Query()],
    # `day`, not `date`: naming the parameter after the type it is annotated
    # with resolves only because annotations are strings here, and that is a
    # footgun to leave lying around.
    day: Annotated[date, Query(description="Any day inside the period.")],
) -> ApiResponse[CashPeriod]:
    """The week, fortnight or month containing `date`, built from the arqueos.

    Takes any day in the period rather than its bounds: the caller should
    not have to know where a Mexican quincena starts, and having two places
    compute that is how they come to disagree.
    """
    try:
        period = await PeriodService.summary(
            db,
            ctx.clinic_id,
            ctx.clinic.currency,
            ctx.clinic.timezone,
            kind,
            day,
        )
    except CashboxError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=period)


# --- Entries that landed after their day was counted -------------------


@router.get("/late-entries", response_model=ApiResponse[list[LateEntry]])
async def list_late_entries(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("cashbox.closing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    include_acknowledged: bool = False,
) -> ApiResponse[list[LateEntry]]:
    """Money written against a day that had already been counted.

    Carries no patient identity: this module depends on `payments` and not
    on `patients`, and the reference plus the amount are enough to find the
    row in Cobros, which is where the person belongs.
    """
    entries = await LateEntryService.list(
        db,
        ctx.clinic_id,
        ctx.clinic.currency,
        ctx.clinic.timezone,
        date_from,
        date_to,
        include_acknowledged=include_acknowledged,
    )
    return ApiResponse(data=entries)


@router.post(
    "/late-entries/acknowledge",
    response_model=ApiResponse[LateEntry],
    status_code=status.HTTP_201_CREATED,
)
async def acknowledge_late_entry(
    data: LateEntryAcknowledge,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    # `closing.write`, not `closing.reopen`: deciding that a late entry goes
    # into next week's count is reception's call and changes nothing that
    # was signed. Reopening the day is the other answer, and that one stays
    # with administration.
    _: Annotated[None, Depends(require_permission("cashbox.closing.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LateEntry]:
    try:
        await LateEntryService.acknowledge(db, ctx.clinic_id, ctx.user_id, data.model_dump())
    except CashboxError as exc:
        raise service_error(exc) from exc
    await db.commit()

    entries = await LateEntryService.list(
        db,
        ctx.clinic_id,
        ctx.clinic.currency,
        ctx.clinic.timezone,
        data.business_date,
        data.business_date,
        include_acknowledged=True,
    )
    match = next((e for e in entries if e.entry_id == data.entry_id), None)
    if match is None:
        raise cashbox_error("cashbox.late_entry.not_found")
    return ApiResponse(data=match)
