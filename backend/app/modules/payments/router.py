"""Payments module FastAPI router.

Endpoints under ``/api/v1/payments/``. Reports are nested under
``/api/v1/payments/reports/*`` so the module owns both the operational
and analytic surfaces — consistent with the design that payment KPIs
should not be cross-joined against invoice data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db
from app.modules.budget.integrations import PATIENTS_UNAVAILABLE, patients_available

from .errors import payments_error, schedule_error, workflow_error
from .schedules import ScheduleService
from .schemas import (
    AgingBuckets,
    AllocationResponse,
    BudgetIdsRequest,
    BudgetSummariesByIds,
    CollectionContactCreate,
    CollectionContactResponse,
    FilterIdsResponse,
    MethodBreakdown,
    PatientIdsRequest,
    PatientLedger,
    PatientSummariesByIds,
    PaymentCreate,
    PaymentReallocate,
    PaymentResponse,
    PaymentScheduleCreate,
    PaymentScheduleResponse,
    PaymentScheduleUpdate,
    PaymentsSummary,
    PaymentsTrends,
    ProfessionalBreakdown,
    ReceivablePatient,
    ReceivableRow,
    RefundCreate,
    RefundResponse,
    RefundsReport,
    TreatmentCollectionSummary,
    TreatmentIdsRequest,
)
from .service import (
    LedgerService,
    PaymentReadService,
    PaymentReportsService,
    PaymentService,
)
from .workflow import (
    PaymentWorkflowError,
    reallocate_payment,
    record_payment,
    refund_payment,
)

router = APIRouter()


async def _ensure_patient(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID, *, writing: bool = False
) -> None:
    """404 when the patient is not this clinic's.

    While Patients is off (ADR 0037) nothing new is written for a patient
    — ``writing`` answers 400 — and a read goes on without asking: every
    query behind these routes is scoped by ``clinic_id`` anyway.

    Mirrors the odontogram / periodontogram pattern, minus its
    ``status != "archived"`` clause: money outlives the chart, and an
    archived patient's ledger still has to be readable.

    The aggregation below is already scoped by ``clinic_id``, so this
    discloses nothing that was leaking — it stops the route answering a
    question about a patient it should not be able to name
    (ADR 0029, invariant 2).
    """
    if not patients_available():
        if writing:
            raise payments_error("payments.patients.unavailable", detail=PATIENTS_UNAVAILABLE)
        return

    from sqlalchemy import select

    from app.modules.patients.models import Patient

    owned = await db.scalar(
        select(Patient.id).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
        )
    )
    if owned is None:
        raise payments_error("payments.patient.not_found")


def _bad_request(exc: Exception):
    return workflow_error(str(exc))


# --- Payments ---------------------------------------------------------


# --- Agreed payment schedules -----------------------------------------
#
# Declared BEFORE the ``/{payment_id}`` routes below: FastAPI resolves in
# registration order, and "schedules" would otherwise be parsed as a
# payment id and rejected as an invalid UUID.
#
# What the clinic and the patient agreed to pay, and when. Distinct from the
# earned ledger: that answers "what is owed for work done", this answers "what
# was agreed". Both settle against the same payments — never add them.


@router.get("/schedules", response_model=ApiResponse[list[PaymentScheduleResponse]])
async def list_payment_schedules(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    patient_id: UUID | None = Query(default=None),
    budget_id: UUID | None = Query(default=None),
    include_cancelled: bool = Query(default=False),
) -> ApiResponse[list[PaymentScheduleResponse]]:
    schedules = await ScheduleService.list_schedules(
        db,
        ctx.clinic_id,
        patient_id=patient_id,
        budget_id=budget_id,
        include_cancelled=include_cancelled,
    )
    return ApiResponse(data=[await _schedule_response(db, ctx.clinic_id, s) for s in schedules])


@router.post(
    "/schedules",
    response_model=ApiResponse[PaymentScheduleResponse],
    status_code=201,
)
async def create_payment_schedule(
    payload: PaymentScheduleCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PaymentScheduleResponse]:
    """Record an agreed schedule.

    Amounts are taken as given: only the caller knows what the total is for,
    and a plan knows its phases where payments does not.
    """
    await _ensure_patient(db, ctx.clinic_id, payload.patient_id, writing=True)
    try:
        schedule = await ScheduleService.create(
            db, ctx.clinic_id, ctx.user_id, payload.model_dump()
        )
    except ValueError as exc:
        raise schedule_error(str(exc)) from exc
    await db.commit()
    reloaded = await ScheduleService.get(db, ctx.clinic_id, schedule.id)
    return ApiResponse(data=await _schedule_response(db, ctx.clinic_id, reloaded))


@router.get("/schedules/{schedule_id}", response_model=ApiResponse[PaymentScheduleResponse])
async def get_payment_schedule(
    schedule_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PaymentScheduleResponse]:
    schedule = await ScheduleService.get(db, ctx.clinic_id, schedule_id)
    if schedule is None:
        raise payments_error("payments.schedule.not_found")
    return ApiResponse(data=await _schedule_response(db, ctx.clinic_id, schedule))


@router.put("/schedules/{schedule_id}", response_model=ApiResponse[PaymentScheduleResponse])
async def update_payment_schedule(
    schedule_id: UUID,
    payload: PaymentScheduleUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PaymentScheduleResponse]:
    """Renegotiate a schedule.

    Allowed after money has been collected: settlement is derived from the
    payments, so the new instalments are simply re-covered in order.
    """
    if not patients_available():
        raise payments_error("payments.patients.unavailable", detail=PATIENTS_UNAVAILABLE)
    try:
        schedule = await ScheduleService.update(
            db, ctx.clinic_id, schedule_id, payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise schedule_error(str(exc)) from exc
    if schedule is None:
        raise payments_error("payments.schedule.not_found")
    await db.commit()
    reloaded = await ScheduleService.get(db, ctx.clinic_id, schedule_id)
    return ApiResponse(data=await _schedule_response(db, ctx.clinic_id, reloaded))


@router.delete("/schedules/{schedule_id}", status_code=204)
async def cancel_payment_schedule(
    schedule_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Supersede an agreement. Never deleted — it is part of what happened."""
    if not patients_available():
        raise payments_error("payments.patients.unavailable", detail=PATIENTS_UNAVAILABLE)
    if not await ScheduleService.cancel(db, ctx.clinic_id, schedule_id):
        raise payments_error("payments.schedule.not_found")
    await db.commit()


async def _schedule_response(db, clinic_id: UUID, schedule) -> PaymentScheduleResponse:
    settlement = await ScheduleService.settlement(db, clinic_id, schedule)
    return PaymentScheduleResponse(
        id=schedule.id,
        patient_id=schedule.patient_id,
        budget_id=schedule.budget_id,
        status=schedule.status,
        notes=schedule.notes,
        **settlement,
    )


# --- Reports ----------------------------------------------------------
#
# Declared before `/{payment_id}` for the same reason `/schedules` is:
# FastAPI resolves in registration order, so with these last
# `GET /reports/refunds` was swallowed by `GET /{payment_id}/refunds`
# and answered 422 "reports is not a valid UUID" — the refunds report
# was unreachable.


@router.get("/reports/summary", response_model=ApiResponse[PaymentsSummary])
async def reports_summary(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.reports.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> ApiResponse[PaymentsSummary]:
    data = await PaymentReportsService.summary(
        db, ctx.clinic_id, ctx.clinic.currency, date_from, date_to, ctx.clinic.timezone
    )
    return ApiResponse(data=data)


@router.get("/reports/by-method", response_model=ApiResponse[list[MethodBreakdown]])
async def reports_by_method(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.reports.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> ApiResponse[list[MethodBreakdown]]:
    data = await PaymentReportsService.by_method(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=data)


@router.get("/reports/by-professional", response_model=ApiResponse[list[ProfessionalBreakdown]])
async def reports_by_professional(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.reports.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> ApiResponse[list[ProfessionalBreakdown]]:
    data = await PaymentReportsService.by_professional(
        db, ctx.clinic_id, date_from, date_to, ctx.clinic.timezone
    )
    return ApiResponse(data=data)


@router.get(
    "/receivables",
    response_model=PaginatedApiResponse[ReceivableRow],
)
async def list_receivables(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    bucket: str | None = Query(default=None, pattern="^(0-30|31-60|61-90|90\\+)$"),
    q: str | None = Query(default=None, max_length=120),
) -> PaginatedApiResponse[ReceivableRow]:
    """Who owes money, oldest debt first — the list a clinic works through.

    The aging report answers "how much is 90 days overdue"; this answers
    "who", which is the only version of the question somebody can act on.

    Declared before ``/{payment_id}``: FastAPI resolves in registration
    order and "receivables" would otherwise be parsed as a payment id.
    """
    if not patients_available():
        # A row is a patient to call; none can be named while Patients is off.
        return PaginatedApiResponse(data=[], total=0, page=page, page_size=page_size)

    from sqlalchemy import select

    from app.modules.patients.models import Patient

    rows = await LedgerService.receivables(db, ctx.clinic_id)
    if bucket:
        rows = [r for r in rows if r["bucket"] == bucket]
    if not rows:
        return PaginatedApiResponse(data=[], total=0, page=page, page_size=page_size)

    patients = {
        p.id: p
        for p in (
            await db.execute(
                select(Patient).where(
                    Patient.clinic_id == ctx.clinic_id,
                    Patient.id.in_([r["patient_id"] for r in rows]),
                )
            )
        )
        .scalars()
        .all()
    }
    # A patient the clinic cannot name is a row it cannot work: drop it
    # rather than answer with a bare id (ADR 0029, invariant 2).
    rows = [r for r in rows if r["patient_id"] in patients]

    if q:
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle
            in f"{patients[r['patient_id']].first_name} "
            f"{patients[r['patient_id']].last_name}".lower()
        ]

    total = len(rows)
    window = rows[(page - 1) * page_size : page * page_size]

    window_ids = [r["patient_id"] for r in window]
    last_paid = await LedgerService.last_payment_dates(db, ctx.clinic_id, window_ids)
    last_chased = await LedgerService.last_contacts(db, ctx.clinic_id, window_ids)

    return PaginatedApiResponse(
        data=[
            ReceivableRow(
                patient=ReceivablePatient.model_validate(patients[r["patient_id"]]),
                receivable=r["receivable"],
                oldest_unpaid_at=r["oldest_unpaid_at"],
                age_days=r["age_days"],
                bucket=r["bucket"],
                last_payment_at=last_paid.get(r["patient_id"]),
                last_contact_at=(
                    last_chased[r["patient_id"]].created_at
                    if r["patient_id"] in last_chased
                    else None
                ),
                last_contact_channel=(
                    last_chased[r["patient_id"]].channel if r["patient_id"] in last_chased else None
                ),
            )
            for r in window
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/receivables/{patient_id}/contacts",
    response_model=ApiResponse[CollectionContactResponse],
    status_code=status.HTTP_201_CREATED,
)
async def record_collection_contact(
    patient_id: UUID,
    data: CollectionContactCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[CollectionContactResponse]:
    """Note that somebody chased this patient about what they owe.

    `record.write` rather than a permission of its own: whoever may take
    the money is whoever rings to ask for it, and a second grant to
    administer would only ever be set to the same people.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id, writing=True)
    contact = await LedgerService.record_contact(
        db, ctx.clinic_id, patient_id, ctx.user_id, data.model_dump()
    )
    return ApiResponse(data=CollectionContactResponse.model_validate(contact))


@router.get(
    "/receivables/{patient_id}/contacts",
    response_model=ApiResponse[list[CollectionContactResponse]],
)
async def list_collection_contacts(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[CollectionContactResponse]]:
    """Everything tried with this patient, most recent first."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    contacts = await LedgerService.contacts_for(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=[CollectionContactResponse.model_validate(c) for c in contacts])


@router.get("/reports/aging-receivables", response_model=ApiResponse[AgingBuckets])
async def reports_aging(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.reports.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AgingBuckets]:
    data = await PaymentReportsService.aging_receivables(db, ctx.clinic_id, ctx.clinic.currency)
    return ApiResponse(data=data)


@router.get("/reports/refunds", response_model=ApiResponse[RefundsReport])
async def reports_refunds(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.reports.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> ApiResponse[RefundsReport]:
    data = await PaymentReportsService.refunds_report(
        db, ctx.clinic_id, ctx.clinic.currency, date_from, date_to, ctx.clinic.timezone
    )
    return ApiResponse(data=data)


@router.get("/reports/trends", response_model=ApiResponse[PaymentsTrends])
async def reports_trends(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.reports.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
    granularity: Literal["day", "week", "month", "year"] = "month",
) -> ApiResponse[PaymentsTrends]:
    data = await PaymentReportsService.trends(
        db, ctx.clinic_id, ctx.clinic.currency, date_from, date_to, granularity, ctx.clinic.timezone
    )
    return ApiResponse(data=data)


@router.get("", response_model=PaginatedApiResponse[PaymentResponse])
async def list_payments(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    method: str | None = None,
    patient_id: UUID | None = None,
    has_refunds: bool | None = Query(default=None),
    has_unallocated: bool | None = Query(default=None),
    amount_min: Decimal | None = Query(default=None, ge=Decimal("0")),
    amount_max: Decimal | None = Query(default=None, ge=Decimal("0")),
    sort: str | None = Query(default=None, max_length=50),
) -> PaginatedApiResponse[PaymentResponse]:
    items, total = await PaymentService.list(
        db,
        ctx.clinic_id,
        date_from=date_from,
        date_to=date_to,
        method=method,
        patient_id=patient_id,
        page=page,
        page_size=page_size,
        has_refunds=has_refunds,
        has_unallocated=has_unallocated,
        amount_min=amount_min,
        amount_max=amount_max,
        sort=sort,
    )
    return PaginatedApiResponse(
        data=[PaymentResponse.from_model(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ApiResponse[PaymentResponse], status_code=201)
async def create_payment(
    payload: PaymentCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PaymentResponse]:
    try:
        payment = await record_payment(
            db,
            clinic_id=ctx.clinic_id,
            currency=ctx.clinic.currency,
            patient_id=payload.patient_id,
            amount=payload.amount,
            method=payload.method,
            payment_date=payload.payment_date,
            recorded_by=ctx.user_id,
            allocations=[a.model_dump() for a in payload.allocations],
            reference=payload.reference,
            notes=payload.notes,
        )
    except PaymentWorkflowError as exc:
        raise _bad_request(exc)

    fresh = await PaymentService.get(db, ctx.clinic_id, payment.id)
    if fresh is None:  # pragma: no cover - defensive
        raise RuntimeError("Payment vanished after create")
    return ApiResponse(data=PaymentResponse.from_model(fresh))


@router.get("/{payment_id}", response_model=ApiResponse[PaymentResponse])
async def get_payment(
    payment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PaymentResponse]:
    payment = await PaymentService.get(db, ctx.clinic_id, payment_id)
    if payment is None:
        raise payments_error("payments.payment.not_found")
    return ApiResponse(data=PaymentResponse.from_model(payment))


@router.post("/{payment_id}/reallocate", response_model=ApiResponse[PaymentResponse])
async def reallocate(
    payment_id: UUID,
    payload: PaymentReallocate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PaymentResponse]:
    payment = await PaymentService.get(db, ctx.clinic_id, payment_id)
    if payment is None:
        raise payments_error("payments.payment.not_found")
    try:
        await reallocate_payment(
            db,
            clinic_id=ctx.clinic_id,
            payment=payment,
            new_allocations=[a.model_dump() for a in payload.allocations],
            changed_by=ctx.user_id,
        )
    except PaymentWorkflowError as exc:
        raise _bad_request(exc)

    fresh = await PaymentService.get(db, ctx.clinic_id, payment_id)
    return ApiResponse(data=PaymentResponse.from_model(fresh))


# --- Refunds ----------------------------------------------------------


@router.get("/{payment_id}/refunds", response_model=ApiResponse[list[RefundResponse]])
async def list_refunds(
    payment_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[RefundResponse]]:
    payment = await PaymentService.get(db, ctx.clinic_id, payment_id)
    if payment is None:
        raise payments_error("payments.payment.not_found")
    return ApiResponse(data=[RefundResponse.model_validate(r) for r in payment.refunds])


@router.post("/{payment_id}/refunds", response_model=ApiResponse[RefundResponse], status_code=201)
async def create_refund(
    payment_id: UUID,
    payload: RefundCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.refund"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RefundResponse]:
    payment = await PaymentService.get(db, ctx.clinic_id, payment_id)
    if payment is None:
        raise payments_error("payments.payment.not_found")
    try:
        refund = await refund_payment(
            db,
            clinic_id=ctx.clinic_id,
            payment=payment,
            amount=payload.amount,
            method=payload.method,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
            refunded_by=ctx.user_id,
        )
    except PaymentWorkflowError as exc:
        raise _bad_request(exc)
    return ApiResponse(data=RefundResponse.model_validate(refund))


# --- Ledger / per-budget ---------------------------------------------


@router.get("/patients/{patient_id}/ledger", response_model=ApiResponse[PatientLedger])
async def patient_ledger(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientLedger]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    ledger = await LedgerService.get_patient_ledger(
        db,
        ctx.clinic_id,
        patient_id,
        currency=ctx.clinic.currency,
        # Payment dates are calendar days; the timeline needs the clinic's
        # own midnight to place them, not UTC's.
        timezone=ctx.clinic.timezone,
    )
    return ApiResponse(data=ledger)


@router.get(
    "/patients/{patient_id}/pending-charges",
    response_model=ApiResponse[list[dict]],
)
async def patient_pending_charges(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[dict]]:
    """Earned entries not yet covered by net payments (FIFO virtual)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    pending = await LedgerService.compute_pending_charges(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=pending)


@router.get(
    "/budgets/{budget_id}/allocations",
    response_model=ApiResponse[list[AllocationResponse]],
)
async def allocations_for_budget(
    budget_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AllocationResponse]]:
    rows = await PaymentReadService.get_allocations_for_budget(db, ctx.clinic_id, budget_id)
    return ApiResponse(data=[AllocationResponse.from_model(r) for r in rows])


# --- Cross-module summary + filter endpoints --------------------------
#
# Power the /budgets and /patients list pages (other modules) without
# forcing those modules to depend on payments. The contract lives in
# docs/technical/payments/cross-module-summaries.md.


@router.post(
    "/summary/by-budgets",
    response_model=ApiResponse[BudgetSummariesByIds],
)
async def summary_by_budgets(
    payload: BudgetIdsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[BudgetSummariesByIds]:
    """Bulk per-budget collected/pending/payment_status.

    Cap 100 ids — sized for one page of a list. Off-books safe: never
    touches invoice totals.
    """
    summaries = await PaymentReadService.summaries_by_budgets(db, ctx.clinic_id, payload.budget_ids)
    return ApiResponse(data=BudgetSummariesByIds(summaries=summaries))


@router.post(
    "/summary/by-patients",
    response_model=ApiResponse[PatientSummariesByIds],
)
async def summary_by_patients(
    payload: PatientIdsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientSummariesByIds]:
    """Bulk per-patient total_paid/debt/on_account_balance.

    Cap 100 ids. debt is computed strictly from earned − net_paid (off
    -books safe).
    """
    summaries = await PaymentReadService.summaries_by_patients(
        db, ctx.clinic_id, payload.patient_ids
    )
    return ApiResponse(data=PatientSummariesByIds(summaries=summaries))


@router.post(
    "/summary/by-treatments",
    response_model=ApiResponse[TreatmentCollectionSummary],
)
async def summary_by_treatments(
    payload: TreatmentIdsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentCollectionSummary]:
    """Per-treatment and per-session collection state for one patient.

    Powers the money view of a treatment plan without the plan importing
    anything from payments. Cap 200 ids — a plan is a few dozen lines at
    most. Off-books safe: pure earned-minus-collected, never invoiced.
    """
    await _ensure_patient(db, ctx.clinic_id, payload.patient_id)
    state = await LedgerService.collection_state_by_treatments(
        db, ctx.clinic_id, payload.patient_id, payload.treatment_ids
    )
    return ApiResponse(
        data=TreatmentCollectionSummary(treatments=state["treatments"], sessions=state["sessions"])
    )


@router.get(
    "/filters/budgets-by-status",
    response_model=ApiResponse[FilterIdsResponse],
)
async def filter_budgets_by_status(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: list[Literal["unpaid", "partial", "paid"]] = Query(..., min_length=1),
    patient_id: UUID | None = Query(default=None),
    assigned_professional_id: UUID | None = Query(default=None),
) -> ApiResponse[FilterIdsResponse]:
    """Return the clinic's budget ids whose payment status matches.

    Used by the /budgets page to intersect with its native list when
    the "Cobro" filter is active. Cap 1000 ids — frontend shows a
    toast when ``truncated=true``.
    """
    ids, truncated = await PaymentReadService.budget_ids_by_payment_status(
        db,
        ctx.clinic_id,
        list(status),
        patient_id=patient_id,
        assigned_professional_id=assigned_professional_id,
    )
    return ApiResponse(data=FilterIdsResponse(budget_ids=ids, truncated=truncated))


@router.get(
    "/filters/patients-with-debt",
    response_model=ApiResponse[FilterIdsResponse],
)
async def filter_patients_with_debt(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("payments.record.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    min_debt: Decimal = Query(default=Decimal("0.01"), ge=Decimal("0")),
) -> ApiResponse[FilterIdsResponse]:
    """Return the clinic's patient ids with debt >= ``min_debt``.

    Used by the /patients page when the "Con deuda" filter is active.
    Cap 1000 ids. Off-books safe: debt = earned − net_paid.
    """
    ids, truncated = await PaymentReadService.patient_ids_with_debt(
        db, ctx.clinic_id, min_debt=min_debt
    )
    return ApiResponse(data=FilterIdsResponse(patient_ids=ids, truncated=truncated))
