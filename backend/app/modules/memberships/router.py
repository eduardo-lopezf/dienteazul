"""Memberships module FastAPI router.

Endpoints under ``/api/v1/memberships/``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import contracts
from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.contracts import CatalogItemBrief, MembershipFees
from app.core.schemas import ApiResponse
from app.database import get_db

from .errors import service_error
from .models import MembershipPlan, PatientMembership
from .schemas import (
    BenefitOut,
    ChangePlanIn,
    EnrollIn,
    IncludedUsage,
    MembershipOut,
    PatientMembershipOut,
    PeriodOut,
    PlanIn,
    PlanOut,
    RenewIn,
    TreatmentOption,
)
from .service import (
    GRACE_DAYS,
    FeePayment,
    MembershipError,
    MembershipService,
    PlanService,
    covering_period,
    cycle_start,
    paid_through,
    plan_terms,
    today,
    treatments,
)

# No prefix: `_mount_one` mounts every module router at ``/api/v1/<module name>``.
router = APIRouter(tags=["memberships"])

Ctx = Annotated[ClinicContext, Depends(get_clinic_context)]
Db = Annotated[AsyncSession, Depends(get_db)]


def _named(named: dict[UUID, CatalogItemBrief], item_id: UUID) -> dict:
    brief = named.get(item_id)
    return {
        "internal_code": brief.internal_code if brief else None,
        "names": brief.names if brief else None,
    }


async def _plan_out(db: AsyncSession, clinic_id: UUID, plan: MembershipPlan) -> PlanOut:
    named = await treatments(db, clinic_id, {b.catalog_item_id for b in plan.benefits})
    return PlanOut(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        fee=plan.fee,
        period=plan.period,
        general_discount_percent=plan.general_discount_percent,
        status=plan.status,
        benefits=[
            BenefitOut(
                catalog_item_id=b.catalog_item_id,
                kind=b.kind,
                quantity=b.quantity,
                discount_percent=b.discount_percent,
                **_named(named, b.catalog_item_id),
            )
            for b in plan.benefits
        ],
    )


async def _membership_out(db: AsyncSession, membership: PatientMembership) -> MembershipOut:
    on = today()
    covering = covering_period(membership, on)
    paid = [p for p in membership.periods if p.status == "paid"]
    # The terms in force; once it lapsed, the last ones paid; never paid, the plan's.
    if covering is not None:
        terms = covering.terms
    elif paid:
        terms = max(paid, key=lambda p: p.starts_on).terms
    else:
        terms = plan_terms(membership.plan)

    used = await MembershipService.used_in_cycle(db, membership, on)
    ids = {UUID(b["catalog_item_id"]) for b in terms["benefits"]}
    named = await treatments(db, membership.clinic_id, ids)
    last = paid_through(membership)
    grace = timedelta(days=GRACE_DAYS if membership.status == "active" else 0)
    general = terms.get("general_discount_percent")
    return MembershipOut(
        id=membership.id,
        patient_id=membership.patient_id,
        plan_id=membership.plan_id,
        plan_name=membership.plan.name,
        state="active"
        if covering
        else ("cancelled" if membership.status == "cancelled" else "expired"),
        status=membership.status,
        started_on=membership.started_on,
        paid_through=last,
        covered_until=last + grace if last else None,
        cycle_start=cycle_start(membership.started_on, on),
        general_discount_percent=Decimal(general) if general is not None else None,
        included=[
            IncludedUsage(
                catalog_item_id=UUID(b["catalog_item_id"]),
                quantity=b["quantity"],
                used=used.get(UUID(b["catalog_item_id"]), 0) if covering else 0,
                **_named(named, UUID(b["catalog_item_id"])),
            )
            for b in terms["benefits"]
            if b["kind"] == "included"
        ],
        discounts=[
            BenefitOut(
                catalog_item_id=UUID(b["catalog_item_id"]),
                kind=b["kind"],
                discount_percent=Decimal(b["discount_percent"]),
                **_named(named, UUID(b["catalog_item_id"])),
            )
            for b in terms["benefits"]
            if b["kind"] == "discount"
        ],
        periods=[
            PeriodOut(
                id=p.id,
                starts_on=p.starts_on,
                ends_on=p.ends_on,
                amount=p.amount,
                refunded_amount=p.refunded_amount,
                status=p.status,
                plan_name=p.terms["plan_name"],
                payment_id=p.payment_id,
            )
            for p in sorted(membership.periods, key=lambda p: p.starts_on, reverse=True)
        ],
        payments_available=contracts.provider(MembershipFees) is not None,
    )


def _payment(data: EnrollIn | RenewIn) -> FeePayment:
    return FeePayment(
        method=data.payment.method,
        payment_date=data.payment.payment_date,
        reference=data.payment.reference,
    )


# --- Plans ----------------------------------------------------------------


@router.get("/plans", response_model=ApiResponse[list[PlanOut]])
async def list_plans(
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.plan.read"))],
    db: Db,
    include_archived: Annotated[bool, Query()] = False,
) -> ApiResponse[list[PlanOut]]:
    plans = await PlanService.list(db, ctx.clinic_id, include_archived)
    return ApiResponse(data=[await _plan_out(db, ctx.clinic_id, p) for p in plans])


@router.post("/plans", response_model=ApiResponse[PlanOut], status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanIn,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.plan.write"))],
    db: Db,
) -> ApiResponse[PlanOut]:
    try:
        plan = await PlanService.create(db, ctx.clinic_id, data.model_dump())
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _plan_out(db, ctx.clinic_id, plan))


@router.put("/plans/{plan_id}", response_model=ApiResponse[PlanOut])
async def replace_plan(
    plan_id: UUID,
    data: PlanIn,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.plan.write"))],
    db: Db,
) -> ApiResponse[PlanOut]:
    """Edit the whole plan. Periods already paid keep the terms they were paid on."""
    try:
        plan = await PlanService.replace(db, ctx.clinic_id, plan_id, data.model_dump())
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _plan_out(db, ctx.clinic_id, plan))


@router.post("/plans/{plan_id}/archive", response_model=ApiResponse[PlanOut])
async def archive_plan(
    plan_id: UUID,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.plan.write"))],
    db: Db,
) -> ApiResponse[PlanOut]:
    """No new sign-ups or renewals on it. Memberships already paid keep running."""
    try:
        plan = await PlanService.set_status(db, ctx.clinic_id, plan_id, "archived")
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _plan_out(db, ctx.clinic_id, plan))


@router.post("/plans/{plan_id}/restore", response_model=ApiResponse[PlanOut])
async def restore_plan(
    plan_id: UUID,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.plan.write"))],
    db: Db,
) -> ApiResponse[PlanOut]:
    try:
        plan = await PlanService.set_status(db, ctx.clinic_id, plan_id, "active")
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _plan_out(db, ctx.clinic_id, plan))


@router.get("/treatments", response_model=ApiResponse[list[TreatmentOption]])
async def list_treatments(
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.plan.write"))],
    db: Db,
) -> ApiResponse[list[TreatmentOption]]:
    """What a benefit can be set on. Empty while the Treatments App is off."""
    items = await treatments(db, ctx.clinic_id)
    return ApiResponse(
        data=[
            TreatmentOption(id=b.id, internal_code=b.internal_code, names=b.names)
            for b in items.values()
        ]
    )


# --- A patient's membership -----------------------------------------------


@router.get("/patients/{patient_id}", response_model=ApiResponse[PatientMembershipOut])
async def get_patient_membership(
    patient_id: UUID,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.membership.read"))],
    db: Db,
) -> ApiResponse[PatientMembershipOut]:
    membership = await MembershipService.for_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(
        data=PatientMembershipOut(
            membership=await _membership_out(db, membership) if membership else None
        )
    )


@router.post(
    "/patients/{patient_id}",
    response_model=ApiResponse[MembershipOut],
    status_code=status.HTTP_201_CREATED,
)
async def enroll(
    patient_id: UUID,
    data: EnrollIn,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.membership.write"))],
    db: Db,
) -> ApiResponse[MembershipOut]:
    """Sign the patient up and collect the first fee, as a payment of the patient."""
    try:
        membership = await MembershipService.enroll(
            db,
            ctx.clinic_id,
            patient_id,
            plan_id=data.plan_id,
            starts_on=data.starts_on,
            payment=_payment(data),
            user_id=ctx.user_id,
        )
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _membership_out(db, membership))


@router.post(
    "/{membership_id}/periods",
    response_model=ApiResponse[MembershipOut],
    status_code=status.HTTP_201_CREATED,
)
async def renew(
    membership_id: UUID,
    data: RenewIn,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.membership.write"))],
    db: Db,
) -> ApiResponse[MembershipOut]:
    """Collect the next fee."""
    try:
        membership = await MembershipService.renew(
            db, ctx.clinic_id, membership_id, payment=_payment(data), user_id=ctx.user_id
        )
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _membership_out(db, membership))


@router.put("/{membership_id}/plan", response_model=ApiResponse[MembershipOut])
async def change_plan(
    membership_id: UUID,
    data: ChangePlanIn,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.membership.write"))],
    db: Db,
) -> ApiResponse[MembershipOut]:
    """From the next fee on. Paid periods keep their plan."""
    try:
        membership = await MembershipService.change_plan(
            db, ctx.clinic_id, membership_id, data.plan_id
        )
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _membership_out(db, membership))


@router.post("/{membership_id}/cancel", response_model=ApiResponse[MembershipOut])
async def cancel(
    membership_id: UUID,
    ctx: Ctx,
    _: Annotated[None, Depends(require_permission("memberships.membership.write"))],
    db: Db,
) -> ApiResponse[MembershipOut]:
    """Stop renewing. Benefits stay until the last paid day."""
    try:
        membership = await MembershipService.cancel(db, ctx.clinic_id, membership_id)
    except MembershipError as exc:
        raise service_error(exc) from exc
    return ApiResponse(data=await _membership_out(db, membership))
