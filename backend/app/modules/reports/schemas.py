"""Report schemas for all report types."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

# ============================================================================
# Common
# ============================================================================


class DateRangeParams(BaseModel):
    """Common date range parameters for reports."""

    date_from: date
    date_to: date


# ============================================================================
# Billing Reports
# ============================================================================


class VatSummaryItem(BaseModel):
    """VAT breakdown item."""

    vat_type_id: UUID | None
    vat_rate: float
    vat_name: str
    base_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class BillingSummary(BaseModel):
    """Billing summary for a period."""

    period_start: date
    period_end: date

    total_invoiced: Decimal
    total_paid: Decimal
    total_pending: Decimal

    invoice_count: int
    paid_count: int
    overdue_count: int

    vat_breakdown: list[VatSummaryItem]


class PaymentMethodSummary(BaseModel):
    """Payment breakdown by method."""

    payment_method: str
    total_amount: Decimal
    payment_count: int


class ProfessionalBillingSummary(BaseModel):
    """Billing breakdown by professional."""

    professional_id: UUID
    professional_name: str
    total_invoiced: Decimal
    invoice_count: int


class OverdueInvoice(BaseModel):
    """Overdue invoice item."""

    id: UUID
    invoice_number: str
    patient_name: str
    issue_date: date
    due_date: date
    days_overdue: int
    balance_due: Decimal


class NumberingGap(BaseModel):
    """Invoice numbering gap."""

    series_prefix: str
    year: int
    missing_numbers: list[int]


class PatientBillingSummary(BaseModel):
    """Patient billing summary (budgets + invoices)."""

    patient_id: UUID

    # Budget metrics
    total_budgeted: Decimal
    work_in_progress: Decimal
    work_completed: Decimal

    # Invoice metrics
    total_invoiced: Decimal
    total_paid: Decimal
    balance_pending: Decimal


# ============================================================================
# Budget Reports
# ============================================================================


class BudgetSummary(BaseModel):
    """Budget summary for a period."""

    period_start: date
    period_end: date

    total_created: int
    total_amount: Decimal

    accepted_count: int
    accepted_amount: Decimal

    rejected_count: int
    pending_count: int
    completed_count: int
    completed_amount: Decimal

    acceptance_rate: float = Field(description="Percentage 0-100")
    average_value: Decimal


class BudgetByProfessional(BaseModel):
    """Budget breakdown by professional."""

    professional_id: UUID | None
    professional_name: str
    budget_count: int
    total_amount: Decimal
    accepted_count: int
    acceptance_rate: float


class BudgetByTreatment(BaseModel):
    """Most common treatments in budgets."""

    catalog_item_id: UUID | None
    treatment_name: str
    occurrence_count: int
    total_quantity: int
    total_amount: Decimal


class BudgetByStatus(BaseModel):
    """Budget breakdown by status."""

    status: str
    count: int
    total_amount: Decimal


# ============================================================================
# Scheduling Reports
# ============================================================================


class SchedulingSummary(BaseModel):
    """Scheduling summary for a period."""

    period_start: date
    period_end: date
    total_appointments: int
    completed: int
    cancelled: int
    no_show: int
    scheduled: int
    confirmed: int
    checked_in: int
    in_treatment: int
    completion_rate: float = Field(description="Percentage 0-100")
    cancellation_rate: float = Field(description="Percentage 0-100")
    no_show_rate: float = Field(description="Percentage 0-100")


# ---- Appointment lifecycle analytics (issue #49) -------------------------


class AnalyticsBucket(BaseModel):
    """A single bar in a distribution chart."""

    label: str
    count: int


class WaitingTimeStats(BaseModel):
    """Time between ``checked_in`` and ``in_treatment``."""

    period_start: date
    period_end: date
    sample_size: int
    avg_minutes: float | None
    median_minutes: float | None
    p90_minutes: float | None
    distribution: list[AnalyticsBucket]


class PunctualityStats(BaseModel):
    """Delta between scheduled ``start_time`` and ``checked_in`` timestamp.

    Negative = early, positive = late. ``on_time_pct`` is the share of
    check-ins with ``|delta| <= 5`` minutes.
    """

    period_start: date
    period_end: date
    sample_size: int
    avg_delta_minutes: float | None
    median_delta_minutes: float | None
    on_time_pct: float | None
    distribution: list[AnalyticsBucket]


class DurationVarianceStats(BaseModel):
    """Planned vs actual treatment duration."""

    period_start: date
    period_end: date
    sample_size: int
    avg_overrun_pct: float | None
    avg_delta_minutes: float | None
    overrun_count: int
    under_count: int


class AppointmentFunnel(BaseModel):
    """Counts per current status + completion/no-show/cancellation rates."""

    period_start: date
    period_end: date
    total: int
    counts_by_status: dict[str, int]
    completion_rate: float | None
    no_show_rate: float | None
    cancellation_rate: float | None


class FirstVisitsSummary(BaseModel):
    """New patients per period."""

    period_start: date
    period_end: date
    new_patients: int
    total_appointments: int
    first_visit_rate: float = Field(description="Percentage 0-100")


class HoursByProfessional(BaseModel):
    """Hours worked by professional."""

    professional_id: UUID | None
    professional_name: str
    appointment_count: int
    completed_count: int
    cancelled_count: int
    no_show_count: int
    total_minutes: int
    total_hours: float


class CabinetUtilization(BaseModel):
    """Cabinet/chair utilization."""

    cabinet: str
    appointment_count: int
    completed_count: int
    total_minutes: int
    total_hours: float


class DayOfWeekStats(BaseModel):
    """Appointment distribution by day of week."""

    day_of_week: int = Field(description="0=Sunday, 1=Monday, ..., 6=Saturday")
    day_name: str
    appointment_count: int
    completed_count: int
    cancelled_count: int
    no_show_count: int


# ============================================================================
# Scheduled summary
# ============================================================================


class SummaryScheduleResponse(BaseModel):
    """A clinic's standing order for its one-page summary."""

    is_active: bool
    cadence: Literal["weekly", "monthly"]
    recipients: list[EmailStr]
    last_sent_for: date | None


class SummaryScheduleUpdate(BaseModel):
    """What the settings screen sends back.

    ``recipients`` is capped: this is the clinic telling itself how it is
    doing, not a mailing list, and an unbounded list is an unbounded send
    on a cron.
    """

    is_active: bool = False
    cadence: Literal["weekly", "monthly"] = "monthly"
    recipients: list[EmailStr] = Field(default_factory=list, max_length=10)


# ============================================================================
# Monthly targets
# ============================================================================


class AttainmentOut(BaseModel):
    """One goal: asked, arrived, and how far that is.

    ``ratio`` is null when no goal was set — different from a goal of
    zero, and a screen must not draw them alike.
    """

    target: Decimal | None
    actual: Decimal
    ratio: float | None


class MonthlyTargetResponse(BaseModel):
    month: date
    collected: AttainmentOut
    production: AttainmentOut
    new_patients: AttainmentOut


class MonthlyTargetUpdate(BaseModel):
    """Every goal optional: a clinic sets the ones it actually steers by."""

    collected_target: Decimal | None = Field(default=None, ge=0)
    production_target: Decimal | None = Field(default=None, ge=0)
    new_patients_target: int | None = Field(default=None, ge=0)


# ============================================================================
# Actionable lists
# ============================================================================


class ActionableRowOut(BaseModel):
    """One person to contact, and why.

    The PII fields keep the owning columns' names (`phone`, `email`,
    `patient_name`) so the classification on those columns still
    tokenizes them wherever this is serialized (ADR 0025).
    """

    patient_id: UUID
    patient_name: str
    phone: str | None
    email: str | None
    amount: Decimal | None
    days: int | None
    detail: str | None


class ActionableListOut(BaseModel):
    """A list, plus what it was asked for, so a screen can say so."""

    key: Literal["owes_not_booked", "accepted_not_booked", "no_visit"]
    rows: list[ActionableRowOut]
    truncated: bool
