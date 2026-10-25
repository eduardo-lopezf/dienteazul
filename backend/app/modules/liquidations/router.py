"""Liquidations module FastAPI router.

Endpoints under ``/api/v1/liquidations/``.
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

from .errors import liquidation_error, service_error
from .schemas import (
    CommissionResponse,
    CommissionUpsert,
    LiquidationIssue,
    LiquidationPay,
    LiquidationPreview,
    LiquidationResponse,
)
from .service import CommissionService, LiquidationError, LiquidationService

# No prefix: `_mount_one` mounts every module router at
# ``/api/v1/<module name>``.
router = APIRouter(tags=["liquidations"])


# --- The arrangement ---------------------------------------------------


@router.get("/commissions", response_model=ApiResponse[list[CommissionResponse]])
async def list_commissions(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("liquidations.settlement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[CommissionResponse]]:
    commissions = await CommissionService.list(db, ctx.clinic_id)
    return ApiResponse(data=[CommissionResponse.model_validate(c) for c in commissions])


@router.put("/commissions/{professional_id}", response_model=ApiResponse[CommissionResponse])
async def upsert_commission(
    professional_id: UUID,
    data: CommissionUpsert,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    # Narrower than reading a settlement: what a clinic pays its associates
    # is the owner's business, not the front desk's.
    _: Annotated[None, Depends(require_permission("liquidations.commission.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CommissionResponse]:
    try:
        await CommissionService.upsert(db, ctx.clinic_id, professional_id, data.model_dump())
    except LiquidationError as exc:
        raise service_error(exc) from exc
    await db.commit()
    reloaded = await CommissionService.get(db, ctx.clinic_id, professional_id)
    return ApiResponse(data=CommissionResponse.model_validate(reloaded))


# --- The settlement ----------------------------------------------------


# Declared before ``/{liquidation_id}``: FastAPI resolves in registration
# order and "preview" would parse as an id.
@router.get("/preview", response_model=ApiResponse[LiquidationPreview])
async def preview_liquidation(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("liquidations.settlement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    professional_id: Annotated[UUID, Query()],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
) -> ApiResponse[LiquidationPreview]:
    """What a settlement would say if it were issued right now.

    Recalculated on every read, which is correct while nobody has been
    paid. Issuing is what stops it moving.
    """
    try:
        preview = await LiquidationService.preview(
            db,
            ctx.clinic_id,
            ctx.clinic.currency,
            ctx.clinic.timezone,
            professional_id,
            date_from,
            date_to,
        )
    except LiquidationError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=preview)


@router.get("", response_model=ApiResponse[list[LiquidationResponse]])
async def list_liquidations(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("liquidations.settlement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    professional_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ApiResponse[list[LiquidationResponse]]:
    liquidations = await LiquidationService.list(
        db,
        ctx.clinic_id,
        professional_id=professional_id,
        date_from=date_from,
        date_to=date_to,
    )
    return ApiResponse(data=[LiquidationResponse.model_validate(x) for x in liquidations])


@router.post(
    "",
    response_model=ApiResponse[LiquidationResponse],
    status_code=status.HTTP_201_CREATED,
)
async def issue_liquidation(
    data: LiquidationIssue,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("liquidations.settlement.issue"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LiquidationResponse]:
    try:
        liquidation = await LiquidationService.issue(
            db,
            ctx.clinic_id,
            ctx.clinic.currency,
            ctx.clinic.timezone,
            ctx.user_id,
            data.model_dump(),
        )
    except LiquidationError as exc:
        raise service_error(exc) from exc
    await db.commit()
    reloaded = await LiquidationService.get(db, ctx.clinic_id, liquidation.id)
    return ApiResponse(data=LiquidationResponse.model_validate(reloaded))


@router.get("/{liquidation_id}", response_model=ApiResponse[LiquidationResponse])
async def get_liquidation(
    liquidation_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("liquidations.settlement.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LiquidationResponse]:
    liquidation = await LiquidationService.get(db, ctx.clinic_id, liquidation_id)
    if liquidation is None:
        raise liquidation_error("liquidations.settlement.not_found")
    return ApiResponse(data=LiquidationResponse.model_validate(liquidation))


@router.post("/{liquidation_id}/pay", response_model=ApiResponse[LiquidationResponse])
async def pay_liquidation(
    liquidation_id: UUID,
    data: LiquidationPay,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    # Same grant as issuing, deliberately: both are the owner deciding that
    # money moves, and a fourth permission every holder of the third would
    # also hold is flexibility nobody asked for. Split it if a clinic ever
    # wants a manager who can produce the document but not hand over cash.
    _: Annotated[None, Depends(require_permission("liquidations.settlement.issue"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LiquidationResponse]:
    """Hand the settlement over.

    A cash payout writes the till movement in the same transaction — see
    `LiquidationService.pay` for why this is a direct call and not an event.
    """
    try:
        liquidation = await LiquidationService.pay(
            db,
            ctx.clinic_id,
            ctx.clinic.currency,
            ctx.clinic.timezone,
            ctx.user_id,
            liquidation_id,
            data.model_dump(),
        )
    except LiquidationError as exc:
        raise service_error(exc) from exc
    if liquidation is None:
        raise liquidation_error("liquidations.settlement.not_found")
    await db.commit()
    reloaded = await LiquidationService.get(db, ctx.clinic_id, liquidation_id)
    return ApiResponse(data=LiquidationResponse.model_validate(reloaded))


@router.post("/{liquidation_id}/unpay", response_model=ApiResponse[LiquidationResponse])
async def unpay_liquidation(
    liquidation_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("liquidations.settlement.issue"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LiquidationResponse]:
    """Undo a payout recorded by mistake, while the till still allows it."""
    try:
        liquidation = await LiquidationService.unpay(db, ctx.clinic_id, liquidation_id)
    except LiquidationError as exc:
        raise service_error(exc) from exc
    if liquidation is None:
        raise liquidation_error("liquidations.settlement.not_found")
    await db.commit()
    reloaded = await LiquidationService.get(db, ctx.clinic_id, liquidation_id)
    return ApiResponse(data=LiquidationResponse.model_validate(reloaded))
