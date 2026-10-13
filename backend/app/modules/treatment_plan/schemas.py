"""Treatment plan module Pydantic schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.catalog.schemas import TreatmentPhase

# ---------------------------------------------------------------------------
# Nested brief schemas
# ---------------------------------------------------------------------------


class PatientBrief(BaseModel):
    """Brief patient info."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str


class BudgetBrief(BaseModel):
    """Brief budget info."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    budget_number: str
    status: str
    total: float


class TreatmentToothBrief(BaseModel):
    """Per-tooth member of a Treatment, embedded in plan items."""

    model_config = ConfigDict(from_attributes=True)

    tooth_number: int
    role: str | None = None
    surfaces: list[str] | None = None


class CatalogItemBrief(BaseModel):
    """Brief catalog item info."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    internal_code: str
    names: dict
    default_price: float | None = None
    # Needed by the template UI to decide whether the treatment is waiting
    # for a tooth: tooth / multi_tooth do, global_mouth / global_arch do not.
    treatment_scope: str | None = None
    # Same reason: the plan builder seeds its draft lines from a proposal and
    # a line carries a stage of care. The catalog list the builder already
    # holds is the odontogram's view, which does not include it.
    default_phase: str | None = None


class TreatmentBrief(BaseModel):
    """Brief Treatment info (header + teeth)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clinical_type: str
    scope: str
    arch: str | None = None
    status: str
    catalog_item_id: UUID | None = None
    catalog_item: CatalogItemBrief | None = None
    price_snapshot: Decimal | None = None
    teeth: list[TreatmentToothBrief] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Treatment Plan schemas
# ---------------------------------------------------------------------------


Prognosis = Literal["favorable", "reserved", "unfavorable"]


class TreatmentPlanCreate(BaseModel):
    """Create a treatment plan."""

    patient_id: UUID
    title: str | None = Field(default=None, max_length=200)
    assigned_professional_id: UUID | None = None
    diagnosis_notes: str | None = None
    prognosis: Prognosis | None = None
    prognosis_notes: str | None = None
    internal_notes: str | None = None


class TreatmentPlanUpdate(BaseModel):
    """Update a treatment plan."""

    title: str | None = Field(default=None, max_length=200)
    assigned_professional_id: UUID | None = None
    diagnosis_notes: str | None = None
    prognosis: Prognosis | None = None
    prognosis_notes: str | None = None
    internal_notes: str | None = None
    # Write-only directive. When ``True`` and the doctor of the plan changes,
    # pending items still pointing at the previous doctor are reassigned in
    # the same transaction. Items with an explicit override (different doctor)
    # and completed items are never touched.
    reassign_pending_items: bool = False


class TreatmentPlanStatusUpdate(BaseModel):
    """Change plan status."""

    status: str = Field(..., pattern="^(draft|pending|active|completed|archived|closed)$")


class ClosePlanRequest(BaseModel):
    """Body for ``POST /treatment-plans/{id}/close``."""

    closure_reason: str = Field(
        ...,
        pattern=("^(rejected_by_patient|expired|cancelled_by_clinic|patient_abandoned|other)$"),
    )
    closure_note: str | None = Field(default=None, max_length=2000)


class ContactLogRequest(BaseModel):
    """Body for ``POST /treatment-plans/{id}/contact-log``.

    Records a non-state-changing reception touchpoint with the patient
    so the bandeja can sort by ``last_contact``.
    """

    channel: str = Field(..., pattern="^(call|whatsapp|email|in_person|other)$")
    note: str | None = Field(default=None, max_length=1000)


class PipelineBudgetBrief(BaseModel):
    """Budget metadata embedded in a pipeline row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    total: float | None = None
    valid_until: date | None = None
    last_reminder_sent_at: datetime | None = None
    viewed_at: datetime | None = None


class PipelineNextAppointment(BaseModel):
    """Compact representation of the next scheduled appointment."""

    id: UUID
    start_at: datetime
    cabinet_id: UUID | None = None
    professional_id: UUID | None = None


class PipelineRow(BaseModel):
    """One row in the bandeja de planes (``GET /pipeline``)."""

    plan_id: UUID
    plan_number: str
    plan_title: str | None = None
    plan_status: str
    days_in_status: int
    closure_reason: str | None = None
    items_total: int
    items_completed: int
    patient: PatientBrief
    budget: PipelineBudgetBrief | None = None
    next_appointment: PipelineNextAppointment | None = None


class TreatmentPlanResponse(BaseModel):
    """Response for treatment plan list."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    plan_number: str
    title: str | None
    status: str
    budget_id: UUID | None
    assigned_professional_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    item_count: int = 0
    completed_count: int = 0
    total: float = 0.0
    patient: PatientBrief | None = None
    budget: BudgetBrief | None = None


class PlanNextAction(BaseModel):
    """What has to happen next for the plan to move on.

    ``key`` is the whole contract; the rest is what the sentence needs to
    read naturally (the date of the booked visit, the budget's state).
    The wording lives in the frontend locales, so a clinic that renames
    "presupuesto" does not need a backend release.
    """

    key: str
    budget_status: str | None = None
    next_appointment_at: datetime | None = None
    #: Only for ``budget_addendum``: how many treatments carry no price.
    unbudgeted_count: int | None = None


class TreatmentPlanDetailResponse(TreatmentPlanResponse):
    """Detailed response with nested items."""

    diagnosis_notes: str | None = None
    prognosis: Prognosis | None = None
    prognosis_notes: str | None = None
    internal_notes: str | None = None
    items: list["PlannedTreatmentItemResponse"] = []
    #: Computed per request — never stored. ``None`` once the plan is over.
    next_action: PlanNextAction | None = None
    #: The clinic asks for a signed informed consent for this plan and it
    #: has none. A treatment performed meanwhile is shown as lacking it.
    informed_consent_missing: bool = False
    #: Treatments added after confirmation that no budget prices yet.
    unbudgeted_count: int = 0
    #: The plan's other live budgets — today, its addenda. ``budget`` above
    #: stays the one the plan was agreed on.
    other_budgets: list[BudgetBrief] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Planned treatment item schemas
# ---------------------------------------------------------------------------
#
# Stage of care; the vocabulary is owned by the catalog module, which is in
# this module's ``manifest.depends``.


class PlannedTreatmentItemCreate(BaseModel):
    """Add a treatment to a plan by Treatment id."""

    treatment_id: UUID
    sequence_order: int | None = None
    notes: str | None = None
    # Stage of care. When omitted, seeded from the catalog item's
    # ``default_phase``; pass a value to override for this patient.
    phase: TreatmentPhase | None = None
    # When omitted, the service inherits the plan's ``assigned_professional_id``.
    # Pass an explicit value to override at creation time.
    assigned_professional_id: UUID | None = None


class PlannedTreatmentItemUpdate(BaseModel):
    """Update a planned treatment item (scheduling metadata only)."""

    sequence_order: int | None = None
    notes: str | None = None
    phase: TreatmentPhase | None = None
    # Nullable: passing ``None`` explicitly clears the assignment. The router
    # serializes with ``exclude_unset=True`` so omitting the field leaves the
    # item untouched.
    assigned_professional_id: UUID | None = None


class PlannedItemSessionResponse(BaseModel):
    """One billing / execution step inside a plan item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int
    label: str | None
    amount: Decimal
    status: str  # pending|completed|cancelled
    completed_at: datetime | None
    completed_by: UUID | None
    notes: str | None


class PlannedTreatmentItemResponse(BaseModel):
    """Response for planned treatment item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clinic_id: UUID
    treatment_plan_id: UUID
    treatment_id: UUID
    sequence_order: int
    phase: str | None = None
    status: str
    completed_without_appointment: bool
    completed_at: datetime | None
    completed_by: UUID | None
    assigned_professional_id: UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    # Embedded Treatment + optional catalog item.
    treatment: TreatmentBrief | None = None
    catalog_item: CatalogItemBrief | None = None
    sessions: list[PlannedItemSessionResponse] = Field(default_factory=list)


class SessionInput(BaseModel):
    """Manual session input — used when adding/editing sessions on a plan item.

    ``sequence`` may be omitted (server assigns by array position).
    """

    sequence: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, max_length=120)
    amount: Decimal = Field(ge=0)


class CompleteSessionRequest(BaseModel):
    """Mark one session of a plan item as completed."""

    completed_without_appointment: bool = False
    notes: str | None = None


class UpdateSessionRequest(BaseModel):
    """Edit a pending session (label / amount / notes)."""

    label: str | None = Field(default=None, max_length=120)
    amount: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class CompleteItemRequest(BaseModel):
    """Mark an item as completed.

    Clinical-note capture moved to the ``clinical_notes`` module: the client
    POSTs the note via ``/api/v1/clinical_notes/notes`` after a successful
    completion. ``notes`` (free-text annotation on the item itself) stays —
    it's the legacy one-line memo, not a clinical_notes entry.
    """

    completed_without_appointment: bool = True
    notes: str | None = None


class ReorderItemsRequest(BaseModel):
    """Reorder all items of a plan in a single atomic update.

    `item_ids` MUST cover exactly the plan's current items — no missing, no extras.
    `sequence_order` is rewritten as 0, 1, 2, ... in the given order.
    """

    item_ids: list[UUID]


# ---------------------------------------------------------------------------
# Budget integration schemas
# ---------------------------------------------------------------------------


class LinkBudgetRequest(BaseModel):
    budget_id: UUID


# ---------------------------------------------------------------------------
# Plan templates
# ---------------------------------------------------------------------------


class PlanTemplateItemInput(BaseModel):
    """One line of a template: a catalog item and, optionally, its stage."""

    catalog_item_id: UUID
    # NULL means "use the catalog item's own default_phase".
    phase: TreatmentPhase | None = None
    # A line the clinic may not offer or the patient may not need. Offered
    # ticked when the template is applied; only these can be excluded.
    is_optional: bool = False
    notes: str | None = None


class PlanTemplateItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int
    catalog_item_id: UUID
    phase: str | None = None
    is_optional: bool = False
    notes: str | None = None
    catalog_item: CatalogItemBrief | None = None


class PlanTemplateSpecialty(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    names: dict[str, str]


class PlanTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str | None = None
    #: The discipline a reference template belongs to. None on a template
    #: the clinic saved from one of its own plans.
    specialty: PlanTemplateSpecialty | None = None
    name: str
    description: str | None = None
    is_active: bool
    display_order: int
    items: list[PlanTemplateItemResponse] = Field(default_factory=list)


class PlanTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    display_order: int = 0
    items: list[PlanTemplateItemInput] = Field(default_factory=list)


class PlanTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    display_order: int | None = None
    is_active: bool | None = None
    # Omit to keep the current lines; send a list (even empty) to replace them.
    items: list[PlanTemplateItemInput] | None = None


class PlanTemplateFromPlanRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class ApplyTemplateRequest(BaseModel):
    """Apply a template to a plan.

    ``tooth_numbers`` is what the template itself cannot know. Every per-tooth
    treatment in the template is created once per tooth listed; whole-mouth
    ones are created once regardless. Leave it empty for a template that has
    no per-tooth treatments at all.

    ``excluded_template_item_ids`` drops lines this patient does not need.
    Only lines marked ``is_optional`` may be dropped; excluding a required one
    is a 400.
    """

    template_id: UUID
    tooth_numbers: list[int] = Field(default_factory=list)
    excluded_template_item_ids: list[UUID] = Field(default_factory=list)


class PlanLineInput(BaseModel):
    """One treatment the dentist put on the plan, with its own teeth.

    Per line, not per request: the plan is built by clicking teeth on a
    chart, so a crown on 16 and a filling on 24 arrive together and each
    carries its own piece. A request-wide tooth list could only say "all of
    these, on all of those", which is not what anybody drew.

    ``surfaces`` is only meaningful for a treatment the catalog marks as
    per-surface; everything else ignores it.
    """

    catalog_item_id: UUID
    tooth_numbers: list[int] = Field(default_factory=list)
    surfaces: list[str] | None = None
    phase: TreatmentPhase | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AddCatalogItemsRequest(BaseModel):
    """Add treatments picked one by one from the catalog.

    The other half of "start from a template": a plan is often a known shape
    *plus* the treatments this patient needs on named teeth, and until this
    endpoint those could only be added after the plan existed, from the
    chart.

    Same tooth rule as a template, applied per line — a per-tooth treatment
    is created once per tooth listed, whole-mouth ones once — because it is
    the same code path underneath.
    """

    lines: list[PlanLineInput] = Field(min_length=1)


class SkippedTemplateLine(BaseModel):
    """A template line that could not be applied.

    ``reason`` is ``not_in_catalog``: the clinic does not offer that
    treatment. Not an error — a clinic that refers its orthodontics out still
    wants the rest of the plan — but never silent.
    """

    name: str
    reason: str


class ApplyTemplateResult(BaseModel):
    items: list[PlannedTreatmentItemResponse] = Field(default_factory=list)
    skipped: list[SkippedTemplateLine] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Proposals from the chart
# ---------------------------------------------------------------------------


class PlanProposal(BaseModel):
    """A charted finding with the treatment proposed for it.

    ``suggested_catalog_item`` is null when the clinic's catalog has nothing
    matching — the finding is still listed, because the dentist may want to
    know it is unaddressed even if the app cannot propose anything.
    """

    finding_id: UUID
    clinical_type: str
    tooth_number: int | None = None
    surfaces: list[str] | None = None
    suggested_catalog_item: CatalogItemBrief | None = None


class AcceptProposalsRequest(BaseModel):
    finding_ids: list[UUID] = Field(min_length=1)


class DismissFindingsRequest(BaseModel):
    """Findings this plan is deliberately not answering.

    Sent by the builder for the seeded lines the dentist deleted, so the
    plan's own proposals list does not offer them straight back.
    """

    finding_ids: list[UUID] = Field(min_length=1)


# Media attachment schemas live in the ``media`` module since issue #55 —
# call ``POST /api/v1/media/attachments`` with ``owner_type='plan_item'``
# instead of the previous ``POST /treatment-plans/items/{id}/media``.
#
# Clinical-note schemas moved to the ``clinical_notes`` module — see issue #60.


class PlanHistoryEntryResponse(BaseModel):
    """One line of the plan's history, shaped for the panel that shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: str
    from_status: str | None = None
    to_status: str | None = None
    payload: dict | None = None
    actor_name: str | None = None
    created_at: datetime


class PlanPermissionsResponse(BaseModel):
    """What the caller may do with this plan.

    Sent alongside the history so the client does not have to reproduce
    the "administrator or assigned professional" rule — which depends on
    a licence-number match it cannot see — to decide whether to draw the
    Reopen button.
    """

    can_reopen: bool
    can_edit: bool


TreatmentPlanDetailResponse.model_rebuild()


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------


class PrescriptionCreate(BaseModel):
    """A prescription for one plan treatment."""

    body: str = Field(..., min_length=1, max_length=5000)
    # The doctor who signs it. The UI defaults to the treatment's assigned
    # professional and lets the user pick another.
    professional_id: UUID


class PrescriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    plan_item_id: UUID | None
    treatment_label: str | None
    professional_id: UUID | None
    professional_name: str
    professional_license: str | None
    body: str
    issued_by: UUID | None
    created_at: datetime
