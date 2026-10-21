"""Plan templates: CRUD, seeding, and applying one to a plan.

A template is a shape — an ordered list of catalog items with their stage of
care — and nothing patient-specific. Applying it is where the teeth arrive.

The apply rule is deliberately one sentence, because a dentist has to be able
to predict it: **every per-tooth item is created once per tooth supplied, and
everything whole-mouth is created once.** That single rule covers the three
shapes that actually occur — a whole-mouth workup with no teeth at all, a
three-step sequence on one tooth, and the same act repeated across quadrants
or a set of molars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.models import Specialty, TreatmentCatalogItem, dentition_fits
from app.modules.odontogram.models import Treatment
from app.modules.odontogram.service import TreatmentService

from .models import PlannedTreatmentItem, PlanTemplate, PlanTemplateItem, TreatmentPlan
from .service import TreatmentPlanService
from .templates_seed import PLAN_TEMPLATES

logger = logging.getLogger(__name__)

# Scopes that need at least one tooth before anything can be created.
_TOOTH_SCOPES = ("tooth", "multi_tooth")


@dataclass(frozen=True)
class SkippedLine:
    """A template line that could not be applied, and why.

    ``not_in_catalog``: the clinic never had that treatment, or retired it.
    It is not an error — a clinic that refers its orthodontics out still
    wants the rest of an orthognathic plan — but it must not be silent.

    ``wrong_dentition``: the treatment is for primary teeth only (or
    permanent only) and some of the teeth given are of the other dentition.
    The teeth it fits still get it; the name carries the ones left out.
    """

    name: str
    reason: str


@dataclass(frozen=True)
class PlanLine:
    """One hand-drawn plan line: a catalog item and the teeth it is for."""

    catalog_item_id: UUID
    tooth_numbers: list[int]
    surfaces: list[str] | None = None
    phase: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ApplyResult:
    items: list[PlannedTreatmentItem]
    skipped: list[SkippedLine]


class TemplateNeedsTeethError(ValueError):
    """The template has per-tooth items but the caller supplied no teeth.

    Carries the offending item names so the UI can say *which* treatments are
    waiting for a tooth instead of a bare "missing field".
    """

    def __init__(self, item_names: list[str]) -> None:
        self.item_names = item_names
        super().__init__(f"Template needs teeth for: {', '.join(item_names)}")


def _arch_of(tooth_number: int) -> str:
    """FDI quadrants 1 and 2 are the upper arch, 3 and 4 the lower."""
    return "upper" if tooth_number // 10 in (1, 2, 5, 6) else "lower"


def _template_loader() -> list:
    return [
        selectinload(PlanTemplate.items).selectinload(PlanTemplateItem.catalog_item),
    ]


class PlanTemplateService:
    """Business logic for reusable plan templates."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @staticmethod
    async def list_templates(
        db: AsyncSession, clinic_id: UUID, *, include_inactive: bool = False
    ) -> list[PlanTemplate]:
        stmt = (
            select(PlanTemplate)
            .options(*_template_loader())
            .where(PlanTemplate.clinic_id == clinic_id)
            .order_by(PlanTemplate.display_order, PlanTemplate.name)
        )
        if not include_inactive:
            stmt = stmt.where(PlanTemplate.is_active.is_(True))
        result = await db.execute(stmt)
        return list(result.scalars().unique().all())

    @staticmethod
    async def specialties_by_key(db: AsyncSession, clinic_id: UUID) -> dict[str, Specialty]:
        """Template ``key`` -> the discipline it belongs to, as the clinic names it.

        Only the reference templates have one. A template the clinic saved
        from its own plan has no ``key`` and belongs to no discipline.
        """
        rows = await db.execute(
            select(Specialty).where(Specialty.clinic_id == clinic_id, Specialty.key.is_not(None))
        )
        by_key = {row.key: row for row in rows.scalars()}
        return {
            spec["key"]: by_key[spec["specialty"]]
            for spec in PLAN_TEMPLATES
            if spec["specialty"] in by_key
        }

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, template_id: UUID) -> PlanTemplate | None:
        """Load a template with its lines.

        ``populate_existing`` because this is the read that runs straight
        after a write: without it the identity map hands back the collection
        as it was before ``_replace_items``, and a PUT answers with the old
        line-up while the database holds the new one.
        """
        result = await db.execute(
            select(PlanTemplate)
            .options(*_template_loader())
            .where(PlanTemplate.id == template_id, PlanTemplate.clinic_id == clinic_id)
            .execution_options(populate_existing=True)
        )
        return result.scalars().unique().one_or_none()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @staticmethod
    async def create(
        db: AsyncSession, clinic_id: UUID, user_id: UUID | None, data: dict
    ) -> PlanTemplate:
        """Create a template. Every catalog item is checked against the clinic."""
        template = PlanTemplate(
            clinic_id=clinic_id,
            name=data["name"],
            description=data.get("description"),
            display_order=data.get("display_order", 0),
            created_by=user_id,
        )
        db.add(template)
        await db.flush()
        await PlanTemplateService._replace_items(db, clinic_id, template, data.get("items") or [])
        await db.flush()
        return template

    @staticmethod
    async def update(
        db: AsyncSession, clinic_id: UUID, template_id: UUID, data: dict
    ) -> PlanTemplate | None:
        template = await PlanTemplateService.get(db, clinic_id, template_id)
        if not template:
            return None

        for field in ("name", "description", "display_order", "is_active"):
            if field in data and data[field] is not None:
                setattr(template, field, data[field])

        # ``items`` is a full replace when present, and left alone when the key
        # is absent — the same contract the catalog's session template uses.
        if data.get("items") is not None:
            await PlanTemplateService._replace_items(db, clinic_id, template, data["items"])

        await db.flush()
        return template

    @staticmethod
    async def delete(db: AsyncSession, clinic_id: UUID, template_id: UUID) -> bool:
        """Soft delete. A template a clinic curated is hidden, never dropped."""
        template = await PlanTemplateService.get(db, clinic_id, template_id)
        if not template:
            return False
        template.is_active = False
        await db.flush()
        return True

    @staticmethod
    async def _replace_items(
        db: AsyncSession, clinic_id: UUID, template: PlanTemplate, items: list[dict]
    ) -> None:
        catalog_ids = [UUID(str(i["catalog_item_id"])) for i in items]
        if catalog_ids:
            result = await db.execute(
                select(TreatmentCatalogItem.id).where(
                    TreatmentCatalogItem.id.in_(catalog_ids),
                    TreatmentCatalogItem.clinic_id == clinic_id,
                )
            )
            known = set(result.scalars().all())
            missing = [str(cid) for cid in catalog_ids if cid not in known]
            if missing:
                raise ValueError(f"Unknown catalog items: {', '.join(missing)}")

        # Replace by statement rather than through the relationship: this runs
        # against templates that were just created and never loaded, and
        # touching ``template.items`` there triggers a lazy load the async
        # session cannot service.
        await db.execute(
            delete(PlanTemplateItem).where(PlanTemplateItem.template_id == template.id)
        )
        await db.flush()
        for index, raw in enumerate(items, start=1):
            db.add(
                PlanTemplateItem(
                    clinic_id=clinic_id,
                    template_id=template.id,
                    sequence=index,
                    catalog_item_id=UUID(str(raw["catalog_item_id"])),
                    phase=raw.get("phase"),
                    is_optional=bool(raw.get("is_optional", False)),
                    notes=raw.get("notes"),
                )
            )

    @staticmethod
    async def create_from_plan(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID | None,
        plan_id: UUID,
        name: str,
        description: str | None = None,
    ) -> PlanTemplate | None:
        """Turn an existing plan into a reusable template.

        This is the feature that makes templates stick: the shapes a clinic
        actually repeats are its own, not the ones shipped in the box. Teeth
        and prices are dropped on purpose — only the catalog item and its
        stage of care carry over. Items whose treatment has no catalog link
        (a pre-existing finding charted by hand) cannot be replayed and are
        skipped.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            return None

        seen: set[UUID] = set()
        specs: list[dict] = []
        for item in sorted(plan.items, key=lambda i: i.sequence_order):
            catalog_item_id = item.treatment.catalog_item_id if item.treatment else None
            if catalog_item_id is None or catalog_item_id in seen:
                continue
            seen.add(catalog_item_id)
            # Everything a real plan contained is recorded as required. Which
            # of those lines is actually a decision is something only the
            # author knows, so they mark them afterwards rather than the app
            # guessing from one patient.
            specs.append({"catalog_item_id": catalog_item_id, "phase": item.phase})

        return await PlanTemplateService.create(
            db,
            clinic_id,
            user_id,
            {"name": name, "description": description, "items": specs},
        )

    # ------------------------------------------------------------------
    # Applying
    # ------------------------------------------------------------------

    @staticmethod
    async def apply(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID,
        plan_id: UUID,
        template_id: UUID,
        tooth_numbers: list[int] | None = None,
        excluded_item_ids: list[UUID] | None = None,
    ) -> ApplyResult:
        """Append a template's treatments to a plan.

        Per-tooth items are created once per tooth in ``tooth_numbers``;
        multi-tooth items get all of them at once; whole-mouth items are
        created once; whole-arch items once per arch the teeth belong to, or
        both arches when no teeth were supplied (a retainer after full
        orthodontics is exactly that case).

        ``excluded_item_ids`` drops template lines the caller does not want.
        Only lines the author marked ``is_optional`` can be dropped: a
        template whose required steps can be silently skipped is not a shape
        any more, it is a suggestion.

        Returns what was created **and what was left out**. A line whose
        catalog item the clinic has retired is skipped rather than failing the
        whole application, and that has to be visible — a plan that quietly
        comes out one treatment short is worse than one that says so.

        Raises ``TemplateNeedsTeethError`` when the template cannot be applied
        as asked, so the caller can name the treatments that are waiting.
        """
        teeth = sorted(set(tooth_numbers or []))
        excluded = set(excluded_item_ids or [])

        template = await PlanTemplateService.get(db, clinic_id, template_id)
        if not template:
            raise ValueError("Template not found")

        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")

        required_excluded = [i for i in template.items if i.id in excluded and not i.is_optional]
        if required_excluded:
            raise ValueError(
                "Cannot exclude required template lines: "
                + ", ".join(_catalog_name(i.catalog_item) for i in required_excluded)
            )

        wanted = [i for i in template.items if i.id not in excluded]

        if not teeth:
            blocked = [
                _catalog_name(i.catalog_item)
                for i in wanted
                if i.catalog_item and i.catalog_item.treatment_scope in _TOOTH_SCOPES
            ]
            if blocked:
                raise TemplateNeedsTeethError(blocked)

        created: list[PlannedTreatmentItem] = []
        skipped: list[SkippedLine] = []
        for template_item in sorted(wanted, key=lambda i: i.sequence):
            catalog_item = template_item.catalog_item
            if catalog_item is None or not catalog_item.is_active:
                # A treatment this clinic does not offer (or no longer does).
                # Skipping beats failing the whole application over one line,
                # but the caller is told which one and why.
                name = _catalog_name(catalog_item) if catalog_item else "—"
                logger.warning(
                    "Template %s: skipping unavailable catalog item %s",
                    template.id,
                    name,
                )
                skipped.append(SkippedLine(name=name, reason="not_in_catalog"))
                continue

            fitting = _fitting_teeth(catalog_item, teeth, skipped)
            if fitting is None:
                continue
            for treatment in await PlanTemplateService._create_treatments(
                db, clinic_id, plan, user_id, catalog_item, fitting
            ):
                item = await TreatmentPlanService.add_item(
                    db,
                    clinic_id,
                    plan_id,
                    {"treatment_id": treatment.id, "phase": template_item.phase},
                )
                if item is not None:
                    created.append(item)

        return ApplyResult(items=created, skipped=skipped)

    @staticmethod
    async def add_catalog_items(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID,
        plan_id: UUID,
        lines: list[PlanLine],
    ) -> ApplyResult:
        """Add treatments the dentist picked one by one, tooth by tooth.

        The same catalog-item → planned-treatment path a template line takes,
        minus the shape: this is a plan drawn on a chart, where every line
        already knows which piece it is for.

        Order follows the lines as given — the order they were drawn in.
        Retired or unknown items are skipped and reported, for the same
        reason a template line is: a plan that arrives short must say so.
        """
        plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")

        wanted_ids = {line.catalog_item_id for line in lines}
        rows = (
            await db.execute(
                select(TreatmentCatalogItem).where(
                    TreatmentCatalogItem.clinic_id == clinic_id,
                    TreatmentCatalogItem.id.in_(wanted_ids),
                    TreatmentCatalogItem.is_active.is_(True),
                    TreatmentCatalogItem.deleted_at.is_(None),
                )
            )
        ).scalars()
        by_id = {item.id: item for item in rows}

        blocked = [
            _catalog_name(by_id[line.catalog_item_id])
            for line in lines
            if line.catalog_item_id in by_id
            and by_id[line.catalog_item_id].treatment_scope in _TOOTH_SCOPES
            and not line.tooth_numbers
        ]
        if blocked:
            raise TemplateNeedsTeethError(blocked)

        created: list[PlannedTreatmentItem] = []
        skipped: list[SkippedLine] = []
        for line in lines:
            catalog_item = by_id.get(line.catalog_item_id)
            if catalog_item is None:
                skipped.append(SkippedLine(name=str(line.catalog_item_id), reason="not_in_catalog"))
                continue

            teeth = _fitting_teeth(catalog_item, sorted(set(line.tooth_numbers)), skipped)
            if teeth is None:
                continue
            for treatment in await PlanTemplateService._create_treatments(
                db,
                clinic_id,
                plan,
                user_id,
                catalog_item,
                teeth,
                surfaces=line.surfaces,
                notes=line.notes,
            ):
                item = await TreatmentPlanService.add_item(
                    db,
                    clinic_id,
                    plan_id,
                    # No phase is not "no opinion": the catalog item's own
                    # `default_phase` fills in downstream.
                    {"treatment_id": treatment.id, "phase": line.phase},
                )
                if item is not None:
                    created.append(item)

        return ApplyResult(items=created, skipped=skipped)

    @staticmethod
    async def _create_treatments(
        db: AsyncSession,
        clinic_id: UUID,
        plan: TreatmentPlan,
        user_id: UUID,
        catalog_item: TreatmentCatalogItem,
        teeth: list[int],
        surfaces: list[str] | None = None,
        notes: str | None = None,
    ) -> list[Treatment]:
        """Turn one template line into the odontogram treatments it implies.

        ``surfaces`` and ``notes`` only ever arrive from a hand-drawn line: a
        template describes a shape, and neither the caries-facing surface nor
        a note about this patient belongs to a shape.
        """
        scope = catalog_item.treatment_scope
        common: dict = {
            "db": db,
            "clinic_id": clinic_id,
            "patient_id": plan.patient_id,
            "user_id": user_id,
            "catalog_item_id": catalog_item.id,
            "clinical_type": None,
            "teeth": None,
            "common_surfaces": surfaces or None,
            # Everything a template creates is planned, never performed.
            "status": "planned",
            "notes": notes,
            "budget_item_id": None,
            "source_module": "treatment_plan",
        }

        if scope == "global_mouth":
            return [
                await TreatmentService.create(
                    **common, tooth_numbers=[], scope="global_mouth", arch=None
                )
            ]

        if scope == "global_arch":
            arches = sorted({_arch_of(n) for n in teeth}) or ["upper", "lower"]
            return [
                await TreatmentService.create(
                    **common, tooth_numbers=[], scope="global_arch", arch=arch
                )
                for arch in arches
            ]

        if scope == "multi_tooth":
            return [
                await TreatmentService.create(
                    **common, tooth_numbers=teeth, scope="multi_tooth", arch=None
                )
            ]

        # `tooth`: one treatment per tooth, which is what makes a template
        # cover four quadrants of scaling or a set of sealants in one go.
        return [
            await TreatmentService.create(
                **common, tooth_numbers=[number], scope="tooth", arch=None
            )
            for number in teeth
        ]

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    @staticmethod
    async def seed(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        specialty: str | None = None,
        restore: bool = False,
    ) -> int:
        """Install the reference templates for a clinic. Idempotent on ``key``.

        A template belongs to a discipline (``specialty``), and a clinic
        gets it only while it has that discipline enabled in its catalogue.
        ``specialty`` narrows the run to one discipline — what enabling or
        restoring a specialty pack asks for.

        Deliberately tolerant: a clinic whose catalog lacks one of the codes
        gets the template without that line, and a template that would end up
        empty is not created at all. Re-running fills in whatever was missing
        the first time, so this doubles as the repair path when the catalog
        was seeded after the templates.

        A template the clinic already has is never overwritten. With
        ``restore`` one the clinic deleted (hidden) is shown again as it
        left it; missing ones are created either way.
        """
        enabled = set(
            (
                await db.execute(
                    select(Specialty.key).where(
                        Specialty.clinic_id == clinic_id,
                        Specialty.key.is_not(None),
                        Specialty.is_active.is_(True),
                    )
                )
            ).scalars()
        )
        wanted = [
            spec
            for spec in PLAN_TEMPLATES
            if spec["specialty"] in enabled and specialty in (None, spec["specialty"])
        ]

        result = await db.execute(
            select(PlanTemplate)
            .options(*_template_loader())
            .where(PlanTemplate.clinic_id == clinic_id, PlanTemplate.key.is_not(None))
        )
        existing = {t.key: t for t in result.scalars().unique().all()}

        codes = {c for spec in wanted for c in (i["code"] for i in spec["items"])}
        catalog_result = await db.execute(
            select(TreatmentCatalogItem).where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.internal_code.in_(codes),
            )
        )
        by_code = {c.internal_code: c for c in catalog_result.scalars().all()}

        touched = 0
        for spec in wanted:
            specs = [
                {"catalog_item_id": by_code[i["code"]].id, "phase": i.get("phase")}
                for i in spec["items"]
                if i["code"] in by_code
            ]
            if not specs:
                continue

            template = existing.get(spec["key"])
            if template is None:
                template = PlanTemplate(
                    clinic_id=clinic_id,
                    key=spec["key"],
                    name=spec["name"],
                    description=spec["description"],
                    display_order=spec["display_order"],
                )
                db.add(template)
                await db.flush()
            elif restore and not template.is_active:
                # Brought back as the clinic left it: a restore never
                # overwrites what the clinic made of a template.
                template.is_active = True
                touched += 1
                continue
            elif len(template.items) >= len(specs):
                # Already complete (or edited by the clinic). Never overwrite.
                continue

            await PlanTemplateService._replace_items(db, clinic_id, template, specs)
            touched += 1

        await db.flush()
        return touched

    @staticmethod
    async def set_specialty_active(
        db: AsyncSession, clinic_id: UUID, specialty: str, active: bool
    ) -> int:
        """Show or hide the reference templates of a discipline.

        Follows the discipline being enabled or disabled in the catalogue.
        Only the reference ones (those with a ``key``): a template the
        clinic saved from one of its own plans is the clinic's.
        """
        keys = [spec["key"] for spec in PLAN_TEMPLATES if spec["specialty"] == specialty]
        if not keys:
            return 0
        result = await db.execute(
            select(PlanTemplate).where(
                PlanTemplate.clinic_id == clinic_id, PlanTemplate.key.in_(keys)
            )
        )
        templates = list(result.scalars())
        for template in templates:
            template.is_active = active
        await db.flush()
        return len(templates)


def _fitting_teeth(
    catalog_item: TreatmentCatalogItem, teeth: list[int], skipped: list[SkippedLine]
) -> list[int] | None:
    """The teeth a per-tooth treatment can be done on; ``None`` when the line
    is left out altogether. Those left out are reported in ``skipped``.

    A per-tooth item goes on the teeth it fits. A multi-tooth one (a bridge,
    a splint) is one piece of work, so a single tooth of the wrong dentition
    leaves out the whole line. Whole-mouth and whole-arch items read the
    teeth only for their arch and are never left out.
    """
    if catalog_item.treatment_scope not in _TOOTH_SCOPES:
        return teeth
    wrong = [n for n in teeth if not dentition_fits(catalog_item.dentition, n)]
    if not wrong:
        return teeth
    skipped.append(
        SkippedLine(
            name=f"{_catalog_name(catalog_item)} ({', '.join(str(n) for n in wrong)})",
            reason="wrong_dentition",
        )
    )
    fitting = [n for n in teeth if n not in wrong]
    if catalog_item.treatment_scope == "multi_tooth" or not fitting:
        return None
    return fitting


def _catalog_name(catalog_item: TreatmentCatalogItem) -> str:
    names = catalog_item.names or {}
    return names.get("es") or names.get("en") or catalog_item.internal_code
