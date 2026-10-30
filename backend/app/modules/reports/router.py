"""Reports module router."""

import io
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.exports import to_zip
from app.core.schemas import ApiResponse
from app.database import get_db

from . import actionable, exports, monthly
from . import schedule as schedule_service
from . import targets as targets_service
from .errors import service_error
from .integrations import needs
from .schemas import (
    ActionableListOut,
    ActionableRowOut,
    AppointmentFunnel,
    AttainmentOut,
    BillingSummary,
    BudgetByProfessional,
    BudgetByStatus,
    BudgetByTreatment,
    BudgetSummary,
    CabinetUtilization,
    DayOfWeekStats,
    DurationVarianceStats,
    FirstVisitsSummary,
    HoursByProfessional,
    MonthlyTargetResponse,
    MonthlyTargetUpdate,
    NumberingGap,
    OverdueInvoice,
    PaymentMethodSummary,
    ProfessionalBillingSummary,
    PunctualityStats,
    SchedulingSummary,
    SummaryScheduleResponse,
    SummaryScheduleUpdate,
    VatSummaryItem,
    WaitingTimeStats,
)
from .services import (
    AppointmentLifecycleService,
    BillingReportService,
    BudgetReportService,
    SchedulingReportService,
)

router = APIRouter(tags=["reports"])

#: Spanish Excel pairs ";" with comma decimals. The caller may ask for ","
#: (dot decimals) when the file is going into something else.
Separator = Literal[";", ","]


def _zip_response(files: dict[str, bytes], filename: str) -> StreamingResponse:
    """The report's CSVs as one download.

    A ZIP rather than one file because a report screen is several tables
    and a single CSV holding all of them is a spreadsheet nobody can sort.
    """
    body = to_zip(files)
    return StreamingResponse(
        io.BytesIO(body),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary.pdf", response_class=StreamingResponse)
async def summary_pdf(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.summary.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> StreamingResponse:
    """The clinic's period on one printable page.

    One permission of its own rather than the sum of the detail reports':
    "may see how the clinic is doing" is a different thing to grant than
    "may read the invoice ledger", and a clinic owner wants the first
    without necessarily handing out the second. Which sections appear is
    decided by the Apps that are running (ADR 0037), not by further
    permissions.
    """
    pdf = await monthly.render_pdf(db, ctx.clinic, date_from, date_to)
    name = monthly.filename(ctx.clinic_id, date_from, date_to)
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


@router.get("/summary/schedule", response_model=ApiResponse[SummaryScheduleResponse])
async def get_summary_schedule(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.summary.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SummaryScheduleResponse]:
    """When this clinic's summary goes out on its own, and to whom.

    Asks for the write permission rather than the read one: the answer
    contains the staff addresses that receive it, which is more than
    "may look at the figures" buys.
    """
    row = await schedule_service.get_or_create(db, ctx.clinic_id)
    return ApiResponse(data=SummaryScheduleResponse.model_validate(row, from_attributes=True))


@router.put("/summary/schedule", response_model=ApiResponse[SummaryScheduleResponse])
async def put_summary_schedule(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.summary.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: SummaryScheduleUpdate,
) -> ApiResponse[SummaryScheduleResponse]:
    """Set the standing order. Off with no recipients is the default state."""
    row = await schedule_service.update(
        db,
        ctx.clinic_id,
        is_active=payload.is_active,
        cadence=payload.cadence,
        recipients=[str(address) for address in payload.recipients],
    )
    return ApiResponse(data=SummaryScheduleResponse.model_validate(row, from_attributes=True))


def _targets_response(row, attainment: dict) -> MonthlyTargetResponse:
    """The service answers in dataclasses; the wire wants the schema."""
    return MonthlyTargetResponse(
        month=row.month,
        **{
            name: AttainmentOut(target=value.target, actual=value.actual, ratio=value.ratio)
            for name, value in attainment.items()
        },
    )


@router.get("/targets", response_model=ApiResponse[MonthlyTargetResponse])
async def get_targets(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.summary.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    month: date = Query(..., description="Any day of the month; the month is the grain"),
) -> ApiResponse[MonthlyTargetResponse]:
    """This month's goals and how the clinic is doing against them.

    Same permission as the one-page summary: both answer "how is the
    clinic doing", and a target without its actual is not an answer.
    """
    row, attainment = await targets_service.progress(db, ctx.clinic, month)
    return ApiResponse(data=_targets_response(row, attainment))


@router.put("/targets", response_model=ApiResponse[MonthlyTargetResponse])
async def put_targets(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.summary.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: MonthlyTargetUpdate,
    month: date = Query(..., description="Any day of the month; the month is the grain"),
) -> ApiResponse[MonthlyTargetResponse]:
    """Set a month's goals. Null clears one — "no goal", not a goal of zero."""
    await targets_service.set_targets(
        db,
        ctx.clinic_id,
        month,
        collected=payload.collected_target,
        production=payload.production_target,
        new_patients=payload.new_patients_target,
    )
    row, attainment = await targets_service.progress(db, ctx.clinic, month)
    return ApiResponse(data=_targets_response(row, attainment))


def _actionable_response(key: str, rows: list) -> ActionableListOut:
    return ActionableListOut(
        key=key,
        # ``vars()`` is no good here: the row is a slots dataclass.
        rows=[ActionableRowOut(**asdict(row)) for row in rows],
        # A full page means there is more behind it; the screen says so
        # rather than letting somebody believe they finished the queue.
        truncated=len(rows) >= actionable.MAX_ROWS,
    )


@router.get("/actionable/owes-not-booked", response_model=ApiResponse[ActionableListOut])
async def actionable_owes_not_booked(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.actionable.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    minimum: Decimal = Query(default=Decimal("0"), ge=0),
) -> ApiResponse[ActionableListOut]:
    """Owes at least ``minimum`` and has no future appointment."""
    rows = await actionable.owes_and_not_coming_back(db, ctx.clinic_id, minimum)
    return ApiResponse(data=_actionable_response("owes_not_booked", rows))


@router.get("/actionable/accepted-not-booked", response_model=ApiResponse[ActionableListOut])
async def actionable_accepted_not_booked(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.actionable.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ActionableListOut]:
    """Said yes to a budget and never got a date."""
    rows = await actionable.accepted_but_not_booked(db, ctx.clinic_id)
    return ApiResponse(data=_actionable_response("accepted_not_booked", rows))


@router.get("/actionable/no-visit", response_model=ApiResponse[ActionableListOut])
async def actionable_no_visit(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.actionable.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    months: int = Query(default=12, ge=1, le=60),
) -> ApiResponse[ActionableListOut]:
    """Not seen in ``months``, and nothing booked."""
    rows = await actionable.no_visit_in_months(db, ctx.clinic_id, months)
    return ApiResponse(data=_actionable_response("no_visit", rows))


# ============================================================================
# Billing Reports
# ============================================================================


@router.get(
    "/billing/summary",
    response_model=ApiResponse[BillingSummary],
    dependencies=[Depends(needs("billing"))],
)
async def get_billing_summary(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[BillingSummary]:
    """Get billing summary for a period.

    Returns total invoiced, total paid, total pending, counts, and VAT breakdown.
    """
    data = await BillingReportService.get_summary(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=BillingSummary(**data))


@router.get(
    "/billing/overdue",
    response_model=ApiResponse[list[OverdueInvoice]],
    dependencies=[Depends(needs("billing"))],
)
async def get_overdue_invoices(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=200, ge=1, le=1000),
) -> ApiResponse[list[OverdueInvoice]]:
    """Get list of overdue invoices, oldest due-date first.

    ``limit`` caps the result at 1000 so a clinic with years of unpaid
    balances doesn't return an unbounded set.
    """
    data = await BillingReportService.get_overdue_invoices(db, ctx.clinic_id, limit=limit)
    return ApiResponse(data=[OverdueInvoice(**item) for item in data])


@router.get(
    "/billing/by-payment-method",
    response_model=ApiResponse[list[PaymentMethodSummary]],
    dependencies=[Depends(needs("billing"))],
)
async def get_by_payment_method(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[PaymentMethodSummary]]:
    """Get payment breakdown by method.

    Returns total amounts and counts grouped by payment method.
    """
    data = await BillingReportService.get_by_payment_method(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=[PaymentMethodSummary(**item) for item in data])


@router.get(
    "/billing/by-professional",
    response_model=ApiResponse[list[ProfessionalBillingSummary]],
    dependencies=[Depends(needs("billing"))],
)
async def get_by_professional(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[ProfessionalBillingSummary]]:
    """Get billing breakdown by professional (creator).

    Returns total amounts and invoice counts per professional.
    """
    data = await BillingReportService.get_by_professional(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=[ProfessionalBillingSummary(**item) for item in data])


@router.get(
    "/billing/vat-summary",
    response_model=ApiResponse[list[VatSummaryItem]],
    dependencies=[Depends(needs("billing"))],
)
async def get_vat_summary(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[VatSummaryItem]]:
    """Get VAT summary for accounting.

    Returns base amounts, tax amounts, and totals grouped by VAT rate.
    """
    data = await BillingReportService.get_vat_summary(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=[VatSummaryItem(**item) for item in data])


@router.get(
    "/billing/gaps",
    response_model=ApiResponse[list[NumberingGap]],
    dependencies=[Depends(needs("billing"))],
)
async def get_numbering_gaps(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[NumberingGap]]:
    """Find gaps in invoice numbering.

    Returns missing numbers by series and year.
    Useful for compliance audits.
    """
    data = await BillingReportService.get_numbering_gaps(db, ctx.clinic_id)
    return ApiResponse(data=[NumberingGap(**item) for item in data])


@router.get(
    "/billing/export",
    dependencies=[Depends(needs("billing"))],
    response_class=StreamingResponse,
)
async def export_billing(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.billing.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
    separator: Separator = Query(default=";"),
) -> StreamingResponse:
    """The Facturación screen as a ZIP of CSVs.

    Same permission as reading it: a reader who can see the figures can
    take them away, and a second permission would land on the same people.
    """
    files = await exports.billing_files(db, ctx.clinic_id, date_from, date_to, separator)
    return _zip_response(files, exports.period_name("facturacion", date_from, date_to))


# ============================================================================
# Budget Reports
# ============================================================================


@router.get(
    "/budgets/summary",
    response_model=ApiResponse[BudgetSummary],
    dependencies=[Depends(needs("budget"))],
)
async def get_budget_summary(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.budgets.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[BudgetSummary]:
    """Get budget summary for a period.

    Returns totals, acceptance rate, and average value.
    """
    data = await BudgetReportService.get_summary(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=BudgetSummary(**data))


@router.get(
    "/budgets/by-professional",
    response_model=ApiResponse[list[BudgetByProfessional]],
    dependencies=[Depends(needs("budget"))],
)
async def get_budgets_by_professional(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.budgets.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[BudgetByProfessional]]:
    """Get budget breakdown by professional."""
    data = await BudgetReportService.get_by_professional(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=[BudgetByProfessional(**item) for item in data])


@router.get(
    "/budgets/by-treatment",
    response_model=ApiResponse[list[BudgetByTreatment]],
    dependencies=[Depends(needs("budget"))],
)
async def get_budgets_by_treatment(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.budgets.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
    limit: int = Query(default=10, ge=1, le=50, description="Number of top treatments"),
) -> ApiResponse[list[BudgetByTreatment]]:
    """Get most common treatments in budgets."""
    data = await BudgetReportService.get_by_treatment(db, ctx.clinic_id, date_from, date_to, limit)
    return ApiResponse(data=[BudgetByTreatment(**item) for item in data])


@router.get(
    "/budgets/by-status",
    response_model=ApiResponse[list[BudgetByStatus]],
    dependencies=[Depends(needs("budget"))],
)
async def get_budgets_by_status(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.budgets.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[BudgetByStatus]]:
    """Get budget breakdown by status."""
    data = await BudgetReportService.get_by_status(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=[BudgetByStatus(**item) for item in data])


@router.get(
    "/budgets/export",
    dependencies=[Depends(needs("budget"))],
    response_class=StreamingResponse,
)
async def export_budgets(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.budgets.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
    separator: Separator = Query(default=";"),
) -> StreamingResponse:
    """The Presupuestos screen as a ZIP of CSVs."""
    files = await exports.budget_files(db, ctx.clinic_id, date_from, date_to, separator)
    return _zip_response(files, exports.period_name("presupuestos", date_from, date_to))


# ============================================================================
# Scheduling Reports
# ============================================================================


@router.get(
    "/scheduling/summary",
    response_model=ApiResponse[SchedulingSummary],
    dependencies=[Depends(needs("agenda"))],
)
async def get_scheduling_summary(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[SchedulingSummary]:
    """Get scheduling summary for a period.

    Returns appointment counts by status and rates.
    """
    data = await SchedulingReportService.get_summary(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=SchedulingSummary(**data))


@router.get(
    "/scheduling/first-visits",
    response_model=ApiResponse[FirstVisitsSummary],
    dependencies=[Depends(needs("agenda"))],
)
async def get_first_visits(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[FirstVisitsSummary]:
    """Get first visits (new patients) statistics."""
    data = await SchedulingReportService.get_first_visits(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=FirstVisitsSummary(**data))


@router.get(
    "/scheduling/by-professional",
    response_model=ApiResponse[list[HoursByProfessional]],
    dependencies=[Depends(needs("agenda"))],
)
async def get_hours_by_professional(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[HoursByProfessional]]:
    """Get hours worked by professional."""
    data = await SchedulingReportService.get_hours_by_professional(
        db, ctx.clinic_id, date_from, date_to
    )
    return ApiResponse(data=[HoursByProfessional(**item) for item in data])


@router.get(
    "/scheduling/by-cabinet",
    response_model=ApiResponse[list[CabinetUtilization]],
    dependencies=[Depends(needs("agenda"))],
)
async def get_cabinet_utilization(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[CabinetUtilization]]:
    """Get cabinet/chair utilization."""
    data = await SchedulingReportService.get_cabinet_utilization(
        db, ctx.clinic_id, date_from, date_to
    )
    return ApiResponse(data=[CabinetUtilization(**item) for item in data])


@router.get(
    "/scheduling/by-day-of-week",
    response_model=ApiResponse[list[DayOfWeekStats]],
    dependencies=[Depends(needs("agenda"))],
)
async def get_by_day_of_week(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
) -> ApiResponse[list[DayOfWeekStats]]:
    """Get appointment distribution by day of week."""
    data = await SchedulingReportService.get_by_day_of_week(db, ctx.clinic_id, date_from, date_to)
    return ApiResponse(data=[DayOfWeekStats(**item) for item in data])


# ---- Appointment lifecycle analytics (issue #49) -------------------------


@router.get(
    "/scheduling/waiting-times",
    response_model=ApiResponse[WaitingTimeStats],
    dependencies=[Depends(needs("agenda"))],
)
async def get_waiting_times(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
    cabinet_id: UUID | None = Query(default=None),
    professional_id: UUID | None = Query(default=None),
) -> ApiResponse[WaitingTimeStats]:
    """Average / median / p90 time from ``checked_in`` to ``in_treatment``."""
    try:
        data = await AppointmentLifecycleService.waiting_times(
            db,
            ctx.clinic_id,
            date_from,
            date_to,
            cabinet_id=cabinet_id,
            professional_id=professional_id,
        )
    except ValueError as e:
        raise service_error(e) from e
    return ApiResponse(data=WaitingTimeStats(**data))


@router.get(
    "/scheduling/punctuality",
    response_model=ApiResponse[PunctualityStats],
    dependencies=[Depends(needs("agenda"))],
)
async def get_punctuality(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
    cabinet_id: UUID | None = Query(default=None),
    professional_id: UUID | None = Query(default=None),
) -> ApiResponse[PunctualityStats]:
    """Patient punctuality (check-in vs scheduled start time)."""
    try:
        data = await AppointmentLifecycleService.punctuality(
            db,
            ctx.clinic_id,
            date_from,
            date_to,
            cabinet_id=cabinet_id,
            professional_id=professional_id,
        )
    except ValueError as e:
        raise service_error(e) from e
    return ApiResponse(data=PunctualityStats(**data))


@router.get(
    "/scheduling/duration-variance",
    response_model=ApiResponse[DurationVarianceStats],
    dependencies=[Depends(needs("agenda"))],
)
async def get_duration_variance(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
    cabinet_id: UUID | None = Query(default=None),
    professional_id: UUID | None = Query(default=None),
) -> ApiResponse[DurationVarianceStats]:
    """Planned vs actual treatment duration (in-treatment → completed)."""
    try:
        data = await AppointmentLifecycleService.duration_variance(
            db,
            ctx.clinic_id,
            date_from,
            date_to,
            cabinet_id=cabinet_id,
            professional_id=professional_id,
        )
    except ValueError as e:
        raise service_error(e) from e
    return ApiResponse(data=DurationVarianceStats(**data))


@router.get(
    "/scheduling/funnel",
    response_model=ApiResponse[AppointmentFunnel],
    dependencies=[Depends(needs("agenda"))],
)
async def get_appointment_funnel(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(...),
    date_to: date = Query(...),
    cabinet_id: UUID | None = Query(default=None),
    professional_id: UUID | None = Query(default=None),
) -> ApiResponse[AppointmentFunnel]:
    """Counts per status + completion / no-show / cancellation rates."""
    try:
        data = await AppointmentLifecycleService.funnel(
            db,
            ctx.clinic_id,
            date_from,
            date_to,
            cabinet_id=cabinet_id,
            professional_id=professional_id,
        )
    except ValueError as e:
        raise service_error(e) from e
    return ApiResponse(data=AppointmentFunnel(**data))


@router.get(
    "/scheduling/export",
    dependencies=[Depends(needs("agenda"))],
    response_class=StreamingResponse,
)
async def export_scheduling(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("reports.scheduling.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: date = Query(..., description="Start date for the report period"),
    date_to: date = Query(..., description="End date for the report period"),
    separator: Separator = Query(default=";"),
) -> StreamingResponse:
    """The Agenda screen as a ZIP of CSVs."""
    files = await exports.scheduling_files(db, ctx.clinic_id, date_from, date_to, separator)
    return _zip_response(files, exports.period_name("agenda", date_from, date_to))
