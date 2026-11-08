"""Commissions module FastAPI router.

Endpoints under ``/api/v1/commissions/``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .errors import service_error
from .models import CommissionAgreement
from .schemas import AgreementIn, AgreementOut, RateOut, TreatmentOption
from .service import CommissionError, CommissionService, require_clinic_tier

# No prefix: `_mount_one` mounts every module router at ``/api/v1/<module name>``.
router = APIRouter(tags=["commissions"])


def _clinic_only(ctx: Annotated[ClinicContext, Depends(get_clinic_context)]) -> None:
    try:
        require_clinic_tier(ctx.clinic.account_tier)
    except CommissionError as exc:
        raise service_error(exc) from exc


async def _out(
    db: AsyncSession, clinic_id: UUID, professional_id: UUID, agreement: CommissionAgreement | None
) -> AgreementOut:
    if agreement is None:
        return AgreementOut(professional_id=professional_id, configured=False)
    named = await CommissionService.treatments(
        db, clinic_id, {r.catalog_item_id for r in agreement.rates}
    )
    return AgreementOut(
        professional_id=professional_id,
        configured=True,
        basis=agreement.basis,
        default_percent=agreement.default_percent,
        notes=agreement.notes,
        rates=[
            RateOut(
                catalog_item_id=r.catalog_item_id,
                percent=r.percent,
                internal_code=named[r.catalog_item_id].internal_code
                if r.catalog_item_id in named
                else None,
                names=named[r.catalog_item_id].names if r.catalog_item_id in named else None,
            )
            for r in agreement.rates
        ],
    )


@router.get("/treatments", response_model=ApiResponse[list[TreatmentOption]])
async def list_treatments(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("commissions.agreement.read"))],
    __: Annotated[None, Depends(_clinic_only)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[TreatmentOption]]:
    """What a rate can be set on. Empty while the Treatments App is off."""
    items = await CommissionService.treatments(db, ctx.clinic_id)
    return ApiResponse(
        data=[
            TreatmentOption(id=b.id, internal_code=b.internal_code, names=b.names)
            for b in items.values()
        ]
    )


@router.get("/professionals/{professional_id}", response_model=ApiResponse[AgreementOut])
async def get_agreement(
    professional_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("commissions.agreement.read"))],
    __: Annotated[None, Depends(_clinic_only)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AgreementOut]:
    agreement = await CommissionService.get(db, ctx.clinic_id, professional_id)
    return ApiResponse(data=await _out(db, ctx.clinic_id, professional_id, agreement))


@router.put("/professionals/{professional_id}", response_model=ApiResponse[AgreementOut])
async def replace_agreement(
    professional_id: UUID,
    data: AgreementIn,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("commissions.agreement.write"))],
    __: Annotated[None, Depends(_clinic_only)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AgreementOut]:
    """Replace the whole agreement. No percentage and no rates clears it."""
    try:
        agreement = await CommissionService.replace(
            db, ctx.clinic_id, professional_id, data.model_dump()
        )
    except CommissionError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _out(db, ctx.clinic_id, professional_id, agreement))
