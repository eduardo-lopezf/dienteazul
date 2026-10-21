"""Turn charted findings into proposed plan items.

The chart already knows the patient has caries on 16, 26 and 36 — a dentist
put them there. Re-entering all three as plan items is retyping a clinical
fact the system holds, and it is the single most repetitive step in building
a plan.

This module reads the findings and proposes a treatment for each. It proposes
only; nothing is created until the dentist ticks a row. That matters, because
the mapping below is clinical judgement compressed into a table and it will be
wrong sometimes — a fractured tooth may need a composite, an overlay or a
crown depending on how much wall is left, and no table knows that.
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.models import TreatmentCatalogItem, dentition_fits
from app.modules.odontogram.models import Treatment, TreatmentTooth

from .models import PlanDismissedFinding, PlannedTreatmentItem, TreatmentPlan

logger = logging.getLogger(__name__)

# Findings — charted observations, not work done. They are stored as
# ``Treatment`` rows with ``status='performed'`` (the chart's way of saying
# "this is how the mouth is") and no catalog link.
FINDING_TYPES: Final[tuple[str, ...]] = (
    "caries",
    "incipient_caries",
    "pulpitis",
    "fracture",
    "missing",
    "periapical_small",
    "periapical_medium",
    "periapical_large",
)

# Preferred catalog codes per finding, most specific first. The first code
# present in the clinic's catalog, and fit for the tooth's dentition, wins; a
# clinic that renamed everything gets no proposal for that finding rather than
# a wrong one — and so does a missing primary tooth, which no implant answers.
#
# Deliberately conservative. Where the honest answer depends on how much tooth
# is left (a fracture) the least invasive option is proposed, because a
# dentist upgrading a composite to a crown is a smaller correction than the
# reverse.
SUGGESTIONS: Final[dict[str, tuple[str, ...]]] = {
    "caries": ("REST-COMP", "REST-AMAL"),
    "incipient_caries": ("REST-COMP",),
    # An inflamed pulp needs the canal treated; the root count decides which
    # code, which is why this one is resolved per tooth in `_suggest`. The
    # adult codes are for permanent teeth only, so a primary tooth falls
    # through to its own: a pulpotomy, or a pulpectomy once the apex is hit.
    "pulpitis": ("ENDO-MULTI", "ENDO-BI", "ENDO-UNI", "PED-PULPOTOMY"),
    "periapical_small": ("ENDO-MULTI", "ENDO-BI", "ENDO-UNI", "PED-PULPECTOMY"),
    "periapical_medium": ("ENDO-MULTI", "ENDO-BI", "ENDO-UNI", "PED-PULPECTOMY"),
    "periapical_large": ("ENDO-MULTI", "ENDO-BI", "ENDO-UNI", "PED-PULPECTOMY"),
    "fracture": ("REST-RECONSTR", "REST-COMP"),
    "missing": ("SURG-IMP-TI", "REST-BRIDGE-MC"),
}

# Root count by FDI position, used to pick the right endodontic code.
# Molars (positions 6–8) are multi-rooted; premolars (4–5) usually
# bi-rooted; anteriors (1–3) single.
_MULTI_ROOT_POSITIONS: Final[set[int]] = {6, 7, 8}
_BI_ROOT_POSITIONS: Final[set[int]] = {4, 5}


def _endodontic_code(tooth_number: int) -> str:
    position = tooth_number % 10
    if position in _MULTI_ROOT_POSITIONS:
        return "ENDO-MULTI"
    if position in _BI_ROOT_POSITIONS:
        return "ENDO-BI"
    return "ENDO-UNI"


def _preferred_codes(clinical_type: str, tooth_number: int | None) -> tuple[str, ...]:
    codes = SUGGESTIONS.get(clinical_type, ())
    if not codes:
        return ()
    if clinical_type.startswith("periapical") or clinical_type == "pulpitis":
        if tooth_number is None:
            return codes
        # Put the root-count match first, keep the rest as fallbacks.
        preferred = _endodontic_code(tooth_number)
        return (preferred, *(c for c in codes if c != preferred))
    return codes


class PlanProposalService:
    """Read charted findings and propose treatments for them."""

    @staticmethod
    async def list_proposals(db: AsyncSession, clinic_id: UUID, plan_id: UUID) -> list[dict] | None:
        """Findings on this patient that nothing is planned for yet.

        A tooth that already has a planned treatment is left out entirely —
        coarse on purpose. Guessing whether an existing plan line addresses a
        given finding would be a guess; showing a finding the dentist has
        already dealt with is worse than showing one less.
        """
        plan = await db.execute(
            select(TreatmentPlan).where(
                TreatmentPlan.id == plan_id,
                TreatmentPlan.clinic_id == clinic_id,
                TreatmentPlan.deleted_at.is_(None),
            )
        )
        plan_row = plan.scalar_one_or_none()
        if plan_row is None:
            return None

        dismissed = await PlanProposalService._dismissed_for_plan(db, plan_id)
        proposals = await PlanProposalService.for_patient(db, clinic_id, plan_row.patient_id)
        return [p for p in proposals if p["finding_id"] not in dismissed]

    @staticmethod
    async def for_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> list[dict]:
        """The same findings, read before any plan exists.

        The builder opens on a blank chart because it has no patient yet, but
        when it is reached from a patient's record it does — and by then the
        clinic has usually already charted what is wrong. Without this the
        dentist redraws, tooth by tooth, work the chart already holds, and
        only learns what was missed after the plan is saved, from
        ``list_proposals``.

        Split out rather than duplicated: the mapping from a finding to a
        treatment is clinical judgement (see ``SUGGESTIONS``) and must have
        exactly one home.
        """
        result = await db.execute(
            select(Treatment)
            .options(selectinload(Treatment.teeth))
            .where(
                Treatment.clinic_id == clinic_id,
                Treatment.patient_id == patient_id,
                Treatment.deleted_at.is_(None),
                Treatment.clinical_type.in_(FINDING_TYPES),
                Treatment.status == "performed",
            )
        )
        findings = list(result.scalars().unique().all())
        if not findings:
            return []

        planned_teeth = await PlanProposalService._teeth_with_planned_work(
            db, clinic_id, patient_id
        )

        catalog = await PlanProposalService._catalog_by_code(db, clinic_id)

        proposals: list[dict] = []
        for finding in findings:
            tooth_number = finding.teeth[0].tooth_number if finding.teeth else None
            if tooth_number is not None and tooth_number in planned_teeth:
                continue

            suggestion = next(
                (
                    catalog[code]
                    for code in _preferred_codes(finding.clinical_type, tooth_number)
                    if code in catalog
                    and (
                        tooth_number is None
                        or dentition_fits(catalog[code].dentition, tooth_number)
                    )
                ),
                None,
            )
            proposals.append(
                {
                    "finding_id": finding.id,
                    "clinical_type": finding.clinical_type,
                    "tooth_number": tooth_number,
                    "surfaces": finding.teeth[0].surfaces if finding.teeth else None,
                    "suggested_catalog_item": suggestion,
                }
            )
        return proposals

    @staticmethod
    async def _dismissed_for_plan(db: AsyncSession, plan_id: UUID) -> set[UUID]:
        result = await db.execute(
            select(PlanDismissedFinding.finding_id).where(
                PlanDismissedFinding.treatment_plan_id == plan_id
            )
        )
        return set(result.scalars().all())

    @staticmethod
    async def dismiss(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID,
        plan_id: UUID,
        finding_ids: list[UUID],
    ) -> int:
        """Record that this plan is not the answer to these findings.

        Idempotent on ``(plan, finding)``: the builder sends the whole list it
        dismissed, and a dentist who deletes a line, undoes, and deletes it
        again has still made one decision. Unknown ids are skipped rather than
        refused — a finding deleted from the chart between the draft and
        *Crear* is not a reason to lose the plan.
        """
        if not finding_ids:
            return 0

        known = await db.execute(
            select(Treatment.id).where(
                Treatment.clinic_id == clinic_id,
                Treatment.id.in_(finding_ids),
                Treatment.deleted_at.is_(None),
            )
        )
        valid = set(known.scalars().all())
        if not valid:
            return 0

        already = await PlanProposalService._dismissed_for_plan(db, plan_id)
        added = 0
        for finding_id in valid - already:
            db.add(
                PlanDismissedFinding(
                    clinic_id=clinic_id,
                    treatment_plan_id=plan_id,
                    finding_id=finding_id,
                    dismissed_by=user_id,
                )
            )
            added += 1
        await db.flush()
        return added

    @staticmethod
    async def _teeth_with_planned_work(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> set[int]:
        result = await db.execute(
            select(TreatmentTooth.tooth_number)
            .join(Treatment, Treatment.id == TreatmentTooth.treatment_id)
            .where(
                Treatment.clinic_id == clinic_id,
                Treatment.patient_id == patient_id,
                Treatment.deleted_at.is_(None),
                Treatment.status == "planned",
            )
        )
        return set(result.scalars().all())

    @staticmethod
    async def _catalog_by_code(
        db: AsyncSession, clinic_id: UUID
    ) -> dict[str, TreatmentCatalogItem]:
        codes = {code for values in SUGGESTIONS.values() for code in values}
        result = await db.execute(
            select(TreatmentCatalogItem).where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.internal_code.in_(codes),
                TreatmentCatalogItem.is_active.is_(True),
            )
        )
        return {item.internal_code: item for item in result.scalars().all()}

    @staticmethod
    async def accept(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID,
        plan_id: UUID,
        finding_ids: list[UUID],
    ) -> list[PlannedTreatmentItem]:
        """Create a planned treatment for each accepted finding.

        The finding itself is left untouched: the diagnosis and the plan are
        separate records, and the chart should keep showing the caries until
        it is actually treated.
        """
        from app.modules.odontogram.service import TreatmentService

        from .service import TreatmentPlanService

        proposals = await PlanProposalService.list_proposals(db, clinic_id, plan_id)
        if proposals is None:
            raise ValueError("Plan not found")

        wanted = set(finding_ids)
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if plan is None:
            raise ValueError("Plan not found")

        created: list[PlannedTreatmentItem] = []
        for proposal in proposals:
            if proposal["finding_id"] not in wanted:
                continue
            catalog_item = proposal["suggested_catalog_item"]
            if catalog_item is None or proposal["tooth_number"] is None:
                # Nothing sensible to create. Skipping keeps the rest of the
                # batch working instead of failing all of it over one row.
                continue

            treatment = await TreatmentService.create(
                db=db,
                clinic_id=clinic_id,
                patient_id=plan.patient_id,
                user_id=user_id,
                catalog_item_id=catalog_item.id,
                clinical_type=None,
                tooth_numbers=[proposal["tooth_number"]],
                teeth=None,
                common_surfaces=proposal["surfaces"] or None,
                status="planned",
                notes=None,
                budget_item_id=None,
                source_module="treatment_plan",
                scope="tooth",
            )
            item = await TreatmentPlanService.add_item(
                db, clinic_id, plan_id, {"treatment_id": treatment.id}
            )
            if item is not None:
                created.append(item)

        return created
