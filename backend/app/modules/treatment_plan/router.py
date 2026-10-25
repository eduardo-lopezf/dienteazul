"""Treatment plan module API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .errors import service_error, treatment_plan_error
from .models import PlanTemplate
from .prescriptions import PrescriptionService, ProfessionalNotFoundError
from .proposals import PlanProposalService
from .schemas import (
    AcceptProposalsRequest,
    AddCatalogItemsRequest,
    ApplyTemplateRequest,
    ApplyTemplateResult,
    BudgetBrief,
    ClosePlanRequest,
    CompleteItemRequest,
    CompleteSessionRequest,
    ContactLogRequest,
    DismissFindingsRequest,
    LinkBudgetRequest,
    PipelineRow,
    PlanHistoryEntryResponse,
    PlannedTreatmentItemCreate,
    PlannedTreatmentItemResponse,
    PlannedTreatmentItemUpdate,
    PlanNextAction,
    PlanPermissionsResponse,
    PlanProposal,
    PlanTemplateCreate,
    PlanTemplateFromPlanRequest,
    PlanTemplateResponse,
    PlanTemplateSpecialty,
    PlanTemplateUpdate,
    PrescriptionCreate,
    PrescriptionResponse,
    ReorderItemsRequest,
    SessionInput,
    TreatmentPlanCreate,
    TreatmentPlanDetailResponse,
    TreatmentPlanResponse,
    TreatmentPlanStatusUpdate,
    TreatmentPlanUpdate,
    UpdateSessionRequest,
)
from .service import (
    CONSENT_REQUIRED,
    InformedConsentRequiredError,
    PlanHasCollectionsError,
    PlanLockedError,
    TreatmentPlanService,
    stewards_of,
)
from .templates_service import PlanLine, PlanTemplateService, TemplateNeedsTeethError

router = APIRouter()


# -----------------------------------------------------------------------------
# Bandeja de planes (pipeline view) — declared FIRST so the literal
# ``/treatment-plans/pipeline`` path matches before any ``/{plan_id}``
# pattern below it. FastAPI resolves routes in registration order.
# -----------------------------------------------------------------------------


PIPELINE_TABS = {
    "en_curso",
    "por_presupuestar",
    "esperando_paciente",
    "sin_cita",
    "sin_proxima_cita",
    "cerrados",
}


@router.get(
    "/treatment-plans/pipeline",
    response_model=PaginatedApiResponse[PipelineRow],
)
async def list_pipeline(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    tab: str = Query(..., description="One of: " + ", ".join(sorted(PIPELINE_TABS))),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    doctor_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, description="Free-text search"),
) -> PaginatedApiResponse[PipelineRow]:
    """Bandeja de planes (cross-module pipeline view).

    The endpoint joins ``treatment_plans``, ``budgets`` and
    ``appointments`` directly via SQL because all three are declared in
    treatment_plan's manifest.depends. Filtering happens in SQL by tab.
    """
    if tab not in PIPELINE_TABS:
        raise treatment_plan_error(
            "treatment_plan.pipeline.invalid_tab", detail=f"Unknown tab '{tab}'"
        )

    rows, total = await TreatmentPlanService.list_pipeline(
        db,
        clinic_id=ctx.clinic_id,
        tab=tab,
        page=page,
        page_size=page_size,
        doctor_id=doctor_id,
        search=q,
    )
    return PaginatedApiResponse(
        data=rows,
        total=total,
        page=page,
        page_size=page_size,
    )


# -----------------------------------------------------------------------------
# Treatment Plans CRUD
# -----------------------------------------------------------------------------


@router.get("/treatment-plans", response_model=PaginatedApiResponse[TreatmentPlanResponse])
async def list_treatment_plans(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    patient_id: UUID | None = None,
    status: list[str] | None = Query(default=None),
    search: str | None = Query(default=None, description="Plan number or patient name"),
) -> PaginatedApiResponse[TreatmentPlanResponse]:
    """List treatment plans with pagination and filters.

    ``search`` was being sent by the "Todos" tab long before it existed
    here; FastAPI drops unknown query parameters silently, so the box
    filtered nothing and the bug looked like a front-end one.
    """
    plans, total = await TreatmentPlanService.list(
        db,
        ctx.clinic_id,
        page,
        page_size,
        patient_id=patient_id,
        status=status,
        search=search,
    )
    # Compute counts and totals from loaded items
    for p in plans:
        items = p.items or []
        p.item_count = len(items)
        p.completed_count = sum(1 for i in items if i.status == "completed")
        p.total = sum(
            float(i.treatment.price_snapshot) if i.treatment and i.treatment.price_snapshot else 0
            for i in items
        )
    return PaginatedApiResponse(
        data=[TreatmentPlanResponse.model_validate(p) for p in plans],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/treatment-plans/patient/{patient_id}/proposals",
    response_model=ApiResponse[list[PlanProposal]],
)
async def list_patient_proposals(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[PlanProposal]]:
    """Charted findings for a patient who has no plan yet.

    The sibling of ``/treatment-plans/{plan_id}/proposals``, for the one
    moment that endpoint cannot serve: the builder, where the plan does not
    exist until the dentist presses *Crear*. Same findings, same clinical
    mapping; only the way in is different.

    Declared above the ``/{plan_id}`` routes for the reason given at the top
    of this file — ``patient`` would otherwise be parsed as a plan id.
    """
    proposals = await PlanProposalService.for_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=[PlanProposal.model_validate(p) for p in proposals])


@router.get(
    "/treatment-plans/patient/{patient_id}",
    response_model=PaginatedApiResponse[TreatmentPlanResponse],
)
async def list_patient_plans(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedApiResponse[TreatmentPlanResponse]:
    """List treatment plans for a specific patient."""
    plans, total = await TreatmentPlanService.list(
        db, ctx.clinic_id, page, page_size, patient_id=patient_id
    )
    # Compute counts and totals from loaded items
    for p in plans:
        items = p.items or []
        p.item_count = len(items)
        p.completed_count = sum(1 for i in items if i.status == "completed")
        p.total = sum(
            float(i.treatment.price_snapshot) if i.treatment and i.treatment.price_snapshot else 0
            for i in items
        )
    return PaginatedApiResponse(
        data=[TreatmentPlanResponse.model_validate(p) for p in plans],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/treatment-plans/{plan_id}",
    response_model=ApiResponse[TreatmentPlanDetailResponse],
)
async def get_treatment_plan(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanDetailResponse]:
    """Get a treatment plan with full details."""
    plan = await TreatmentPlanService.get(db, ctx.clinic_id, plan_id)
    if not plan:
        raise treatment_plan_error("treatment_plan.plan.not_found")
    response = TreatmentPlanDetailResponse.model_validate(plan)
    # Not part of the ORM row: computed here so the screen can say what
    # to do next without a second round trip and a second set of rules.
    next_action = await TreatmentPlanService.next_action(db, ctx.clinic_id, plan)
    response.next_action = PlanNextAction(**next_action) if next_action else None
    response.informed_consent_missing = await TreatmentPlanService.informed_consent_missing(
        db, ctx.clinic_id, plan
    )
    response.unbudgeted_count = len(
        await TreatmentPlanService.unbudgeted_items(db, ctx.clinic_id, plan)
    )
    response.other_budgets = [
        BudgetBrief.model_validate(b)
        for b in await TreatmentPlanService.other_live_budgets(db, ctx.clinic_id, plan)
    ]
    return ApiResponse(data=response)


@router.post(
    "/treatment-plans",
    response_model=ApiResponse[TreatmentPlanResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_treatment_plan(
    data: TreatmentPlanCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Create a new treatment plan."""
    try:
        plan = await TreatmentPlanService.create(db, ctx.clinic_id, ctx.user_id, data.model_dump())
        return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))
    except ValueError as e:
        raise service_error(e, resource="plan") from e


@router.put(
    "/treatment-plans/{plan_id}",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def update_treatment_plan(
    plan_id: UUID,
    data: TreatmentPlanUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Update a treatment plan."""
    try:
        plan = await TreatmentPlanService.update(
            db,
            ctx.clinic_id,
            plan_id,
            data.model_dump(exclude_unset=True),
            user_id=ctx.user_id,
        )
    except ValueError as e:
        raise service_error(e, resource="plan") from e
    if not plan:
        raise treatment_plan_error("treatment_plan.plan.not_found")
    return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))


@router.patch(
    "/treatment-plans/{plan_id}/status",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def update_plan_status(
    plan_id: UUID,
    data: TreatmentPlanStatusUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Change treatment plan status."""
    try:
        plan = await TreatmentPlanService.update_status(
            db, ctx.clinic_id, plan_id, data.status, ctx.user_id
        )
        if not plan:
            raise treatment_plan_error("treatment_plan.plan.not_found")
        return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))
    except ValueError as e:
        raise service_error(e, resource="plan") from e


# -----------------------------------------------------------------------------
# Workflow transitions (confirm / reopen / close / reactivate)
# -----------------------------------------------------------------------------


@router.post(
    "/treatment-plans/{plan_id}/confirm",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def confirm_treatment_plan(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.confirm"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Doctor confirms the plan (``draft`` → ``pending``).

    Auto-creates the draft budget so reception can review and send.
    """
    try:
        plan = await TreatmentPlanService.confirm(db, ctx.clinic_id, plan_id, ctx.user_id)
    except InformedConsentRequiredError as e:
        # Its own status, so the screen can say what is missing and where
        # to get it instead of showing a generic refusal.
        raise treatment_plan_error(
            "treatment_plan.plan.consent_required", detail=CONSENT_REQUIRED
        ) from e
    except ValueError as e:
        raise service_error(e, resource="plan") from e
    return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))


@router.get(
    "/treatment-plans/{plan_id}/history",
    response_model=ApiResponse[dict],
)
async def get_plan_history(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    """The plan's change log, newest first, plus what the caller may do.

    Permissions ride along because the "administrator or assigned
    professional" rule turns on a licence-number match between accounts
    and directory profiles that the client cannot evaluate on its own.
    """
    plan = await TreatmentPlanService.get(db, ctx.clinic_id, plan_id)
    if not plan:
        raise treatment_plan_error("treatment_plan.plan.not_found")

    entries = await TreatmentPlanService.history(db, ctx.clinic_id, plan_id)

    is_admin = ctx.role == "admin"
    is_steward = is_admin or ctx.user_id in await stewards_of(db, ctx.clinic_id, plan)

    return ApiResponse(
        data={
            "entries": [
                PlanHistoryEntryResponse(
                    id=entry.id,
                    action=entry.action,
                    from_status=entry.from_status,
                    to_status=entry.to_status,
                    payload=entry.payload,
                    actor_name=(
                        f"{entry.actor.first_name} {entry.actor.last_name}".strip()
                        if entry.actor
                        else None
                    ),
                    created_at=entry.created_at,
                ).model_dump(mode="json")
                for entry in entries
            ],
            "permissions": PlanPermissionsResponse(
                can_reopen=is_steward and plan.status in ("pending", "active"),
                can_edit=is_steward,
            ).model_dump(),
        }
    )


@router.post(
    "/treatment-plans/{plan_id}/reopen",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def reopen_treatment_plan(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Reopen a plan back to ``draft`` and cancel its budget.

    Narrower than the permission alone: reopening throws away a budget
    the patient may already have seen, so it is limited to an
    administrator or a professional the case is actually assigned to —
    the plan's doctor or any of the specialists on its items. Rights
    follow the assignment, so handing the plan to someone else hands
    them over too.
    """
    plan = await TreatmentPlanService.get(db, ctx.clinic_id, plan_id)
    if not plan:
        raise treatment_plan_error("treatment_plan.plan.not_found")

    if ctx.role != "admin":
        stewards = await stewards_of(db, ctx.clinic_id, plan)
        if ctx.user_id not in stewards:
            raise treatment_plan_error("treatment_plan.plan.reopen_forbidden")

    try:
        plan = await TreatmentPlanService.reopen(db, ctx.clinic_id, plan_id, ctx.user_id)
    except ValueError as e:
        raise service_error(e, resource="plan") from e
    return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))


@router.post(
    "/treatment-plans/{plan_id}/close",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def close_treatment_plan(
    plan_id: UUID,
    data: ClosePlanRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.close"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Move the plan to terminal ``closed`` state with a reason.

    Cancelling (``cancelled_by_clinic``) a plan the patient paid into is
    refused with 409; any other reason still closes it.
    """
    try:
        plan = await TreatmentPlanService.close(
            db,
            ctx.clinic_id,
            plan_id,
            ctx.user_id,
            closure_reason=data.closure_reason,
            closure_note=data.closure_note,
        )
    except PlanHasCollectionsError as e:
        raise treatment_plan_error("treatment_plan.plan.has_collections", detail=e.CODE) from e
    except ValueError as e:
        raise service_error(e, resource="plan") from e
    return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))


@router.post(
    "/treatment-plans/{plan_id}/reactivate",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def reactivate_treatment_plan(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.reactivate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Revive a closed plan back to ``draft`` for a fresh cycle."""
    try:
        plan = await TreatmentPlanService.reactivate(db, ctx.clinic_id, plan_id, ctx.user_id)
    except ValueError as e:
        raise service_error(e, resource="plan") from e
    return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))


@router.post(
    "/treatment-plans/{plan_id}/contact-log",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def log_plan_contact(
    plan_id: UUID,
    data: ContactLogRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Record a non-state-changing contact with the patient.

    The bandeja sorts ``Esperando paciente`` by ``last_contact`` so
    reception can prioritise calls. We persist the touchpoint via the
    plan's ``internal_notes`` for now (one-line append). A dedicated
    contact-log table is on the v2 backlog.
    """
    from datetime import UTC, datetime

    plan = await TreatmentPlanService.get(db, ctx.clinic_id, plan_id)
    if not plan:
        raise treatment_plan_error("treatment_plan.plan.not_found")
    timestamp = datetime.now(UTC).isoformat()
    line = f"[{timestamp}] {data.channel} by {ctx.user_id}"
    if data.note:
        line += f" — {data.note.strip()}"
    plan.internal_notes = f"{plan.internal_notes}\n{line}".strip() if plan.internal_notes else line
    await db.flush()


@router.delete("/treatment-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_treatment_plan(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft delete (archive) a treatment plan — refused once it holds money."""
    try:
        deleted = await TreatmentPlanService.delete(db, ctx.clinic_id, plan_id, ctx.user_id)
    except PlanHasCollectionsError as e:
        raise treatment_plan_error("treatment_plan.plan.has_collections", detail=e.CODE) from e
    if not deleted:
        raise treatment_plan_error("treatment_plan.plan.not_found")


# -----------------------------------------------------------------------------
# Plan Items
# -----------------------------------------------------------------------------


@router.post(
    "/treatment-plans/{plan_id}/items",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_plan_item(
    plan_id: UUID,
    data: PlannedTreatmentItemCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Add a treatment item to the plan."""
    try:
        item = await TreatmentPlanService.add_item(
            db, ctx.clinic_id, plan_id, data.model_dump(), user_id=ctx.user_id
        )
        return ApiResponse(data=PlannedTreatmentItemResponse.model_validate(item))
    except PlanLockedError as e:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(e)) from e
    except ValueError as e:
        raise service_error(e, resource="item") from e


@router.put(
    "/treatment-plans/{plan_id}/items/{item_id}",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def update_plan_item(
    plan_id: UUID,
    item_id: UUID,
    data: PlannedTreatmentItemUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Update a planned treatment item."""
    try:
        item = await TreatmentPlanService.update_item(
            db, ctx.clinic_id, plan_id, item_id, data.model_dump(exclude_unset=True)
        )
    except PlanLockedError as e:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(e)) from e
    except ValueError as e:
        raise service_error(e, resource="item") from e
    if not item:
        raise treatment_plan_error("treatment_plan.item.not_found")
    return ApiResponse(data=PlannedTreatmentItemResponse.model_validate(item))


@router.delete(
    "/treatment-plans/{plan_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_plan_item(
    plan_id: UUID,
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove an item from the plan."""
    try:
        removed = await TreatmentPlanService.remove_item(
            db, ctx.clinic_id, plan_id, item_id, ctx.user_id
        )
    except PlanLockedError as e:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(e)) from e
    if not removed:
        raise treatment_plan_error("treatment_plan.item.not_found")


@router.patch(
    "/treatment-plans/{plan_id}/items/reorder",
    response_model=ApiResponse[TreatmentPlanDetailResponse],
)
async def reorder_plan_items(
    plan_id: UUID,
    data: ReorderItemsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanDetailResponse]:
    """Reorder all items of a plan in a single atomic call.

    `item_ids` MUST cover exactly the plan's current items. Returns the full plan
    with items in the new order so the caller doesn't need a second round-trip.
    """
    try:
        items = await TreatmentPlanService.reorder_items(db, ctx.clinic_id, plan_id, data.item_ids)
    except PlanLockedError as e:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(e)) from e
    except ValueError as e:
        raise service_error(e, resource="plan") from e
    if items is None:
        raise treatment_plan_error("treatment_plan.plan.not_found")

    plan = await TreatmentPlanService.get(db, ctx.clinic_id, plan_id)
    if not plan:
        raise treatment_plan_error("treatment_plan.plan.not_found")
    return ApiResponse(data=TreatmentPlanDetailResponse.model_validate(plan))


@router.patch(
    "/treatment-plans/{plan_id}/items/{item_id}/complete",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def complete_plan_item(
    plan_id: UUID,
    item_id: UUID,
    data: CompleteItemRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Mark a treatment item as completed."""
    item = await TreatmentPlanService.complete_item(
        db,
        ctx.clinic_id,
        plan_id,
        item_id,
        ctx.user_id,
        data.completed_without_appointment,
        data.notes,
    )
    if not item:
        raise treatment_plan_error("treatment_plan.item.not_found")
    return ApiResponse(data=PlannedTreatmentItemResponse.model_validate(item))


@router.patch(
    "/treatment-plans/{plan_id}/items/{item_id}/reopen",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def reopen_plan_item(
    plan_id: UUID,
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Undo a completion: the item is pending again and its charge is dropped.

    Same permission as completing it — this is the way back from that
    click, not a separate privilege.
    """
    try:
        item = await TreatmentPlanService.reopen_item(
            db, ctx.clinic_id, plan_id, item_id, ctx.user_id
        )
    except ValueError as exc:
        raise service_error(exc, resource="item") from exc
    if not item:
        raise treatment_plan_error("treatment_plan.item.not_found")
    return ApiResponse(data=PlannedTreatmentItemResponse.model_validate(item))


# -----------------------------------------------------------------------------
# Plan item sessions (multi-session billing)
# -----------------------------------------------------------------------------


def _item_response_or_404(item) -> ApiResponse[PlannedTreatmentItemResponse]:
    if not item:
        raise treatment_plan_error("treatment_plan.item.not_found")
    return ApiResponse(data=PlannedTreatmentItemResponse.model_validate(item))


@router.patch(
    "/treatment-plans/{plan_id}/items/{item_id}/sessions/{session_id}/complete",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def complete_item_session(
    plan_id: UUID,
    item_id: UUID,
    session_id: UUID,
    data: CompleteSessionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Mark one session of a plan item as completed."""
    try:
        item = await TreatmentPlanService.complete_session(
            db,
            ctx.clinic_id,
            plan_id,
            item_id,
            session_id,
            ctx.user_id,
            data.completed_without_appointment,
            data.notes,
        )
    except ValueError as exc:
        raise service_error(exc, resource="session") from exc
    return _item_response_or_404(item)


@router.patch(
    "/treatment-plans/{plan_id}/items/{item_id}/sessions/{session_id}/cancel",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def cancel_item_session(
    plan_id: UUID,
    item_id: UUID,
    session_id: UUID,
    data: CompleteSessionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Mark a session as cancelled (no earned entry will be generated)."""
    try:
        item = await TreatmentPlanService.cancel_session(
            db, ctx.clinic_id, plan_id, item_id, session_id, ctx.user_id, data.notes
        )
    except ValueError as exc:
        raise service_error(exc, resource="session") from exc
    return _item_response_or_404(item)


@router.put(
    "/treatment-plans/{plan_id}/items/{item_id}/sessions/{session_id}",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def update_item_session(
    plan_id: UUID,
    item_id: UUID,
    session_id: UUID,
    data: UpdateSessionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Edit label / amount / notes on a pending session."""
    try:
        item = await TreatmentPlanService.update_session(
            db,
            ctx.clinic_id,
            plan_id,
            item_id,
            session_id,
            data.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise service_error(exc, resource="session") from exc
    return _item_response_or_404(item)


@router.post(
    "/treatment-plans/{plan_id}/items/{item_id}/sessions",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_item_session(
    plan_id: UUID,
    item_id: UUID,
    data: SessionInput,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Append a new session to a plan item (manual; outside catalog template)."""
    try:
        item = await TreatmentPlanService.add_session_manual(
            db,
            ctx.clinic_id,
            plan_id,
            item_id,
            data.model_dump(),
        )
    except ValueError as exc:
        raise service_error(exc, resource="session") from exc
    return _item_response_or_404(item)


@router.delete(
    "/treatment-plans/{plan_id}/items/{item_id}/sessions/{session_id}",
    response_model=ApiResponse[PlannedTreatmentItemResponse],
)
async def delete_item_session(
    plan_id: UUID,
    item_id: UUID,
    session_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlannedTreatmentItemResponse]:
    """Remove a pending session. Returns the updated item."""
    try:
        item = await TreatmentPlanService.delete_session(
            db, ctx.clinic_id, plan_id, item_id, session_id
        )
    except ValueError as exc:
        raise service_error(exc, resource="session") from exc
    return _item_response_or_404(item)


# -----------------------------------------------------------------------------
# Budget Integration
# -----------------------------------------------------------------------------


@router.post(
    "/treatment-plans/{plan_id}/link-budget",
    response_model=ApiResponse[TreatmentPlanResponse],
)
async def link_budget_to_plan(
    plan_id: UUID,
    data: LinkBudgetRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentPlanResponse]:
    """Link an existing budget to the treatment plan."""
    try:
        plan = await TreatmentPlanService.link_budget(db, ctx.clinic_id, plan_id, data.budget_id)
        if not plan:
            raise treatment_plan_error("treatment_plan.plan.not_found")
        return ApiResponse(data=TreatmentPlanResponse.model_validate(plan))
    except ValueError as e:
        raise service_error(e, resource="budget") from e


@router.post(
    "/treatment-plans/{plan_id}/sync-budget",
    response_model=ApiResponse[dict],
)
async def sync_plan_with_budget(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    """Request synchronization of plan items with linked budget."""
    success = await TreatmentPlanService.request_budget_sync(db, ctx.clinic_id, plan_id)
    if not success:
        raise treatment_plan_error("treatment_plan.budget.not_linked")
    return ApiResponse(data={"synced": True})


# Generating a plan's budget and pricing its additions are `budget`
# endpoints now (`POST /api/v1/budget/plans/{plan_id}/budget` and
# `/addendum`): a budget is that module's to write (ADR 0042).


# Media attachment endpoints moved to the ``media`` module since issue #55.
# Use ``POST /api/v1/media/attachments`` with ``owner_type='plan_item'``.
#
# Clinical-notes endpoints moved to the ``clinical_notes`` module since
# issue #60 (``/api/v1/clinical_notes/*``).


# -----------------------------------------------------------------------------
# Plan templates
#
# Declared last, on their own ``/plan-templates`` prefix, so nothing here can
# shadow a ``/treatment-plans/{plan_id}`` pattern above.
# -----------------------------------------------------------------------------


async def _template_responses(
    db: AsyncSession, clinic_id: UUID, templates: list[PlanTemplate]
) -> list[PlanTemplateResponse]:
    """Templates as the API answers them, each with the discipline it belongs to."""
    specialties = await PlanTemplateService.specialties_by_key(db, clinic_id)
    responses = []
    for template in templates:
        response = PlanTemplateResponse.model_validate(template)
        specialty = specialties.get(template.key) if template.key else None
        if specialty is not None:
            response.specialty = PlanTemplateSpecialty.model_validate(specialty)
        responses.append(response)
    return responses


@router.get("/plan-templates", response_model=ApiResponse[list[PlanTemplateResponse]])
async def list_plan_templates(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> ApiResponse[list[PlanTemplateResponse]]:
    """Templates available when starting a plan. Reading needs only plans.read."""
    templates = await PlanTemplateService.list_templates(
        db, ctx.clinic_id, include_inactive=include_inactive
    )
    return ApiResponse(data=await _template_responses(db, ctx.clinic_id, templates))


@router.post(
    "/plan-templates",
    response_model=ApiResponse[PlanTemplateResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_plan_template(
    data: PlanTemplateCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.templates"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlanTemplateResponse]:
    try:
        template = await PlanTemplateService.create(
            db, ctx.clinic_id, ctx.user_id, data.model_dump()
        )
    except ValueError as exc:
        raise service_error(exc, resource="template") from exc
    await db.commit()
    reloaded = await PlanTemplateService.get(db, ctx.clinic_id, template.id)
    return ApiResponse(data=(await _template_responses(db, ctx.clinic_id, [reloaded]))[0])


@router.put("/plan-templates/{template_id}", response_model=ApiResponse[PlanTemplateResponse])
async def update_plan_template(
    template_id: UUID,
    data: PlanTemplateUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.templates"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlanTemplateResponse]:
    try:
        template = await PlanTemplateService.update(
            db, ctx.clinic_id, template_id, data.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise service_error(exc, resource="template") from exc
    if not template:
        raise treatment_plan_error("treatment_plan.template.not_found")
    await db.commit()
    reloaded = await PlanTemplateService.get(db, ctx.clinic_id, template_id)
    return ApiResponse(data=(await _template_responses(db, ctx.clinic_id, [reloaded]))[0])


@router.delete("/plan-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan_template(
    template_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.templates"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Hide a template. Soft delete — a curated shape is never dropped."""
    if not await PlanTemplateService.delete(db, ctx.clinic_id, template_id):
        raise treatment_plan_error("treatment_plan.template.not_found")
    await db.commit()


@router.post(
    "/plan-templates/from-plan/{plan_id}",
    response_model=ApiResponse[PlanTemplateResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_template_from_plan(
    plan_id: UUID,
    data: PlanTemplateFromPlanRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.templates"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PlanTemplateResponse]:
    """Save an existing plan as a reusable template. Teeth are dropped."""
    template = await PlanTemplateService.create_from_plan(
        db, ctx.clinic_id, ctx.user_id, plan_id, data.name, data.description
    )
    if not template:
        raise treatment_plan_error("treatment_plan.plan.not_found")
    await db.commit()
    reloaded = await PlanTemplateService.get(db, ctx.clinic_id, template.id)
    return ApiResponse(data=(await _template_responses(db, ctx.clinic_id, [reloaded]))[0])


@router.post(
    "/treatment-plans/{plan_id}/apply-template",
    response_model=ApiResponse[ApplyTemplateResult],
    status_code=status.HTTP_201_CREATED,
)
async def apply_plan_template(
    plan_id: UUID,
    data: ApplyTemplateRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ApplyTemplateResult]:
    """Append a template's treatments to a plan.

    Returns what was created and what was left out — a line whose treatment
    the clinic does not offer is skipped, never silently.

    422 when the template has per-tooth treatments and no teeth were given —
    the detail names them, so the UI can ask for the right thing.
    """
    try:
        result = await PlanTemplateService.apply(
            db,
            ctx.clinic_id,
            ctx.user_id,
            plan_id,
            data.template_id,
            data.tooth_numbers,
            data.excluded_template_item_ids,
        )
    except TemplateNeedsTeethError as exc:
        raise treatment_plan_error(
            "treatment_plan.template.needs_teeth",
            fields={"treatments": exc.item_names},
        ) from exc
    except PlanLockedError as exc:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(exc)) from exc
    except ValueError as exc:
        raise service_error(exc, resource="template") from exc

    await db.commit()
    return ApiResponse(
        data=ApplyTemplateResult(
            items=[PlannedTreatmentItemResponse.model_validate(i) for i in result.items],
            skipped=[{"name": s.name, "reason": s.reason} for s in result.skipped],
        )
    )


@router.post(
    "/treatment-plans/{plan_id}/catalog-items",
    response_model=ApiResponse[ApplyTemplateResult],
    status_code=status.HTTP_201_CREATED,
)
async def add_catalog_items_to_plan(
    plan_id: UUID,
    data: AddCatalogItemsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ApplyTemplateResult]:
    """Add treatments picked one by one from the catalog.

    Same contract as ``apply-template`` — it is the same code underneath —
    including the 422 that names the treatments still waiting for a tooth.
    """
    try:
        result = await PlanTemplateService.add_catalog_items(
            db,
            ctx.clinic_id,
            ctx.user_id,
            plan_id,
            [
                PlanLine(
                    catalog_item_id=line.catalog_item_id,
                    tooth_numbers=line.tooth_numbers,
                    surfaces=line.surfaces,
                    phase=line.phase,
                    notes=line.notes,
                )
                for line in data.lines
            ],
        )
    except TemplateNeedsTeethError as exc:
        raise treatment_plan_error(
            "treatment_plan.template.needs_teeth",
            fields={"treatments": exc.item_names},
        ) from exc
    except PlanLockedError as exc:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(exc)) from exc
    except ValueError as exc:
        raise service_error(exc, resource="template") from exc

    await db.commit()
    return ApiResponse(
        data=ApplyTemplateResult(
            items=[PlannedTreatmentItemResponse.model_validate(i) for i in result.items],
            skipped=[{"name": s.name, "reason": s.reason} for s in result.skipped],
        )
    )


# -----------------------------------------------------------------------------
# Proposals from the chart
#
# The findings are already in the odontogram; retyping them as plan items is
# the most repetitive step of building a plan. These two endpoints read them
# and, on the dentist's word, turn the accepted ones into planned treatments.
# -----------------------------------------------------------------------------


@router.get(
    "/treatment-plans/{plan_id}/proposals",
    response_model=ApiResponse[list[PlanProposal]],
)
async def list_plan_proposals(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[PlanProposal]]:
    """Charted findings on this patient that nothing is planned for yet."""
    proposals = await PlanProposalService.list_proposals(db, ctx.clinic_id, plan_id)
    if proposals is None:
        raise treatment_plan_error("treatment_plan.plan.not_found")
    return ApiResponse(data=[PlanProposal.model_validate(p) for p in proposals])


@router.post(
    "/treatment-plans/{plan_id}/dismissed-findings",
    response_model=ApiResponse[dict],
)
async def dismiss_plan_findings(
    plan_id: UUID,
    data: DismissFindingsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    """Record findings this plan does not answer, so it stops proposing them.

    The builder calls this for the seeded lines the dentist deleted. The
    findings themselves are untouched — the chart keeps showing the caries,
    and the patient's next plan proposes it again.
    """
    dismissed = await PlanProposalService.dismiss(
        db, ctx.clinic_id, ctx.user_id, plan_id, data.finding_ids
    )
    await db.commit()
    return ApiResponse(data={"dismissed": dismissed})


@router.post(
    "/treatment-plans/{plan_id}/proposals",
    response_model=ApiResponse[list[PlannedTreatmentItemResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def accept_plan_proposals(
    plan_id: UUID,
    data: AcceptProposalsRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[PlannedTreatmentItemResponse]]:
    """Add a planned treatment for each accepted finding.

    The findings themselves are untouched — the chart keeps showing the caries
    until it is actually treated.
    """
    try:
        items = await PlanProposalService.accept(
            db, ctx.clinic_id, ctx.user_id, plan_id, data.finding_ids
        )
    except PlanLockedError as exc:
        raise treatment_plan_error("treatment_plan.plan.locked", detail=str(exc)) from exc
    except ValueError as exc:
        raise service_error(exc, resource="proposal") from exc

    await db.commit()
    return ApiResponse(data=[PlannedTreatmentItemResponse.model_validate(i) for i in items])


# -----------------------------------------------------------------------------
# Prescriptions
#
# Written from a treatment's detail dialog and printed straight away. The row
# keeps what was printed, so a reprint gives the same document.
# -----------------------------------------------------------------------------


@router.get(
    "/treatment-plans/{plan_id}/items/{item_id}/prescriptions",
    response_model=ApiResponse[list[PrescriptionResponse]],
)
async def list_item_prescriptions(
    plan_id: UUID,
    item_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.prescriptions.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[PrescriptionResponse]]:
    """Prescriptions written for one plan treatment, newest first."""
    rows = await PrescriptionService.list_for_item(db, ctx.clinic_id, plan_id, item_id)
    if rows is None:
        raise treatment_plan_error("treatment_plan.item.not_found")
    return ApiResponse(data=[PrescriptionResponse.model_validate(r) for r in rows])


@router.post(
    "/treatment-plans/{plan_id}/items/{item_id}/prescriptions",
    response_model=ApiResponse[PrescriptionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_item_prescription(
    plan_id: UUID,
    item_id: UUID,
    data: PrescriptionCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.prescriptions.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PrescriptionResponse]:
    """Issue a prescription signed by ``professional_id``.

    The doctor's name and licence are copied onto the prescription.
    """
    try:
        prescription = await PrescriptionService.create(
            db,
            ctx.clinic_id,
            ctx.user_id,
            plan_id,
            item_id,
            data.body,
            data.professional_id,
        )
    except ProfessionalNotFoundError as exc:
        raise service_error(exc, resource="prescription") from exc
    if prescription is None:
        raise treatment_plan_error("treatment_plan.item.not_found")
    await db.commit()
    return ApiResponse(data=PrescriptionResponse.model_validate(prescription))


@router.get("/prescriptions/{prescription_id}/pdf")
async def prescription_pdf(
    prescription_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.prescriptions.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    locale: str = Query(default="es", pattern="^(es|en)$"),
) -> Response:
    """The prescription as a print-ready PDF (served inline)."""
    prescription = await PrescriptionService.get(db, ctx.clinic_id, prescription_id)
    if prescription is None:
        raise treatment_plan_error("treatment_plan.prescription.not_found")
    pdf = await PrescriptionService.render_pdf(db, prescription, locale)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="receta_{prescription.id.hex[:8]}.pdf"'},
    )
