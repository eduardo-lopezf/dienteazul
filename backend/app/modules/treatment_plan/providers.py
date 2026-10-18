"""What treatment_plan offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import PlannedTreatmentBrief, ProfessionalActivity, TreatmentLink
from app.modules.catalog.models import TreatmentCatalogItem
from app.modules.odontogram.models import Treatment

from .models import PlannedTreatmentItem, TreatmentPlan


class PlannedTreatmentsProvider:
    async def problems(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID, item_ids: Collection[UUID]
    ) -> list[str]:
        if not item_ids:
            return []
        result = await db.execute(
            select(PlannedTreatmentItem)
            .options(selectinload(PlannedTreatmentItem.treatment_plan))
            .where(PlannedTreatmentItem.id.in_(item_ids))
        )
        items = {item.id: item for item in result.scalars().all()}

        errors: list[str] = []
        for item_id in item_ids:
            item = items.get(item_id)
            if not item or item.clinic_id != clinic_id:
                errors.append(f"Treatment item {item_id} not found")
                continue
            plan = item.treatment_plan
            if not plan or plan.patient_id != patient_id:
                errors.append(f"Treatment item {item_id} does not belong to patient")
                continue
            if plan.status not in ("active", "draft"):
                errors.append(f"Treatment item {item_id} belongs to {plan.status} plan")
                continue
            if item.status != "pending":
                errors.append(f"Treatment item {item_id} is already {item.status}")
        return errors

    async def catalog_item_ids(
        self, db: AsyncSession, clinic_id: UUID, item_ids: Collection[UUID]
    ) -> dict[UUID, UUID | None]:
        if not item_ids:
            return {}
        result = await db.execute(
            select(PlannedTreatmentItem.id, Treatment.catalog_item_id)
            .join(Treatment, Treatment.id == PlannedTreatmentItem.treatment_id, isouter=True)
            .where(
                PlannedTreatmentItem.clinic_id == clinic_id,
                PlannedTreatmentItem.id.in_(item_ids),
            )
        )
        return {row[0]: row[1] for row in result.all()}

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, links: Collection[TreatmentLink]
    ) -> dict[UUID, PlannedTreatmentBrief]:
        if not links:
            return {}

        result = await db.execute(
            select(PlannedTreatmentItem)
            .options(
                selectinload(PlannedTreatmentItem.treatment).options(
                    selectinload(Treatment.teeth),
                    selectinload(Treatment.catalog_item),
                ),
                selectinload(PlannedTreatmentItem.treatment_plan),
            )
            .where(
                PlannedTreatmentItem.clinic_id == clinic_id,
                PlannedTreatmentItem.id.in_({link.planned_item_id for link in links}),
            )
        )
        items = {item.id: item for item in result.scalars().all()}

        # The link may name a catalog item of its own; the treatment's is
        # the fallback.
        own_catalog_ids = {link.catalog_item_id for link in links if link.catalog_item_id}
        own_catalog: dict[UUID, TreatmentCatalogItem] = {}
        if own_catalog_ids:
            rows = await db.execute(
                select(TreatmentCatalogItem).where(TreatmentCatalogItem.id.in_(own_catalog_ids))
            )
            own_catalog = {row.id: row for row in rows.scalars().all()}

        briefs: dict[UUID, PlannedTreatmentBrief] = {}
        for link in links:
            item = items.get(link.planned_item_id)
            treatment = item.treatment if item else None
            catalog_item = own_catalog.get(link.catalog_item_id) if link.catalog_item_id else None
            if not catalog_item and treatment:
                catalog_item = treatment.catalog_item

            tooth_number = None
            surfaces = None
            is_global = True
            if treatment and treatment.teeth:
                primary = treatment.teeth[0]
                tooth_number = primary.tooth_number
                surfaces = primary.surfaces
                is_global = False

            price: float | None = None
            if treatment and treatment.price_snapshot is not None:
                price = float(treatment.price_snapshot)
            elif catalog_item and catalog_item.default_price is not None:
                price = float(catalog_item.default_price)

            briefs[link.id] = PlannedTreatmentBrief(
                planned_item_status=item.status if item else "pending",
                catalog_item_id=catalog_item.id if catalog_item else None,
                internal_code=catalog_item.internal_code if catalog_item else "",
                names=catalog_item.names if catalog_item else {},
                default_price=price,
                default_duration_minutes=(
                    catalog_item.default_duration_minutes if catalog_item else None
                ),
                tooth_number=tooth_number,
                surfaces=surfaces,
                is_global=is_global,
                plan_id=item.treatment_plan_id if item else None,
                plan_number=(
                    item.treatment_plan.plan_number if item and item.treatment_plan else None
                ),
            )
        return briefs


planned_treatments = PlannedTreatmentsProvider()


class PlanQuotesProvider:
    async def snapshot(self, db: AsyncSession, clinic_id: UUID, plan_id: UUID) -> dict | None:
        from app.modules.patients.models import Patient

        from .service import TreatmentPlanService

        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if plan is None:
            return None
        patient = await db.get(Patient, plan.patient_id)
        snapshot = TreatmentPlanService._build_plan_snapshot(plan, patient)
        snapshot["plan_status"] = plan.status
        snapshot["budget_id"] = str(plan.budget_id) if plan.budget_id else None
        return snapshot


#: A plan still being worked: confirmed and not finished.
_PLANS_IN_PROGRESS = ("pending", "active")


class PlanWorkload:
    """Each professional's plans and treatments, for their profile (ADR 0039).

    A plan is theirs when they are its doctor, a treatment when it is
    assigned to them. Deleted plans and cancelled treatments count for
    nothing; a draft plan's patient is not yet one they see.
    """

    async def activity(
        self, db: AsyncSession, clinic_id: UUID, professional_ids: Collection[UUID]
    ) -> dict[UUID, ProfessionalActivity]:
        if not professional_ids:
            return {}
        patients: dict[UUID, set[UUID]] = defaultdict(set)
        counts: dict[UUID, dict[str, int]] = defaultdict(
            lambda: {"plans_in_progress": 0, "treatments_pending": 0, "treatments_completed": 0}
        )

        plans = await db.execute(
            select(
                TreatmentPlan.assigned_professional_id,
                TreatmentPlan.patient_id,
                TreatmentPlan.status,
            ).where(
                TreatmentPlan.clinic_id == clinic_id,
                TreatmentPlan.assigned_professional_id.in_(professional_ids),
                TreatmentPlan.deleted_at.is_(None),
                TreatmentPlan.status != "draft",
            )
        )
        for row in plans.all():
            patients[row.assigned_professional_id].add(row.patient_id)
            if row.status in _PLANS_IN_PROGRESS:
                counts[row.assigned_professional_id]["plans_in_progress"] += 1

        items = await db.execute(
            select(
                PlannedTreatmentItem.assigned_professional_id,
                PlannedTreatmentItem.status,
                TreatmentPlan.patient_id,
            )
            .join(TreatmentPlan, PlannedTreatmentItem.treatment_plan_id == TreatmentPlan.id)
            .where(
                TreatmentPlan.clinic_id == clinic_id,
                TreatmentPlan.deleted_at.is_(None),
                TreatmentPlan.status != "draft",
                PlannedTreatmentItem.assigned_professional_id.in_(professional_ids),
                PlannedTreatmentItem.status != "cancelled",
            )
        )
        for row in items.all():
            patients[row.assigned_professional_id].add(row.patient_id)
            key = "treatments_completed" if row.status == "completed" else "treatments_pending"
            counts[row.assigned_professional_id][key] += 1

        return {
            professional_id: ProfessionalActivity(
                patient_ids=frozenset(patients[professional_id]),
                counts=counts[professional_id],
            )
            # Every one asked about: no plans is a zero, not silence.
            for professional_id in professional_ids
        }


plan_quotes = PlanQuotesProvider()
workload = PlanWorkload()
