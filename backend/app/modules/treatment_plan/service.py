"""Treatment plan module service layer."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import (
    Collections,
    PlanBudgets,
    PlanConsents,
    ProfessionalDirectory,
    provider,
)
from app.core.events import event_bus
from app.core.events.types import EventType
from app.core.utils.search import FOLD_FROM, FOLD_TO, search_tokens
from app.modules.odontogram.models import Treatment
from app.modules.patients.models import Patient

from .models import (
    PlannedTreatmentItem,
    PlannedTreatmentItemSession,
    TreatmentPlan,
    TreatmentPlanHistory,
)


async def _validate_professional_in_clinic(
    db: AsyncSession, clinic_id: UUID, professional_id: UUID
) -> None:
    """Confirm ``professional_id`` is an active dentist/hygienist in ``clinic_id``.

    Used when assigning a doctor to a plan item (or the plan itself) to
    avoid leaking professionals across tenants or assigning a non-clinical
    profile. Raises ``ValueError`` so the router maps it to a 400 response,
    in line with the other validation errors in this module.
    """
    # Asked of the directory's contract, not read from its table
    # (ADR 0039). With the Professionals App off nobody can be assigned.
    directory = provider(ProfessionalDirectory)
    if directory is None:
        raise ValueError(PROFESSIONALS_UNAVAILABLE)
    if not await directory.is_bookable(db, clinic_id, professional_id):
        raise ValueError("Invalid professional for this clinic")


logger = logging.getLogger(__name__)

PROFESSIONALS_UNAVAILABLE = "Professionals are not available — nobody can be assigned"
BUDGETS_UNAVAILABLE = "Budgets are not available — a plan cannot be linked to one"


def _treatment_loader() -> selectinload:
    """Eager-load the Treatment (with teeth + catalog_item + its category).

    The ``category`` chain is loaded so consumers of the
    ``treatment_plan.treatment_completed`` event get the
    ``treatment_category_key`` snapshot without a follow-up query
    (issue #62, recalls).
    """
    from app.modules.catalog.models import TreatmentCatalogItem

    return selectinload(PlannedTreatmentItem.treatment).options(
        selectinload(Treatment.teeth),
        selectinload(Treatment.catalog_item).selectinload(TreatmentCatalogItem.category),
    )


def _item_with_sessions_loader() -> list:
    """Eager-load both treatment chain and sessions for a plan item."""
    return [
        _treatment_loader(),
        selectinload(PlannedTreatmentItem.sessions),
    ]


def _snapshot_sessions_from_catalog(
    item: PlannedTreatmentItem,
    treatment: Treatment,
) -> list[PlannedTreatmentItemSession]:
    """Build the session rows for a newly added plan item.

    Pulls the template from ``catalog_item.sessions`` when present;
    otherwise emits a single session worth ``treatment.price_snapshot``.
    When ``price_snapshot`` differs from the catalog's ``default_price``
    (e.g. per_tooth strategy multiplying the unit price), session amounts
    are scaled proportionally so the per-session weights survive.
    Returned rows are appended to ``item.sessions`` by the caller.
    """
    catalog_item = getattr(treatment, "catalog_item", None)
    catalog_sessions = getattr(catalog_item, "sessions", None) if catalog_item else None
    treatment_total = (
        Decimal(str(treatment.price_snapshot))
        if treatment.price_snapshot is not None
        else Decimal("0")
    )

    if not catalog_sessions:
        return [
            PlannedTreatmentItemSession(
                sequence=1,
                label=None,
                amount=treatment_total,
                status="pending",
            )
        ]

    catalog_total = sum(
        (Decimal(str(s.default_price)) for s in catalog_sessions),
        Decimal("0"),
    )
    rows: list[PlannedTreatmentItemSession] = []
    if catalog_total > 0 and treatment_total > 0 and catalog_total != treatment_total:
        # Scale per-session amounts to the actual treatment total.
        scale = treatment_total / catalog_total
        scaled = [
            (Decimal(str(s.default_price)) * scale).quantize(Decimal("0.01"))
            for s in catalog_sessions
        ]
        # Adjust last session to absorb rounding drift so Σ matches exactly.
        delta = treatment_total - sum(scaled, Decimal("0"))
        scaled[-1] = scaled[-1] + delta
        amounts = scaled
    else:
        amounts = [Decimal(str(s.default_price)) for s in catalog_sessions]

    for idx, (cs, amount) in enumerate(zip(catalog_sessions, amounts, strict=True), start=1):
        label = None
        if cs.labels:
            label = cs.labels.get("es") or cs.labels.get("en") or next(iter(cs.labels.values()))
        rows.append(
            PlannedTreatmentItemSession(
                sequence=idx,
                label=label,
                amount=amount,
                status="pending",
            )
        )
    return rows


# Allowed status transitions for ``TreatmentPlan``. See ADR 0006 and
# docs/workflows/plan-budget-flow-tech-plan.md §3.1 for the model.
#
#   draft     ──confirm──► pending ──accept──► active ──complete──► completed
#                            │                    │
#                            │ rejected/expired   │ cancelled by clinic
#                            ▼                    ▼
#                                       closed (closure_reason)
#                                          │
#                                          └── reactivate ──► draft
VALID_PLAN_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending", "closed"},
    "pending": {"active", "draft", "closed"},
    "active": {"completed", "closed"},
    "completed": {"archived"},
    "closed": {"draft"},
    "archived": set(),
}

VALID_CLOSURE_REASONS: set[str] = {
    "rejected_by_patient",
    "expired",
    "cancelled_by_clinic",
    "patient_abandoned",
    "other",
}


class InformedConsentRequiredError(ValueError):
    """The clinic asks for a signed informed consent before a plan is
    confirmed, and this plan has none."""


#: What the API answers (409) when that is why a plan was not confirmed.
CONSENT_REQUIRED = "informed_consent_required"


class PlanLockedError(ValueError):
    """Raised when a mutation is attempted on a plan locked by an active budget."""


class PlanHasCollectionsError(ValueError):
    """The patient has paid into this plan, so it can only be closed.

    Deleting it would take its budgets with it, and cancelling it says the
    clinic called the work off — neither is true of a plan somebody paid
    for. The router answers 409 with ``PLAN_HAS_COLLECTIONS`` so the client
    can say so in its own words.
    """

    CODE = "PLAN_HAS_COLLECTIONS"

    def __init__(self) -> None:
        super().__init__(self.CODE)


# Closing for this reason is the "cancel" of the UI, and is refused on a
# plan with money in it; every other reason is an ordinary close.
CANCEL_CLOSURE_REASON = "cancelled_by_clinic"


def _item_label(item: PlannedTreatmentItem) -> str | None:
    """Human name of the treatment behind a plan item, for the history.

    Best-effort: the history is read by people, so a missing catalogue
    name is better recorded as nothing than as a UUID nobody can place.
    Never raises — a lazy relationship that is not loaded simply yields
    ``None`` rather than taking the surrounding write down with it.
    """
    try:
        treatment = item.treatment
        catalog_item = treatment.catalog_item if treatment else None
        if catalog_item is None:
            return None
        names = catalog_item.names or {}
        return names.get("es") or names.get("en")
    except Exception:  # pragma: no cover - defensive, see docstring
        return None


async def stewards_of(db: AsyncSession, clinic_id: UUID, plan: TreatmentPlan) -> set[UUID]:
    """User ids allowed to edit this plan besides an administrator.

    A plan can have several specialists — one on the plan and one on each
    item, since a case is often split between an orthodontist, a surgeon
    and whoever does the restorative work — so the set is built from all
    of them, not just the plan header.

    Resolving a professional to an account is the soft part. A
    ``Professional`` is a directory profile with no ``user_id``: the
    module keeps it independent of any product account on purpose (see
    the module CLAUDE.md). The only bridge that exists is the licence
    number — ``users.professional_id`` is free text holding a colegiado
    number, and it happens to match ``professionals.license_number``. So
    a professional who has no account, or whose licence is blank on
    either side, simply resolves to nobody and the plan stays
    administrator-only, which is the rule reception asked for.

    Reassignment needs no bookkeeping: the set is derived from whoever is
    assigned *now*, so handing the plan to another professional hands
    over the rights with it.
    """
    professional_ids = {
        pid
        for pid in (
            plan.assigned_professional_id,
            *(item.assigned_professional_id for item in plan.items),
        )
        if pid is not None
    }
    if not professional_ids:
        return set()

    rows = await db.execute(
        sa_text(
            "SELECT u.id FROM users u "
            "JOIN professionals p ON p.license_number = u.professional_id "
            "WHERE p.id = ANY(:professional_ids) "
            "  AND p.clinic_id = :clinic_id "
            "  AND COALESCE(u.professional_id, '') <> '' "
            "  AND COALESCE(p.license_number, '') <> ''"
        ),
        {"professional_ids": list(professional_ids), "clinic_id": clinic_id},
    )
    return {row.id for row in rows}


async def _attach_budgets(db: AsyncSession, clinic_id: UUID, plans: list[TreatmentPlan]) -> None:
    """Put each plan's budget brief on ``plan.budget``.

    Asked of the ``PlanBudgets`` contract in one go (ADR 0039). With the
    Budgets App off every plan reads as having no budget: nothing is
    locked by one, nothing is waiting on one, and the links stay stored.
    """
    budgets = provider(PlanBudgets)
    ids = {plan.budget_id for plan in plans if plan.budget_id}
    briefs = await budgets.briefs(db, clinic_id, ids) if budgets and ids else {}
    for plan in plans:
        plan.budget = briefs.get(plan.budget_id) if plan.budget_id else None


def _is_plan_locked(plan: TreatmentPlan) -> bool:
    """A plan is locked once it has a non-cancelled budget attached.

    Rationale: generating/sending/accepting a budget turns the plan into a
    contract with the patient. Changing a line the patient agreed to — its
    price, its presence — would silently invalidate that contract, so those
    go through the explicit unlock flow (which cancels the budget).

    **Adding is exempt and does not consult this.** A treatment added to a
    confirmed plan alters none of the agreed lines; what it costs is priced
    separately (``unbudgeted_items``, and ``budget``'s ``price_additions``). Callers:
    ``update_item``, ``remove_item`` and ``reorder_items``.
    """
    if not plan.budget_id or plan.budget is None:
        return False
    return plan.budget.status != "cancelled"


class TreatmentPlanService:
    """Service for treatment plan operations."""

    # -------------------------------------------------------------------------
    # Plan Number Generation
    # -------------------------------------------------------------------------

    @staticmethod
    async def generate_plan_number(db: AsyncSession, clinic_id: UUID) -> str:
        """Generate a unique plan number for the clinic.

        One past the highest number of the year, not one past the count:
        counting breaks the moment a row is ever removed — the next number
        lands on a plan that exists and the insert fails on
        ``uq_treatment_plan_number``. Soft-deleted plans still hold their
        number, so they are counted in. Same rule as
        ``BudgetNumberService``.
        """
        year = datetime.now(UTC).year
        prefix = f"PLAN-{year}-"

        result = await db.execute(
            select(func.max(TreatmentPlan.plan_number)).where(
                TreatmentPlan.clinic_id == clinic_id,
                TreatmentPlan.plan_number.like(f"{prefix}%"),
            )
        )
        highest = result.scalar_one_or_none()
        try:
            sequence = int(highest.split("-")[-1]) + 1 if highest else 1
        except ValueError:
            sequence = 1

        return f"{prefix}{sequence:04d}"

    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------

    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        page: int = 1,
        page_size: int = 20,
        patient_id: UUID | None = None,
        status: str | list[str] | None = None,
        search: str | None = None,
    ) -> tuple[list[TreatmentPlan], int]:
        """List treatment plans with pagination and filters.

        ``search`` matches the plan number, the patient's name, or any
        combination of words from it, ignoring accents. It did not exist
        until now: the "Todos" tab sent a ``search`` parameter that
        FastAPI silently dropped, so typing in that box filtered nothing
        at all and the list looked broken rather than empty.
        """
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * page_size

        # Base query - exclude deleted
        base_where = [
            TreatmentPlan.clinic_id == clinic_id,
            TreatmentPlan.deleted_at.is_(None),
        ]

        if patient_id:
            base_where.append(TreatmentPlan.patient_id == patient_id)

        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            if len(statuses) == 1:
                base_where.append(TreatmentPlan.status == statuses[0])
            else:
                base_where.append(TreatmentPlan.status.in_(statuses))

        if search and (tokens := search_tokens(search)):
            # Both sides folded, so "Perez" finds "Pérez". The patient
            # join is a correlated EXISTS rather than a join on the main
            # query so the eager loads below keep their shape.
            folded_first = func.translate(Patient.first_name, FOLD_FROM, FOLD_TO)
            folded_last = func.translate(Patient.last_name, FOLD_FROM, FOLD_TO)
            for token in tokens:
                like = f"%{token}%"
                base_where.append(
                    or_(
                        func.translate(TreatmentPlan.plan_number, FOLD_FROM, FOLD_TO).ilike(like),
                        select(Patient.id)
                        .where(
                            Patient.id == TreatmentPlan.patient_id,
                            or_(folded_first.ilike(like), folded_last.ilike(like)),
                        )
                        .exists(),
                    )
                )

        # Count
        count_result = await db.execute(select(func.count(TreatmentPlan.id)).where(*base_where))
        total = count_result.scalar_one()

        # Query with relationships. The inner ``items → treatment``
        # chain was previously declared twice — once with
        # ``Treatment.teeth`` and once with ``Treatment.catalog_item``
        # — making SQLAlchemy issue two extra batch queries per page
        # instead of one. Collapsed into a single chain that loads
        # both grandchildren in the same step.
        query = (
            select(TreatmentPlan)
            .where(*base_where)
            .options(
                selectinload(TreatmentPlan.patient),
                selectinload(TreatmentPlan.items)
                .selectinload(PlannedTreatmentItem.treatment)
                .options(
                    selectinload(Treatment.teeth),
                    selectinload(Treatment.catalog_item),
                ),
                selectinload(TreatmentPlan.items).selectinload(PlannedTreatmentItem.sessions),
            )
            .order_by(TreatmentPlan.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(query)
        items = list(result.scalars().all())
        await _attach_budgets(db, clinic_id, items)

        return items, total

    @staticmethod
    async def get(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
    ) -> TreatmentPlan | None:
        """Get a single treatment plan with all relationships."""
        result = await db.execute(
            select(TreatmentPlan)
            .where(
                TreatmentPlan.id == plan_id,
                TreatmentPlan.clinic_id == clinic_id,
                TreatmentPlan.deleted_at.is_(None),
            )
            .options(
                selectinload(TreatmentPlan.patient),
                selectinload(TreatmentPlan.items)
                .selectinload(PlannedTreatmentItem.treatment)
                .selectinload(Treatment.teeth),
                selectinload(TreatmentPlan.items)
                .selectinload(PlannedTreatmentItem.treatment)
                .selectinload(Treatment.catalog_item),
                selectinload(TreatmentPlan.items).selectinload(PlannedTreatmentItem.sessions),
            )
        )
        plan = result.scalar_one_or_none()
        if plan is not None:
            await _attach_budgets(db, clinic_id, [plan])
        return plan

    @staticmethod
    async def unbudgeted_items(
        db: AsyncSession,
        clinic_id: UUID,
        plan: TreatmentPlan,
    ) -> list[PlannedTreatmentItem]:
        """The plan's treatments no live budget of its own has priced.

        Since adding to a plan in progress no longer cancels the signed
        budget, a plan can carry work nobody has quoted. This is how much:
        the screen counts them, and the addendum is built from exactly this
        list.

        Derived rather than stored, and that is the point — no column to
        drift, and every plan written before this existed answers correctly
        from the first request. A budget line already names the odontogram
        `Treatment` it prices (`budget_items.treatment_id`), which is the
        same treatment the plan item points at, so "priced" is a join that
        was always available.

        The plan's budgets are the ones carrying its number plus the
        current link — the same rule `delete_for_plan` and the collections
        guard use. Cancelled ones do not count: a reopen cancels a budget,
        and its lines stop being a quote anybody owes.
        """
        items = plan.items or []
        if not items:
            return []

        # With the Budgets App off nothing is quoted, so nothing is behind.
        budgets = provider(PlanBudgets)
        if budgets is None:
            return []
        priced = await budgets.priced_treatment_ids(db, clinic_id, plan.plan_number, plan.budget_id)

        return [i for i in items if i.treatment_id and i.treatment_id not in priced]

    @staticmethod
    async def other_live_budgets(
        db: AsyncSession,
        clinic_id: UUID,
        plan: TreatmentPlan,
    ) -> list:
        """The plan's live budgets other than the one it points at.

        Today that means its addenda. Without this they would exist and be
        unreachable from the plan that produced them — findable only by
        scrolling the patient's budget list, which is exactly how a second
        document goes unsent.
        """
        budgets = provider(PlanBudgets)
        if budgets is None:
            return []
        live = await budgets.live_for_plan(db, clinic_id, plan.plan_number)
        return [b for b in live if b.id != plan.budget_id]

    @staticmethod
    async def next_action(
        db: AsyncSession,
        clinic_id: UUID,
        plan: TreatmentPlan,
    ) -> dict | None:
        """The one thing that has to happen for this plan to move on.

        A plan advances through hands that do not overlap: the dentist
        plans it, the patient accepts the budget, reception books the
        chair. The screen shows the stepper, but the stepper only says
        *where* the plan is — never what makes it move, which is why a
        confirmed plan sat untouched: nothing told anyone the budget was
        still unsent.

        One key at a time, deliberately. A list of everything outstanding
        is a report; this is an instruction, and a screen that gives two
        gives neither.

        The same reading the pipeline tabs do
        (``docs/workflows/plan-budget-flow.md`` §5), for one plan: the
        budget's own status decides the commercial steps and the plan's
        appointments decide the clinical ones. Returns ``None`` for a plan
        that is over — there is nothing to ask of a finished plan.

        One step is not a pipeline tab's: treatments added after the plan
        was confirmed carry no price until an addendum quotes them, and
        that comes before booking the chair.
        """
        status = plan.status
        if status in ("completed", "closed"):
            return None

        items = plan.items or []
        budget_status = plan.budget.status if plan.budget else None

        if status == "draft":
            return {"key": "add_treatments" if not items else "confirm_plan"}

        # Confirmed. The budget is what the patient is being asked to
        # agree to, so while it is unsent nothing else is the next step —
        # including on an `active` plan, where treatment has begun off the
        # back of an attended visit and the paperwork is now the thing
        # that is behind.
        # No budget and somebody to make one. With the Budgets App off
        # there is nobody to ask, and the plan moves on to the chair.
        if budget_status is None and provider(PlanBudgets) is not None:
            return {"key": "generate_budget"}

        # Work the clinic took on after the plan was confirmed, which no
        # budget prices yet. Checked *before* the budget's own steps, and
        # both orders would be wrong the other way round: telling anyone to
        # send a draft that leaves out half the treatments is how a patient
        # signs one figure and is later asked for another.
        unbudgeted = await TreatmentPlanService.unbudgeted_items(db, clinic_id, plan)
        if unbudgeted:
            return {
                "key": "budget_addendum",
                "budget_status": budget_status,
                "unbudgeted_count": len(unbudgeted),
            }

        if budget_status == "draft":
            return {"key": "send_budget", "budget_status": budget_status}
        if status == "pending":
            if budget_status == "sent":
                return {"key": "awaiting_patient", "budget_status": budget_status}
            if budget_status in ("expired", "rejected", "cancelled"):
                return {"key": f"budget_{budget_status}", "budget_status": budget_status}
            # `accepted` here means the plan never heard the event that
            # moves it on. Say what the clinic would do next anyway.

        if any(i.status != "completed" for i in items):
            booked = await db.execute(
                sa_text("""
                    SELECT
                        COUNT(*) FILTER (
                            WHERE a.start_time >= NOW()
                              AND a.status NOT IN ('cancelled', 'no_show')
                        ) AS future_count,
                        COUNT(*) FILTER (
                            WHERE a.start_time < NOW()
                              AND a.status NOT IN ('cancelled', 'no_show')
                        ) AS past_count,
                        MIN(a.start_time) FILTER (
                            WHERE a.start_time >= NOW()
                              AND a.status NOT IN ('cancelled', 'no_show')
                        ) AS next_at
                    FROM planned_treatment_items pti
                    JOIN appointment_treatments at
                      ON at.planned_treatment_item_id = pti.id
                    JOIN appointments a ON a.id = at.appointment_id
                    WHERE pti.clinic_id = :clinic_id
                      AND pti.treatment_plan_id = :plan_id
                """),
                {"clinic_id": clinic_id, "plan_id": plan.id},
            )
            appointments = booked.mappings().one()

            if appointments["future_count"]:
                return {
                    "key": "next_appointment",
                    "budget_status": budget_status,
                    "next_appointment_at": appointments["next_at"],
                }
            return {
                "key": "schedule_next" if appointments["past_count"] else "schedule_first",
                "budget_status": budget_status,
            }

        # Every treatment done and the plan still open. Completion normally
        # moves the plan to `completed` on its own, so this is the tail the
        # rule cannot reach by the front door — a plan whose items were all
        # reopened and finished again. Nothing to ask for; say it is done.
        return {"key": "all_done", "budget_status": budget_status}

    @staticmethod
    async def create(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID,
        data: dict,
    ) -> TreatmentPlan:
        """Create a new treatment plan."""
        # Validate patient exists in clinic
        patient_id = data.get("patient_id")
        patient = await db.get(Patient, patient_id)
        if not patient or patient.clinic_id != clinic_id:
            raise ValueError("Invalid patient")

        assigned_professional_id = data.get("assigned_professional_id")
        if assigned_professional_id is not None:
            await _validate_professional_in_clinic(db, clinic_id, assigned_professional_id)

        plan_number = await TreatmentPlanService.generate_plan_number(db, clinic_id)

        plan = TreatmentPlan(
            clinic_id=clinic_id,
            patient_id=patient_id,
            plan_number=plan_number,
            title=data.get("title"),
            assigned_professional_id=data.get("assigned_professional_id"),
            diagnosis_notes=data.get("diagnosis_notes"),
            prognosis=data.get("prognosis"),
            prognosis_notes=data.get("prognosis_notes"),
            internal_notes=data.get("internal_notes"),
            created_by=user_id,
        )
        db.add(plan)
        await db.flush()

        # Load patient relationship for response serialization
        await db.refresh(plan, ["patient"])

        # Publish event
        event_bus.publish_after_commit(
            db,
            "treatment_plan.created",
            {
                "plan_id": str(plan.id),
                "patient_id": str(plan.patient_id),
                "clinic_id": str(clinic_id),
                "created_by": str(user_id),
                "plan_number": plan.plan_number,
                "plan_name": plan.title,
            },
        )

        return plan

    @staticmethod
    async def update(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        data: dict,
        user_id: UUID | None = None,
    ) -> TreatmentPlan | None:
        """Update a treatment plan.

        ``user_id`` only names the actor when a reassignment is recorded
        in the plan history.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None

        # Pull the cascade flag out before generic setattr — it is a
        # write-only directive, not a column on TreatmentPlan.
        reassign_pending = bool(data.pop("reassign_pending_items", False))
        old_professional_id = plan.assigned_professional_id
        new_professional_id = data.get("assigned_professional_id", old_professional_id)

        if new_professional_id is not None and new_professional_id != old_professional_id:
            await _validate_professional_in_clinic(db, clinic_id, new_professional_id)

        for key, value in data.items():
            if value is not None and hasattr(plan, key):
                setattr(plan, key, value)

        # Cascade is opt-in. Only pending items still pointing at the previous
        # plan-doctor are reassigned; explicit overrides (other doctor) and
        # completed items are intentionally left alone.
        if (
            reassign_pending
            and old_professional_id is not None
            and new_professional_id is not None
            and old_professional_id != new_professional_id
        ):
            await db.execute(
                update(PlannedTreatmentItem)
                .where(
                    PlannedTreatmentItem.treatment_plan_id == plan_id,
                    PlannedTreatmentItem.clinic_id == clinic_id,
                    PlannedTreatmentItem.status == "pending",
                    PlannedTreatmentItem.assigned_professional_id == old_professional_id,
                )
                .values(assigned_professional_id=new_professional_id)
            )

        # Reassignment hands the plan's edit rights to whoever holds it
        # now — `stewards_of` derives them from the current assignment —
        # so it is worth a line of its own in the history rather than
        # disappearing into a generic "updated".
        if new_professional_id != old_professional_id:
            directory = provider(ProfessionalDirectory)
            briefs = (
                await directory.briefs(
                    db,
                    clinic_id,
                    [p for p in (old_professional_id, new_professional_id) if p is not None],
                )
                if directory
                else {}
            )
            by_id = {pid: f"{b.first_name} {b.last_name}".strip() for pid, b in briefs.items()}
            TreatmentPlanService.record_history(
                db,
                clinic_id=clinic_id,
                plan_id=plan_id,
                action="reassigned",
                actor_user_id=user_id,
                payload={
                    "from": by_id.get(old_professional_id),
                    "to": by_id.get(new_professional_id),
                    "cascaded_to_items": reassign_pending,
                },
            )

        return plan

    @staticmethod
    async def update_status(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        new_status: str,
        user_id: UUID,
    ) -> TreatmentPlan | None:
        """Update treatment plan status with validation."""
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None

        old_status = plan.status
        if old_status == new_status:
            return plan

        if new_status not in VALID_PLAN_TRANSITIONS.get(old_status, set()):
            raise ValueError(f"Invalid status transition from {old_status} to {new_status}")

        # Cannot activate plan without items
        if new_status == "active" and not plan.items:
            raise ValueError("Cannot activate plan without treatments")

        plan.status = new_status

        # Terminal transitions drop the plan's hold on its planned Treatments — clean
        # up any that become orphaned so the odontogram reflects reality.
        if new_status in ("closed", "archived"):
            await TreatmentPlanService._cleanup_orphan_planned_treatments(
                db, clinic_id, plan, user_id
            )

        # Publish event
        event_bus.publish_after_commit(
            db,
            "treatment_plan.status_changed",
            {
                "plan_id": str(plan.id),
                "old_status": old_status,
                "new_status": new_status,
                "clinic_id": str(clinic_id),
            },
        )

        return plan

    @staticmethod
    async def delete(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Soft delete (archive) a treatment plan.

        Also runs orphan cleanup: planned Treatments that only lived inside this
        plan are soft-deleted so they disappear from the odontogram. `performed`
        Treatments are always preserved as clinical history.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return False

        await TreatmentPlanService._guard_collections(db, clinic_id, plan)
        await TreatmentPlanService._cleanup_orphan_planned_treatments(db, clinic_id, plan, user_id)

        plan.deleted_at = datetime.now(UTC)

        # The budgets go with their plan, every version of them — `budget`
        # deletes them when it hears this (ADR 0042). The budget endpoint
        # refuses to delete a plan's budget, so this is the only way they go.
        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_DELETED,
            {
                "plan_id": str(plan.id),
                "clinic_id": str(clinic_id),
                "patient_id": str(plan.patient_id),
                "plan_number": plan.plan_number,
                "budget_id": str(plan.budget_id) if plan.budget_id else None,
                "deleted_by_user_id": str(user_id),
            },
        )
        return True

    @staticmethod
    async def _guard_collections(db: AsyncSession, clinic_id: UUID, plan: TreatmentPlan) -> None:
        """Refuse to delete or cancel a plan the patient has paid into.

        Asks `payments` through the ``Collections`` contract: this is a
        precondition of the write, and an event could only report the
        mistake after it was made. The plan's budgets are every one it
        produced — the current link plus any carrying its number, so money
        on a budget cancelled by a reopen still counts.

        With the Payments App off there is no ledger to ask and nothing
        new is being collected, so the plan may go (ADR 0037).
        """
        ledger = provider(Collections)
        if ledger is None:
            return
        budgets = provider(PlanBudgets)
        budget_ids = (
            await budgets.ids_for_plan(db, clinic_id, plan.plan_number, plan.budget_id)
            if budgets
            else []
        )
        treatment_ids = [item.treatment_id for item in plan.items if item.treatment_id]

        if await ledger.plan_has_collections(
            db, clinic_id, plan.patient_id, budget_ids, treatment_ids
        ):
            raise PlanHasCollectionsError()

    @staticmethod
    async def _cleanup_orphan_planned_treatments(
        db: AsyncSession,
        clinic_id: UUID,
        plan: TreatmentPlan,
        user_id: UUID,
    ) -> None:
        """Soft-delete Treatments that become orphaned when `plan` goes terminal.

        For every Treatment referenced by this plan's items, check whether any
        *other* non-terminal plan still references it. If not, and the Treatment
        is still `planned` (never performed), soft-delete it so the odontogram
        stops showing it. Performed Treatments are left alone (clinical history).
        """
        from app.modules.odontogram.service import TreatmentService

        treatment_ids = {item.treatment_id for item in plan.items if item.treatment_id}
        if not treatment_ids:
            return

        for treatment_id in treatment_ids:
            # Count references from OTHER plans that are still "live" (non-terminal,
            # non-deleted). We exclude this plan explicitly — its items stay in DB
            # as history but no longer count as a live reference.
            result = await db.execute(
                select(func.count(PlannedTreatmentItem.id))
                .join(
                    TreatmentPlan,
                    TreatmentPlan.id == PlannedTreatmentItem.treatment_plan_id,
                )
                .where(
                    PlannedTreatmentItem.treatment_id == treatment_id,
                    PlannedTreatmentItem.clinic_id == clinic_id,
                    PlannedTreatmentItem.treatment_plan_id != plan.id,
                    TreatmentPlan.deleted_at.is_(None),
                    TreatmentPlan.status.notin_(("archived", "cancelled")),
                )
            )
            if (result.scalar_one() or 0) > 0:
                continue

            treatment = await db.get(Treatment, treatment_id)
            if treatment and treatment.deleted_at is None and treatment.status == "planned":
                await TreatmentService.delete(db, clinic_id, treatment_id, user_id)

    # -------------------------------------------------------------------------
    # Item Operations
    # -------------------------------------------------------------------------

    @staticmethod
    async def add_item(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        data: dict,
        user_id: UUID | None = None,
    ) -> PlannedTreatmentItem:
        """Add a Treatment to the plan as a new item.

        ``user_id`` only names the actor in the plan history. Optional so
        the internal callers that add items on the clinic's behalf —
        applying a template, accepting a charted proposal — keep working
        without inventing an author for the row.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Treatment plan not found")

        if plan.status not in ("draft", "pending", "active"):
            raise ValueError("Cannot add items to a completed/cancelled plan")

        # Deliberately **not** guarded by `_is_plan_locked`. The lock exists
        # to protect what the patient signed, and adding changes none of it:
        # the existing lines keep their prices and the budget keeps saying
        # what it always said. Finding a second caries halfway through a
        # plan is ordinary, and the old answer — cancel the signed budget,
        # rebuild the plan, make the patient accept everything again — cost
        # far more than the finding. What the new treatment costs is priced
        # by an addendum (`unbudgeted_items` + `POST /budget-addendum`).
        #
        # Changing or removing an existing line is the opposite, and both
        # still refuse: that is the contract moving under the patient.

        treatment_id = data.get("treatment_id")
        if treatment_id is None:
            raise ValueError("treatment_id is required")

        # Validate the Treatment exists for this clinic/patient.
        treatment = await db.get(Treatment, treatment_id)
        if (
            not treatment
            or treatment.clinic_id != clinic_id
            or treatment.patient_id != plan.patient_id
            or treatment.deleted_at is not None
        ):
            raise ValueError("Invalid treatment for this plan")

        sequence_order = data.get("sequence_order")
        if sequence_order is None:
            result = await db.execute(
                select(func.max(PlannedTreatmentItem.sequence_order)).where(
                    PlannedTreatmentItem.treatment_plan_id == plan_id
                )
            )
            max_order = result.scalar_one() or 0
            sequence_order = max_order + 1

        # Inherit the plan's doctor unless the caller passes an explicit value.
        # Snapshot semantics: once stored on the item it stays put even if the
        # plan's doctor changes later (cascade is opt-in on plan update).
        assigned_professional_id = data.get("assigned_professional_id")
        if assigned_professional_id is None:
            assigned_professional_id = plan.assigned_professional_id
        if assigned_professional_id is not None:
            await _validate_professional_in_clinic(db, clinic_id, assigned_professional_id)

        item = PlannedTreatmentItem(
            clinic_id=clinic_id,
            treatment_plan_id=plan_id,
            treatment_id=treatment_id,
            sequence_order=sequence_order,
            notes=data.get("notes"),
            assigned_professional_id=assigned_professional_id,
        )
        db.add(item)
        await db.flush()

        # Pre-load the catalog template before snapshotting sessions.
        from app.modules.catalog.models import TreatmentCatalogItem

        treatment_full = await db.execute(
            select(Treatment)
            .options(
                selectinload(Treatment.teeth),
                selectinload(Treatment.catalog_item).selectinload(TreatmentCatalogItem.sessions),
            )
            .where(Treatment.id == treatment_id)
        )
        treatment_loaded = treatment_full.scalar_one()

        # Stage of care: an explicit value wins, otherwise seed from the
        # catalog default. Stored on the item because the same treatment is
        # an emergency for one patient and planned rehabilitation for another.
        phase = data.get("phase")
        if phase is None and treatment_loaded.catalog_item is not None:
            phase = treatment_loaded.catalog_item.default_phase
        item.phase = phase
        for session_row in _snapshot_sessions_from_catalog(item, treatment_loaded):
            session_row.plan_item_id = item.id
            db.add(session_row)
        await db.flush()

        # Re-fetch with eager-loaded treatment.teeth / .catalog_item for the response.
        reloaded = await db.execute(
            select(PlannedTreatmentItem)
            .options(
                selectinload(PlannedTreatmentItem.treatment).selectinload(Treatment.teeth),
                selectinload(PlannedTreatmentItem.treatment).selectinload(Treatment.catalog_item),
                selectinload(PlannedTreatmentItem.sessions),
            )
            .where(PlannedTreatmentItem.id == item.id)
        )
        item = reloaded.scalar_one()

        # Snapshot payload — see ADR 0003. The budget module subscribes
        # without importing treatment_plan/odontogram models.
        treatment = item.treatment
        primary_tooth = treatment.teeth[0].tooth_number if treatment and treatment.teeth else None
        primary_surfaces = treatment.teeth[0].surfaces if treatment and treatment.teeth else None

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan_id,
            action="item_added",
            actor_user_id=user_id,
            payload={
                "treatment": _item_label(item),
                "tooth": primary_tooth,
                "budget_id": str(plan.budget_id) if plan.budget_id else None,
            },
        )

        event_bus.publish_after_commit(
            db,
            "treatment_plan.treatment_added",
            {
                "plan_id": str(plan_id),
                "item_id": str(item.id),
                "treatment_id": str(treatment_id),
                "clinic_id": str(clinic_id),
                "patient_id": str(plan.patient_id),
                "budget_id": str(plan.budget_id) if plan.budget_id else None,
                "catalog_item_id": (
                    str(treatment.catalog_item_id)
                    if treatment and treatment.catalog_item_id
                    else None
                ),
                "tooth_number": primary_tooth,
                "surfaces": primary_surfaces,
                "unit_price": (
                    str(treatment.price_snapshot)
                    if treatment and treatment.price_snapshot is not None
                    else None
                ),
                "assigned_professional_id": (
                    str(item.assigned_professional_id) if item.assigned_professional_id else None
                ),
            },
        )

        return item

    @staticmethod
    async def update_item(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        data: dict,
    ) -> PlannedTreatmentItem | None:
        """Update scheduling metadata on a planned treatment item."""
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None

        # The plan-lock guard protects the patient-facing contract: items,
        # prices, sequence. Reassigning who performs a treatment doesn't
        # change that contract, so doctor-only updates skip the guard —
        # clinicians need to swap responsibility even after the plan is
        # validated. Any other field still respects the lock.
        non_doctor_keys = {k for k in data if k != "assigned_professional_id"}
        if non_doctor_keys and _is_plan_locked(plan):
            raise PlanLockedError("Plan is locked by an active budget")

        result = await db.execute(
            select(PlannedTreatmentItem)
            .where(
                PlannedTreatmentItem.id == item_id,
                PlannedTreatmentItem.treatment_plan_id == plan_id,
                PlannedTreatmentItem.clinic_id == clinic_id,
            )
            .options(*_item_with_sessions_loader())
        )
        item = result.scalar_one_or_none()
        if not item:
            return None

        # Completed/cancelled items preserve the doctor that was responsible
        # at the time. ``completed_by`` is the source of truth for "who did
        # it" once an item is done — don't let later edits rewrite history.
        if "assigned_professional_id" in data and item.status != "pending":
            raise ValueError("Cannot change the assigned doctor on a non-pending item")

        # ``assigned_professional_id`` is nullable on purpose — the caller may
        # want to clear it. The router passes ``model_dump(exclude_unset=True)``
        # so a missing key means "do not touch", while ``None`` means "unset".
        if "assigned_professional_id" in data:
            new_professional_id = data.pop("assigned_professional_id")
            if new_professional_id is not None:
                await _validate_professional_in_clinic(db, clinic_id, new_professional_id)
            item.assigned_professional_id = new_professional_id

        for key, value in data.items():
            if value is not None and hasattr(item, key):
                setattr(item, key, value)

        return item

    @staticmethod
    async def reorder_items(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_ids: list[UUID],
    ) -> list[PlannedTreatmentItem] | None:
        """Set `sequence_order` of items to match the position in `item_ids`.

        Validates that `item_ids` covers exactly the plan's items (no missing, no
        extras). Returns the reordered items or None if the plan does not exist.
        Raises ValueError on validation failure.
        """
        # Load plan to confirm ownership (with budget for lock check).
        plan_q = await db.execute(
            select(TreatmentPlan).where(
                TreatmentPlan.id == plan_id,
                TreatmentPlan.clinic_id == clinic_id,
                TreatmentPlan.deleted_at.is_(None),
            )
        )
        plan = plan_q.scalar_one_or_none()
        if not plan:
            return None
        await _attach_budgets(db, clinic_id, [plan])
        if _is_plan_locked(plan):
            raise PlanLockedError("Plan is locked by an active budget")

        # Load current items.
        items_q = await db.execute(
            select(PlannedTreatmentItem).where(
                PlannedTreatmentItem.treatment_plan_id == plan_id,
                PlannedTreatmentItem.clinic_id == clinic_id,
            )
        )
        current = {i.id: i for i in items_q.scalars().all()}

        # Validate set equality — no missing or extra IDs.
        requested = list(item_ids)
        if len(requested) != len(set(requested)):
            raise ValueError("Duplicate item ids not allowed")
        if set(requested) != set(current.keys()):
            raise ValueError("item_ids must cover exactly the plan's current items")

        # Apply new order.
        for index, item_id in enumerate(requested):
            current[item_id].sequence_order = index

        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_ITEMS_REORDERED,
            {
                "clinic_id": str(clinic_id),
                "plan_id": str(plan_id),
                "item_ids": [str(i) for i in requested],
            },
        )

        return [current[i] for i in requested]

    @staticmethod
    async def remove_item(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Remove an item from the plan.

        Orphan rule: if the removed item was the last active PlannedTreatmentItem
        referencing its Treatment and that Treatment is still `planned`, soft-delete
        the Treatment so the odontogram reflects the removal. `performed` Treatments
        are kept (clinical history).
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return False
        if _is_plan_locked(plan):
            raise PlanLockedError("Plan is locked by an active budget")

        result = await db.execute(
            select(PlannedTreatmentItem).where(
                PlannedTreatmentItem.id == item_id,
                PlannedTreatmentItem.treatment_plan_id == plan_id,
                PlannedTreatmentItem.clinic_id == clinic_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return False

        treatment_id = item.treatment_id
        removed_label = _item_label(item)
        await db.delete(item)
        await db.flush()

        # Orphan check — any other active item still referencing the Treatment?
        other_refs = await db.execute(
            select(func.count(PlannedTreatmentItem.id)).where(
                PlannedTreatmentItem.treatment_id == treatment_id,
                PlannedTreatmentItem.clinic_id == clinic_id,
            )
        )
        remaining = other_refs.scalar_one() or 0
        if remaining == 0:
            treatment = await db.get(Treatment, treatment_id)
            if treatment and treatment.deleted_at is None and treatment.status == "planned":
                from app.modules.odontogram.service import TreatmentService

                await TreatmentService.delete(db, clinic_id, treatment_id, user_id)

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan_id,
            action="item_removed",
            actor_user_id=user_id,
            payload={"treatment": removed_label},
        )

        # Snapshot payload — budget needs ``budget_id`` to find the
        # matching line without importing treatment_plan models.
        event_bus.publish_after_commit(
            db,
            "treatment_plan.treatment_removed",
            {
                "plan_id": str(plan_id),
                "item_id": str(item_id),
                "treatment_id": str(treatment_id),
                "clinic_id": str(clinic_id),
                "budget_id": str(plan.budget_id) if plan.budget_id else None,
            },
        )

        return True

    @staticmethod
    async def _load_item_with_sessions(
        db: AsyncSession, clinic_id: UUID, plan_id: UUID, item_id: UUID
    ) -> PlannedTreatmentItem | None:
        result = await db.execute(
            select(PlannedTreatmentItem)
            .where(
                PlannedTreatmentItem.id == item_id,
                PlannedTreatmentItem.treatment_plan_id == plan_id,
                PlannedTreatmentItem.clinic_id == clinic_id,
            )
            .options(*_item_with_sessions_loader())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def complete_session(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        session_id: UUID,
        user_id: UUID,
        completed_without_appointment: bool = False,
        notes: str | None = None,
    ) -> PlannedTreatmentItem | None:
        """Mark one session of a plan item as completed.

        Publishes ``treatment_plan.item_session_completed`` (consumed by
        payments → earned ledger). When this is the last non-pending
        session, the parent item is finalized: status flips to
        ``completed``, the Treatment is performed, and the existing
        ``treatment_plan.treatment_completed`` audit/recall path runs.
        """
        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None

        session = next((s for s in item.sessions if s.id == session_id), None)
        if not session:
            raise ValueError("Session not found")
        if session.status != "pending":
            raise ValueError("Session is not pending")

        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        session.completed_by = user_id
        if notes:
            session.notes = notes

        await db.flush()

        patient_id_str: str | None = None
        if item.treatment:
            patient_id_str = str(item.treatment.patient_id)

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_ITEM_SESSION_COMPLETED,
            {
                "clinic_id": str(clinic_id),
                "plan_id": str(plan_id),
                "item_id": str(item_id),
                "session_id": str(session.id),
                "sequence": session.sequence,
                "label": session.label,
                "amount": str(session.amount),
                "treatment_id": str(item.treatment_id),
                "patient_id": patient_id_str,
                "completed_by": str(user_id),
                "occurred_at": session.completed_at.isoformat(),
            },
        )

        # Item finalizes when every session is in a terminal state and at
        # least one was actually completed (otherwise an all-cancelled
        # set would silently mark the item done).
        terminal_states = {"completed", "cancelled"}
        all_terminal = all(s.status in terminal_states for s in item.sessions)
        any_completed = any(s.status == "completed" for s in item.sessions)
        if all_terminal and any_completed and item.status != "completed":
            await TreatmentPlanService._finalize_item(
                db,
                clinic_id=clinic_id,
                plan_id=plan_id,
                item=item,
                user_id=user_id,
                completed_without_appointment=completed_without_appointment,
                notes=notes,
            )

        return item

    @staticmethod
    async def _finalize_item(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        plan_id: UUID,
        item: PlannedTreatmentItem,
        user_id: UUID,
        completed_without_appointment: bool,
        notes: str | None,
    ) -> None:
        """Flip the item to completed and run the legacy completion path.

        Performs the Treatment, publishes ``treatment_completed`` (recalls /
        odontogram) and the audit hint. Does NOT publish earned events —
        those flow per-session via ``item_session_completed``.
        """
        item.status = "completed"
        item.completed_at = datetime.now(UTC)
        item.completed_by = user_id
        item.completed_without_appointment = completed_without_appointment
        if notes and not item.notes:
            item.notes = notes

        from app.modules.odontogram.service import TreatmentService

        await TreatmentService.perform(
            db=db,
            clinic_id=clinic_id,
            treatment_id=item.treatment_id,
            user_id=user_id,
            notes=notes,
        )

        item_name: str | None = None
        patient_id_str: str | None = None
        treatment_category_key: str | None = None
        if item.treatment:
            patient_id_str = str(item.treatment.patient_id)
            if item.treatment.catalog_item:
                names = item.treatment.catalog_item.names or {}
                item_name = names.get("es") or names.get("en")
                if item.treatment.catalog_item.category:
                    treatment_category_key = item.treatment.catalog_item.category.key

        event_bus.publish_after_commit(
            db,
            "treatment_plan.treatment_completed",
            {
                "plan_id": str(plan_id),
                "item_id": str(item.id),
                "treatment_id": str(item.treatment_id),
                "clinic_id": str(clinic_id),
                "patient_id": patient_id_str,
                "completed_by": str(user_id),
                "item_name": item_name,
                "occurred_at": item.completed_at.isoformat() if item.completed_at else None,
                "treatment_category_key": treatment_category_key,
            },
        )

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_ITEM_COMPLETED_WITHOUT_NOTE,
            {
                "clinic_id": str(clinic_id),
                "patient_id": patient_id_str,
                "plan_id": str(plan_id),
                "plan_item_id": str(item.id),
                "user_id": str(user_id),
                "item_name": item_name,
                "occurred_at": item.completed_at.isoformat() if item.completed_at else None,
            },
        )

        await TreatmentPlanService._sync_plan_lifecycle(db, clinic_id, plan_id)

    @staticmethod
    async def complete_item(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        user_id: UUID,
        completed_without_appointment: bool = True,
        notes: str | None = None,
    ) -> PlannedTreatmentItem | None:
        """Back-compat shim: complete the next pending session of an item.

        Items always have ≥1 session post-migration (tp_0006 backfill).
        For single-session items this behaves like the legacy flow. For
        multi-session items it advances one session per call — callers
        targeting a specific session should use ``complete_session``.
        """
        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None
        if item.status == "completed":
            return item

        next_session = next(
            (s for s in sorted(item.sessions, key=lambda x: x.sequence) if s.status == "pending"),
            None,
        )
        if next_session is None:
            raise ValueError("No pending sessions to complete")

        return await TreatmentPlanService.complete_session(
            db,
            clinic_id=clinic_id,
            plan_id=plan_id,
            item_id=item_id,
            session_id=next_session.id,
            user_id=user_id,
            completed_without_appointment=completed_without_appointment,
            notes=notes,
        )

    @staticmethod
    async def reopen_item(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        user_id: UUID,
    ) -> PlannedTreatmentItem | None:
        """Undo the completion of an item: it goes back to ``pending``.

        What is undone is **the act that closed the item** — its most
        recent terminal session — not every session it ever had. On a
        single-session treatment that is the only one; on an eight-visit
        orthodontic case, ticking the last visit by mistake must not wipe
        the seven the patient really attended, nor the money they earned.

        The charge goes with it. ``item_session_reopened`` is published for
        the session, and ``payments`` drops the earned entry it booked; if
        the patient had already paid, that money stays theirs as credit and
        covers the treatment again when it is completed for real. An event
        and not a direct call because the charge was booked by an event in
        the first place and this module does not depend on ``payments`` —
        reversal takes the same road as creation.

        Refused on a ``closed`` plan: the plan is over, and reactivating it
        is the door back in. A ``completed`` plan returns to ``active``,
        because it now has work outstanding.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None
        if plan.status == "closed":
            raise ValueError("The plan is closed. Reactivate it before reopening a treatment.")

        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None
        if item.status != "completed":
            raise ValueError("Only a completed treatment can be reopened")

        terminal = [s for s in item.sessions if s.status in ("completed", "cancelled")]
        if not terminal:
            raise ValueError("No completed session to reopen")
        session = max(
            terminal, key=lambda s: (s.completed_at or datetime.min.replace(tzinfo=UTC), s.sequence)
        )
        previous_session_status = session.status

        session.status = "pending"
        session.completed_at = None
        session.completed_by = None

        item.status = "pending"
        item.completed_at = None
        item.completed_by = None
        item.completed_without_appointment = False

        from app.modules.odontogram.service import TreatmentService

        await TreatmentService.update(
            db,
            clinic_id=clinic_id,
            treatment_id=item.treatment_id,
            user_id=user_id,
            status="planned",
        )

        previous_plan_status = plan.status
        if plan.status == "completed":
            plan.status = "active"

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan_id,
            action="item_reopened",
            actor_user_id=user_id,
            from_status=previous_plan_status if plan.status != previous_plan_status else None,
            to_status=plan.status if plan.status != previous_plan_status else None,
            payload={"treatment": _item_label(item)},
        )

        await db.flush()

        now = datetime.now(UTC)
        if previous_session_status == "completed":
            event_bus.publish_after_commit(
                db,
                EventType.TREATMENT_PLAN_ITEM_SESSION_REOPENED,
                {
                    "clinic_id": str(clinic_id),
                    "plan_id": str(plan_id),
                    "item_id": str(item_id),
                    "session_id": str(session.id),
                    "treatment_id": str(item.treatment_id),
                    "patient_id": str(item.treatment.patient_id) if item.treatment else None,
                    "reopened_by": str(user_id),
                    "occurred_at": now.isoformat(),
                },
            )
        if plan.status != previous_plan_status:
            event_bus.publish_after_commit(
                db,
                EventType.TREATMENT_PLAN_STATUS_CHANGED,
                {
                    "plan_id": str(plan.id),
                    "old_status": previous_plan_status,
                    "new_status": plan.status,
                    "clinic_id": str(clinic_id),
                },
            )

        return item

    @staticmethod
    async def cancel_session(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        session_id: UUID,
        user_id: UUID,
        notes: str | None = None,
    ) -> PlannedTreatmentItem | None:
        """Mark a pending session as cancelled (no earned entry generated)."""
        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None
        session = next((s for s in item.sessions if s.id == session_id), None)
        if not session:
            raise ValueError("Session not found")
        if session.status != "pending":
            raise ValueError("Only pending sessions can be cancelled")

        session.status = "cancelled"
        session.completed_at = datetime.now(UTC)
        session.completed_by = user_id
        if notes:
            session.notes = notes
        await db.flush()

        # Finalize if cancellation leaves the item with no pending work and
        # at least one completed session.
        terminal_states = {"completed", "cancelled"}
        all_terminal = all(s.status in terminal_states for s in item.sessions)
        any_completed = any(s.status == "completed" for s in item.sessions)
        if all_terminal and any_completed and item.status != "completed":
            await TreatmentPlanService._finalize_item(
                db,
                clinic_id=clinic_id,
                plan_id=plan_id,
                item=item,
                user_id=user_id,
                completed_without_appointment=False,
                notes=None,
            )
        return item

    @staticmethod
    async def update_session(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        session_id: UUID,
        data: dict,
    ) -> PlannedTreatmentItem | None:
        """Edit a pending session's label/amount/notes."""
        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None
        session = next((s for s in item.sessions if s.id == session_id), None)
        if not session:
            raise ValueError("Session not found")
        if session.status != "pending":
            raise ValueError("Cannot edit a non-pending session")

        if "label" in data:
            session.label = data["label"]
        if "amount" in data and data["amount"] is not None:
            session.amount = Decimal(str(data["amount"]))
        if "notes" in data:
            session.notes = data["notes"]
        return item

    @staticmethod
    async def add_session_manual(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        data: dict,
    ) -> PlannedTreatmentItem | None:
        """Append a new session row at the next sequence number."""
        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None
        next_seq = (max((s.sequence for s in item.sessions), default=0)) + 1
        amount = data.get("amount")
        if amount is None:
            raise ValueError("amount is required")
        item.sessions.append(
            PlannedTreatmentItemSession(
                sequence=next_seq,
                label=data.get("label"),
                amount=Decimal(str(amount)),
                status="pending",
            )
        )
        # `id` is a Python-side `default=uuid4`, so it is filled on flush and
        # not before. Returning the item unflushed handed the response model a
        # session whose id was still None, and Pydantic refused it with a 500 —
        # the row rolled back and adding a session by hand never once worked.
        await db.flush()
        return item

    @staticmethod
    async def delete_session(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        item_id: UUID,
        session_id: UUID,
    ) -> PlannedTreatmentItem | None:
        """Remove a pending session. Refuses on completed/cancelled sessions."""
        item = await TreatmentPlanService._load_item_with_sessions(db, clinic_id, plan_id, item_id)
        if not item:
            return None
        session = next((s for s in item.sessions if s.id == session_id), None)
        if not session:
            raise ValueError("Session not found")
        if session.status != "pending":
            raise ValueError("Cannot delete a non-pending session")
        if (
            len([s for s in item.sessions if s.status == "pending"]) <= 1
            and len(item.sessions) == 1
        ):
            raise ValueError("Cannot delete the only session of an item")
        item.sessions.remove(session)
        await db.flush()
        return item

    @staticmethod
    def record_history(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        plan_id: UUID,
        action: str,
        actor_user_id: UUID | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Append one line to the plan's history.

        Not a coroutine and it does not flush: the row joins whatever
        transaction the caller is already in, so a change and its record
        of that change land together or not at all. A history that can
        outlive a rolled-back edit is worse than none.
        """
        db.add(
            TreatmentPlanHistory(
                clinic_id=clinic_id,
                treatment_plan_id=plan_id,
                action=action,
                from_status=from_status,
                to_status=to_status,
                payload=payload,
                actor_user_id=actor_user_id,
            )
        )

    @staticmethod
    async def history(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        limit: int = 100,
    ) -> list[TreatmentPlanHistory]:
        """The plan's history, newest first."""
        result = await db.execute(
            select(TreatmentPlanHistory)
            .where(
                TreatmentPlanHistory.clinic_id == clinic_id,
                TreatmentPlanHistory.treatment_plan_id == plan_id,
            )
            .options(selectinload(TreatmentPlanHistory.actor))
            .order_by(TreatmentPlanHistory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _sync_plan_lifecycle(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
    ) -> None:
        """Move the plan to wherever its items now say it is.

        Called from every path that finishes a treatment. Both ends of the
        lifecycle are checked, in order, because a single completion can
        legitimately cross both: work recorded on a plan nobody had
        started proves the patient came (``pending`` → ``active``), and
        if it was the last outstanding treatment the plan is finished too
        (``active`` → ``completed``). Running the start first is what
        lets that plan land on ``completed`` instead of stalling in
        ``pending`` with every item done.

        Both steps are idempotent and both refuse a status they do not
        apply to, so calling this after any completion is safe.
        """
        await TreatmentPlanService.activate_from_attendance(db, clinic_id, plan_id)
        await TreatmentPlanService._check_and_complete_plan(db, clinic_id, plan_id)

    @staticmethod
    async def _check_and_complete_plan(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
    ) -> None:
        """Check if all items completed and auto-complete the plan if so."""
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan or plan.status != "active":
            return

        # Check if any non-completed items remain
        has_pending = any(item.status != "completed" for item in plan.items)
        if has_pending:
            return

        # All items completed - auto-complete the plan
        old_status = plan.status
        plan.status = "completed"

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="completed",
            from_status=old_status,
            to_status="completed",
        )

        event_bus.publish_after_commit(
            db,
            "treatment_plan.status_changed",
            {
                "plan_id": str(plan.id),
                "old_status": old_status,
                "new_status": "completed",
                "clinic_id": str(clinic_id),
            },
        )

        logger.info(
            "Auto-completed treatment plan %s (all items completed)",
            plan.id,
        )

    # -------------------------------------------------------------------------
    # Budget Integration
    # -------------------------------------------------------------------------

    @staticmethod
    async def link_budget(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        budget_id: UUID,
    ) -> TreatmentPlan | None:
        """Link an existing budget to the plan."""
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None

        # Verify budget exists and belongs to same clinic/patient
        budgets = provider(PlanBudgets)
        if budgets is None:
            raise ValueError(BUDGETS_UNAVAILABLE)
        budget = (await budgets.briefs(db, clinic_id, [budget_id])).get(budget_id)
        if not budget:
            raise ValueError("Invalid budget")

        if budget.patient_id != plan.patient_id:
            raise ValueError("Budget belongs to different patient")

        plan.budget_id = budget_id
        plan.budget = budget

        return plan

    @staticmethod
    async def request_budget_sync(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
    ) -> bool:
        """Request budget module to sync items.

        Builds a denormalized items snapshot so the budget handler can
        reconcile without importing treatment_plan / odontogram models
        (ADR 0003).
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan or not plan.budget_id:
            return False

        plan_items = await db.execute(
            select(PlannedTreatmentItem)
            .options(selectinload(PlannedTreatmentItem.treatment).selectinload(Treatment.teeth))
            .where(
                PlannedTreatmentItem.treatment_plan_id == plan_id,
                PlannedTreatmentItem.clinic_id == clinic_id,
            )
        )
        items_payload = []
        for plan_item in plan_items.scalars().all():
            treatment = plan_item.treatment
            if not treatment or not treatment.catalog_item_id:
                continue
            primary_tooth = treatment.teeth[0].tooth_number if treatment.teeth else None
            primary_surfaces = treatment.teeth[0].surfaces if treatment.teeth else None
            items_payload.append(
                {
                    "item_id": str(plan_item.id),
                    "treatment_id": str(treatment.id),
                    "catalog_item_id": str(treatment.catalog_item_id),
                    "tooth_number": primary_tooth,
                    "surfaces": primary_surfaces,
                    "unit_price": (
                        str(treatment.price_snapshot)
                        if treatment.price_snapshot is not None
                        else None
                    ),
                }
            )

        event_bus.publish_after_commit(
            db,
            "treatment_plan.budget_sync_requested",
            {
                "plan_id": str(plan_id),
                "budget_id": str(plan.budget_id),
                "clinic_id": str(clinic_id),
                "items": items_payload,
            },
        )

        return True

    # -------------------------------------------------------------------------
    # Bandeja de planes (cross-module pipeline view)
    # -------------------------------------------------------------------------

    @staticmethod
    async def list_pipeline(
        db: AsyncSession,
        clinic_id: UUID,
        tab: str,
        page: int = 1,
        page_size: int = 20,
        doctor_id: UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        """Pipeline bandeja query — joins plans + budgets + appointments.

        Returns ``(rows, total)`` with rows shaped as ``PipelineRow``
        dicts ready to be returned by FastAPI. The query is implemented
        with raw SQL because the JOIN spans three modules
        (treatment_plan + budget + agenda) and `treatment_plan`'s
        manifest declares the dependency on both. Splitting into ORM
        round-trips would be N+1; doing it in one statement is fastest
        and pageable.
        """
        # ----- per-tab WHERE clause ------------------------------------
        # Five tabs documented in docs/workflows/plan-budget-flow.md §5.
        if tab == "en_curso":
            # "En curso" = every plan actually in flight, which spans two
            # statuses: `pending` (doctor confirmed, waiting on the
            # patient to accept the budget) and `active` (accepted,
            # treatment underway). Reception thinks of both as "en
            # marcha" — the plan starts moving once the patient turns up
            # for the diagnostic visit, well before the budget is signed
            # — so splitting them across tabs hid work that was live.
            # Most recently moved first: this is the "what is going on
            # right now" tab, not a queue to work through.
            tab_where = "p.status IN ('pending', 'active')"
            order_by = "GREATEST(p.updated_at, COALESCE(p.confirmed_at, p.created_at)) DESC"
        elif tab == "por_presupuestar":
            # These two queues are about the *budget*, so they follow the
            # budget's state and accept either live plan status. Since
            # attending the first consultation moves a plan to `active`
            # before anything is signed, keying them to `pending` alone
            # would drop exactly those plans out of the commercial queue
            # — the unsigned budget would stop being chased the moment
            # the patient walked in.
            tab_where = "p.status IN ('pending', 'active') AND b.status = 'draft'"
            order_by = "COALESCE(p.confirmed_at, p.created_at) DESC"
        elif tab == "esperando_paciente":
            tab_where = "p.status IN ('pending', 'active') AND b.status IN ('sent', 'expired')"
            order_by = "COALESCE(p.confirmed_at, p.created_at) ASC"  # oldest first
        elif tab == "sin_cita":
            tab_where = (
                "p.status = 'active' "
                "AND COALESCE(appt.future_count, 0) = 0 "
                "AND COALESCE(appt.past_count, 0) = 0"
            )
            order_by = "p.updated_at DESC"
        elif tab == "sin_proxima_cita":
            tab_where = (
                "p.status = 'active' "
                "AND COALESCE(appt.future_count, 0) = 0 "
                "AND COALESCE(appt.past_count, 0) > 0 "
                "AND COALESCE(items.pending_count, 0) > 0"
            )
            order_by = "appt.last_past_at DESC NULLS LAST"
        elif tab == "cerrados":
            tab_where = "p.status = 'closed' AND p.closed_at >= (NOW() - INTERVAL '90 days')"
            order_by = "p.closed_at DESC"
        else:
            raise ValueError(f"Unknown pipeline tab '{tab}'")

        params: dict[str, object] = {"clinic_id": clinic_id}
        extra_where = ""
        if doctor_id is not None:
            extra_where += " AND p.assigned_professional_id = :doctor_id"
            params["doctor_id"] = doctor_id
        if search:
            # One clause per word, ANDed: matching the whole string against
            # a single column meant "Juan Pérez" found nobody, because no
            # column holds both words. Both sides are accent-folded so
            # "Perez" finds "Pérez" — between them these were most of what
            # "the search doesn't work by name" meant.
            for index, token in enumerate(search_tokens(search)):
                key = f"q{index}"
                extra_where += (
                    f" AND (translate(p.plan_number, :fold_from, :fold_to) ILIKE :{key}"
                    f" OR translate(pat.first_name, :fold_from, :fold_to) ILIKE :{key}"
                    f" OR translate(pat.last_name, :fold_from, :fold_to) ILIKE :{key})"
                )
                params[key] = f"%{token}%"
            if "q0" in params:
                params["fold_from"] = FOLD_FROM
                params["fold_to"] = FOLD_TO

        # ----- shared SELECT --------------------------------------------
        base_sql = f"""
            WITH item_counts AS (
                SELECT
                    treatment_plan_id AS plan_id,
                    COUNT(*) AS total_count,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending_count
                FROM planned_treatment_items
                WHERE clinic_id = :clinic_id
                GROUP BY treatment_plan_id
            ),
            plan_appts AS (
                SELECT
                    pti.treatment_plan_id AS plan_id,
                    COUNT(*) FILTER (
                        WHERE a.start_time >= NOW()
                          AND a.status NOT IN ('cancelled', 'no_show')
                    ) AS future_count,
                    COUNT(*) FILTER (
                        WHERE a.start_time < NOW()
                          AND a.status NOT IN ('cancelled', 'no_show')
                    ) AS past_count,
                    MAX(a.start_time) FILTER (
                        WHERE a.start_time < NOW()
                          AND a.status NOT IN ('cancelled', 'no_show')
                    ) AS last_past_at,
                    MIN(a.start_time) FILTER (
                        WHERE a.start_time >= NOW()
                          AND a.status NOT IN ('cancelled', 'no_show')
                    ) AS next_future_at
                FROM planned_treatment_items pti
                JOIN appointment_treatments at ON at.planned_treatment_item_id = pti.id
                JOIN appointments a ON a.id = at.appointment_id
                WHERE pti.clinic_id = :clinic_id
                GROUP BY pti.treatment_plan_id
            ),
            next_appt AS (
                SELECT DISTINCT ON (pti.treatment_plan_id)
                    pti.treatment_plan_id AS plan_id,
                    a.id AS id,
                    a.start_time AS start_at,
                    a.cabinet_id AS cabinet_id,
                    a.professional_id AS professional_id
                FROM planned_treatment_items pti
                JOIN appointment_treatments at ON at.planned_treatment_item_id = pti.id
                JOIN appointments a ON a.id = at.appointment_id
                WHERE pti.clinic_id = :clinic_id
                  AND a.start_time >= NOW()
                  AND a.status NOT IN ('cancelled', 'no_show')
                ORDER BY pti.treatment_plan_id, a.start_time ASC
            )
            SELECT
                p.id AS plan_id,
                p.plan_number,
                p.title AS plan_title,
                p.status AS plan_status,
                p.closure_reason,
                p.confirmed_at,
                p.closed_at,
                p.updated_at,
                pat.id AS patient_id,
                pat.first_name,
                pat.last_name,
                pat.phone,
                COALESCE(items.total_count, 0) AS items_total,
                COALESCE(items.completed_count, 0) AS items_completed,
                b.id AS budget_id,
                b.status AS budget_status,
                b.total AS budget_total,
                b.valid_until,
                b.last_reminder_sent_at,
                b.viewed_at,
                na.id AS next_appt_id,
                na.start_at AS next_appt_start_at,
                na.cabinet_id AS next_appt_cabinet,
                na.professional_id AS next_appt_professional
            FROM treatment_plans p
            JOIN patients pat ON pat.id = p.patient_id
            LEFT JOIN budgets b ON b.id = p.budget_id
            LEFT JOIN item_counts items ON items.plan_id = p.id
            LEFT JOIN plan_appts appt ON appt.plan_id = p.id
            LEFT JOIN next_appt na ON na.plan_id = p.id
            WHERE p.clinic_id = :clinic_id
              AND p.deleted_at IS NULL
              AND ({tab_where})
              {extra_where}
        """

        # ----- count + page ---------------------------------------------
        count_result = await db.execute(
            sa_text(f"SELECT COUNT(*) AS total FROM ({base_sql}) sub"),
            params,
        )
        total = count_result.scalar() or 0

        page_params = dict(params)
        page_params["limit"] = page_size
        page_params["offset"] = (page - 1) * page_size
        rows_result = await db.execute(
            sa_text(f"{base_sql} ORDER BY {order_by} LIMIT :limit OFFSET :offset"),
            page_params,
        )

        # ----- shape rows -----------------------------------------------
        now = datetime.now(UTC)
        out: list[dict] = []
        for r in rows_result.mappings().all():
            anchor = r["confirmed_at"] or r["closed_at"] or r["updated_at"]
            days_in_status = (now - anchor).days if anchor is not None else 0
            patient_brief = {
                "id": r["patient_id"],
                "first_name": r["first_name"],
                "last_name": r["last_name"],
                "phone": r["phone"],
            }
            budget_brief = None
            if r["budget_id"]:
                budget_brief = {
                    "id": r["budget_id"],
                    "status": r["budget_status"],
                    "total": float(r["budget_total"]) if r["budget_total"] is not None else None,
                    "valid_until": r["valid_until"],
                    "last_reminder_sent_at": r["last_reminder_sent_at"],
                    "viewed_at": r["viewed_at"],
                }
            next_appt = None
            if r["next_appt_id"]:
                next_appt = {
                    "id": r["next_appt_id"],
                    "start_at": r["next_appt_start_at"],
                    "cabinet_id": r["next_appt_cabinet"],
                    "professional_id": r["next_appt_professional"],
                }
            out.append(
                {
                    "plan_id": r["plan_id"],
                    "plan_number": r["plan_number"],
                    "plan_title": r["plan_title"],
                    "plan_status": r["plan_status"],
                    "days_in_status": max(days_in_status, 0),
                    "closure_reason": r["closure_reason"],
                    "items_total": r["items_total"],
                    "items_completed": r["items_completed"],
                    "patient": patient_brief,
                    "budget": budget_brief,
                    "next_appointment": next_appt,
                }
            )
        return out, total

    # -------------------------------------------------------------------------
    # Workflow Transitions (confirm / close / reactivate)
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_plan_snapshot(plan: TreatmentPlan, patient: Patient | None) -> dict:
        """Build the snapshot payload used for cross-module events."""
        items_payload = []
        total_estimated = 0.0
        for item in plan.items:
            treatment = item.treatment
            if treatment is None:
                continue
            primary_tooth = treatment.teeth[0].tooth_number if treatment.teeth else None
            primary_surfaces = treatment.teeth[0].surfaces if treatment.teeth else None
            unit_price = (
                str(treatment.price_snapshot) if treatment.price_snapshot is not None else None
            )
            if unit_price is not None:
                try:
                    total_estimated += float(unit_price)
                except (TypeError, ValueError):
                    pass
            items_payload.append(
                {
                    "item_id": str(item.id),
                    "treatment_id": str(treatment.id),
                    "catalog_item_id": (
                        str(treatment.catalog_item_id) if treatment.catalog_item_id else None
                    ),
                    "tooth_number": primary_tooth,
                    "surfaces": primary_surfaces,
                    "unit_price": unit_price,
                }
            )
        patient_full_name = None
        if patient is not None:
            parts = [patient.first_name, patient.last_name]
            patient_full_name = " ".join(p for p in parts if p) or None
        return {
            "plan_id": str(plan.id),
            "plan_number": plan.plan_number,
            "clinic_id": str(plan.clinic_id),
            "patient_id": str(plan.patient_id),
            "patient_full_name": patient_full_name,
            "items": items_payload,
            "total_estimated": str(total_estimated),
        }

    @staticmethod
    async def informed_consent_missing(
        db: AsyncSession, clinic_id: UUID, plan: TreatmentPlan
    ) -> bool:
        """Whether the clinic asks for a signed informed consent for this
        plan and it has none.

        The consents module's to say (ADR 0039); with that App off nobody
        asks. A plan in this state is not confirmed. One confirmed before
        the clinic asked, or whose letter was revoked, keeps going — its
        treatments can still be performed — and the screen says in red
        that the letter is missing.
        """
        consents = provider(PlanConsents)
        return bool(
            consents
            and await consents.lacks_required_consent(db, clinic_id, plan.patient_id, plan.id)
        )

    @staticmethod
    async def confirm(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        user_id: UUID,
    ) -> TreatmentPlan:
        """Doctor confirmation: ``draft`` → ``pending``.

        Side effects:

        - Sets ``confirmed_at``.
        - Publishes ``treatment_plan.confirmed`` with a snapshot payload.
          ``budget`` hears it and mints the draft budget in its own
          transaction, then announces ``budget.created_for_plan``, which
          links it here (``events.on_budget_created_for_plan``). The plan
          does not call ``budget`` and does not wait for it (ADR 0042): a
          budget that fails to appear leaves a confirmed plan whose next
          step is "generate budget".
        - With the Budgets App off there is no acceptance to wait for, so
          the plan goes straight on to ``active``.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")

        if plan.status != "draft":
            raise ValueError(f"Cannot confirm plan in status '{plan.status}'")
        if not plan.items:
            raise ValueError("Cannot confirm plan without treatments")

        # The clinic may ask for the patient's informed consent to this
        # plan first.
        if await TreatmentPlanService.informed_consent_missing(db, clinic_id, plan):
            raise InformedConsentRequiredError(
                "The plan needs a signed informed consent before it is confirmed"
            )

        # Atomic transition.
        plan.status = "pending"
        plan.confirmed_at = datetime.now(UTC)

        # Resolve patient for the snapshot. The relationship is OK to
        # use — patients is in our depends.
        patient = await db.get(Patient, plan.patient_id)
        snapshot = TreatmentPlanService._build_plan_snapshot(plan, patient)
        snapshot["confirmed_at"] = plan.confirmed_at.isoformat()
        snapshot["confirmed_by_user_id"] = str(user_id)

        # The budget the plan still links to, if it is live. `budget` mints
        # a new one unless this is set — after a reopen the link points at
        # a cancelled budget, which does not count.
        live_budget = plan.budget if plan.budget and plan.budget.status != "cancelled" else None
        snapshot["budget_id"] = str(live_budget.id) if live_budget else None
        snapshot["plan_status"] = "pending"

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="confirmed",
            actor_user_id=user_id,
            from_status="draft",
            to_status="pending",
        )

        # Acceptance of the budget is what moves a plan from `pending` to
        # `active`. With the Budgets App off nobody will ever accept one.
        budgets_available = provider(PlanBudgets) is not None
        if not budgets_available:
            plan.status = "active"
            TreatmentPlanService.record_history(
                db,
                clinic_id=clinic_id,
                plan_id=plan.id,
                action="started",
                from_status="pending",
                to_status="active",
                payload={"trigger": "budgets_unavailable"},
            )

        await db.flush()

        event_bus.publish_after_commit(db, EventType.TREATMENT_PLAN_CONFIRMED, snapshot)
        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": "draft",
                "new_status": plan.status,
                "clinic_id": str(clinic_id),
            },
        )
        return plan

    @staticmethod
    async def reopen(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        user_id: UUID,
    ) -> TreatmentPlan:
        """Reopen a plan that is under way back to ``draft``.

        ``budget`` cancels the linked budget when it hears the status
        change (ADR 0042), so reception can edit items again. Until it has,
        the plan is already a draft, and a draft is editable.

        Accepts ``active`` as well as ``pending``. It used to take only
        ``pending``, which was fine while acceptance was the sole way in;
        now that attending the first consultation moves a plan to
        ``active``, keeping the old rule would have made every plan
        unreopenable the moment the patient walked in — the case most in
        need of editing, because that visit is usually where the real
        treatment gets decided. ``completed`` and ``closed`` stay out:
        those are finished, and reactivation is their door.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")
        if plan.status not in ("pending", "active"):
            raise ValueError(f"Cannot reopen plan in status '{plan.status}'")
        previous_status = plan.status

        live_budget = plan.budget if plan.budget and plan.budget.status != "cancelled" else None
        cancelled_budget = live_budget.budget_number if live_budget else None

        plan.status = "draft"
        plan.confirmed_at = None

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="reopened",
            actor_user_id=user_id,
            from_status=previous_status,
            to_status="draft",
            payload={"cancelled_budget": cancelled_budget} if cancelled_budget else None,
        )

        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": previous_status,
                "new_status": "draft",
                "clinic_id": str(clinic_id),
                # What `budget` needs to cancel the plan's budget.
                "budget_id": str(live_budget.id) if live_budget else None,
                "user_id": str(user_id),
            },
        )
        # The draft is no longer held by that budget, whatever the brief
        # loaded a moment ago says.
        plan.budget = None
        return plan

    @staticmethod
    async def close(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        user_id: UUID,
        closure_reason: str,
        closure_note: str | None = None,
    ) -> TreatmentPlan:
        """Move the plan to terminal ``closed`` state.

        Allowed from ``draft``, ``pending`` or ``active``. The reason
        must be one of the catalogue keys in ``VALID_CLOSURE_REASONS``
        — free-text detail belongs in ``closure_note``.
        """
        if closure_reason not in VALID_CLOSURE_REASONS:
            raise ValueError(f"Unknown closure_reason '{closure_reason}'")

        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")
        if "closed" not in VALID_PLAN_TRANSITIONS.get(plan.status, set()):
            raise ValueError(f"Cannot close plan in status '{plan.status}'")
        if closure_reason == CANCEL_CLOSURE_REASON:
            await TreatmentPlanService._guard_collections(db, clinic_id, plan)

        previous_status = plan.status
        plan.status = "closed"
        plan.closure_reason = closure_reason
        plan.closure_note = closure_note
        plan.closed_at = datetime.now(UTC)

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="closed",
            actor_user_id=user_id,
            from_status=previous_status,
            to_status="closed",
            payload={"reason": closure_reason, "note": closure_note},
        )

        # Drop the plan's hold on its planned Treatments.
        await TreatmentPlanService._cleanup_orphan_planned_treatments(db, clinic_id, plan, user_id)
        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_CLOSED,
            {
                "plan_id": str(plan.id),
                "clinic_id": str(clinic_id),
                "patient_id": str(plan.patient_id),
                "closure_reason": closure_reason,
                "closure_note": closure_note,
                "closed_at": plan.closed_at.isoformat(),
                "closed_by_user_id": str(user_id),
                "previous_status": previous_status,
            },
        )
        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": previous_status,
                "new_status": "closed",
                "clinic_id": str(clinic_id),
            },
        )
        return plan

    @staticmethod
    async def reactivate(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        user_id: UUID,
    ) -> TreatmentPlan:
        """Revive a closed plan back to ``draft`` for a new cycle."""
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")
        if plan.status != "closed":
            raise ValueError(f"Cannot reactivate plan in status '{plan.status}'")

        previous_reason = plan.closure_reason
        plan.status = "draft"
        plan.closure_reason = None
        plan.closure_note = None
        plan.closed_at = None
        plan.confirmed_at = None

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="reactivated",
            actor_user_id=user_id,
            from_status="closed",
            to_status="draft",
            payload={"previous_reason": previous_reason},
        )

        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_REACTIVATED,
            {
                "plan_id": str(plan.id),
                "clinic_id": str(clinic_id),
                "patient_id": str(plan.patient_id),
                "previous_closure_reason": previous_reason,
                "reactivated_at": datetime.now(UTC).isoformat(),
                "reactivated_by_user_id": str(user_id),
            },
        )
        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": "closed",
                "new_status": "draft",
                "clinic_id": str(clinic_id),
            },
        )
        return plan

    @staticmethod
    async def activate_from_attendance(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
    ) -> TreatmentPlan | None:
        """``pending`` → ``active`` because the patient turned up.

        The clinic counts a plan as under way from the first consultation
        the patient actually attends, which happens well before the
        budget is signed — so attendance is a second, independent road
        into ``active`` alongside ``accept_from_budget``.

        "Attended" is read from the work, not only from the diary: a
        completed appointment says so, and so does a finished treatment,
        including one ticked off straight on the plan with no appointment
        behind it (``completed_without_appointment``) — which is how a
        first consultation is often recorded. Keying this to appointments
        alone left those plans stranded in ``pending`` with work already
        done against them. Every completion path reaches this through
        ``_sync_plan_lifecycle``.

        Idempotent and deliberately narrow: only a ``pending`` plan
        moves. A ``draft`` plan is one nobody has confirmed yet and must
        not skip the confirmation step, and ``active`` / ``completed`` /
        ``closed`` are left exactly as they are.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None
        if plan.status != "pending":
            return plan

        plan.status = "active"

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="started",
            from_status="pending",
            to_status="active",
            payload={"trigger": "work_recorded"},
        )

        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": "pending",
                "new_status": "active",
                "clinic_id": str(clinic_id),
                "triggered_by": "appointment_attended",
            },
        )
        return plan

    @staticmethod
    async def accept_from_budget(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
    ) -> TreatmentPlan | None:
        """``pending`` → ``active`` triggered by ``budget.accepted``.

        Idempotent: if the plan is already active or closed, returns the
        current plan without raising.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None
        if plan.status == "active":
            return plan
        if plan.status != "pending":
            logger.warning(
                "Ignoring budget.accepted for plan %s in status '%s'",
                plan_id,
                plan.status,
            )
            return plan

        plan.status = "active"

        TreatmentPlanService.record_history(
            db,
            clinic_id=clinic_id,
            plan_id=plan.id,
            action="started",
            from_status="pending",
            to_status="active",
            payload={"trigger": "budget_accepted"},
        )

        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": "pending",
                "new_status": "active",
                "clinic_id": str(clinic_id),
            },
        )
        return plan

    @staticmethod
    async def reject_from_budget(
        db: AsyncSession,
        clinic_id: UUID,
        plan_id: UUID,
        rejection_note: str | None = None,
    ) -> TreatmentPlan | None:
        """Close the plan in response to ``budget.rejected``.

        Sets ``closure_reason='rejected_by_patient'``. Idempotent: if
        the plan is already closed or beyond pending, no-op.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None
        if plan.status == "closed":
            return plan
        if plan.status != "pending":
            logger.warning(
                "Ignoring budget.rejected for plan %s in status '%s'",
                plan_id,
                plan.status,
            )
            return plan

        previous_status = plan.status
        plan.status = "closed"
        plan.closure_reason = "rejected_by_patient"
        plan.closure_note = rejection_note
        plan.closed_at = datetime.now(UTC)
        await db.flush()

        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_CLOSED,
            {
                "plan_id": str(plan.id),
                "clinic_id": str(clinic_id),
                "patient_id": str(plan.patient_id),
                "closure_reason": "rejected_by_patient",
                "closure_note": rejection_note,
                "closed_at": plan.closed_at.isoformat(),
                "closed_by_user_id": None,
                "previous_status": previous_status,
            },
        )
        event_bus.publish_after_commit(
            db,
            EventType.TREATMENT_PLAN_STATUS_CHANGED,
            {
                "plan_id": str(plan.id),
                "old_status": previous_status,
                "new_status": "closed",
                "clinic_id": str(clinic_id),
            },
        )
        return plan
