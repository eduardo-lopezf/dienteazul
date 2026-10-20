"""Seed data for the catalog module.

Creates VAT types, categories and a broad catalog of billable treatments. Includes
pricing strategies (flat / per_tooth / per_surface / per_role) so that multi-tooth
treatments can scale price with the tooth count automatically.

Visualization rules use the new layered JSONB format:

    visualization_rules = [
        {"layer": "cenital_pattern", "pattern": "diagonal_stripes", "color": "#F59E0B"},
        {"layer": "lateral_icon",    "icon": "implant",            "color": "#10B981"}
    ]

Diagnostic findings (caries, fracture, etc.) are NOT billable and therefore are
not seeded here. Their visualization is driven by the odontogram module's
default rules for clinical_type.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    CatalogItemSession,
    Specialty,
    TreatmentCatalogItem,
    TreatmentCategory,
    TreatmentOdontogramMapping,
    VatType,
    catalog_item_specialties,
)
from .reference import (
    BY_CODE,
    CATEGORY_KEYS,
    SPECIALTY_FILES,
    seed_item,
    treatments_by_category,
)

# ============================================================================
# VAT types
# ============================================================================

VAT_TYPES: list[dict[str, Any]] = [
    {
        "key": "exempt",
        "names": {"es": "Exento", "en": "Exempt"},
        "rate": 0.0,
        "is_default": True,
    },
    {
        "key": "standard",
        "names": {"es": "General (16%)", "en": "Standard (16%)"},
        "rate": 16.0,
        "is_default": False,
    },
]


# ============================================================================
# The reference catalogue
# ============================================================================
#
# The treatments, the disciplines they belong to, their stage of care and
# their sub-areas are data: one file per discipline under ``reference/``,
# read and validated by ``reference.py`` (ADR 0048). Nothing about a
# treatment is derived here from the shape of its code any more.
#
# Two axes, both written on each treatment. A *category* answers "where do
# I find this treatment" and a *specialty* answers "who performs it";
# neither is a subset of the other — `cirugia` holds two specialties, while
# Implantología spans three categories.


def _specialty(key: str) -> dict[str, Any]:
    return {"key": key, "names": SPECIALTY_FILES[key].names.model_dump()}


#: The disciplines every new clinic starts with.
SPECIALTIES: list[dict[str, Any]] = [
    _specialty(key) for key, file in SPECIALTY_FILES.items() if file.baseline
]

#: Disciplines a clinic adds when it practises them. Real enough to deserve
#: a stable key and a catalogue, rare enough that seeding them into every
#: clinic would clutter every picker.
#:
#: The keys matter: a clinic-created specialty normally carries
#: `key = NULL`, so two people typing "Radiología" produce two rows that
#: split the treatments between them. Enabling one of these carries the key
#: instead, which the unique index enforces.
SUGGESTED_SPECIALTIES: list[dict[str, Any]] = [
    _specialty(key) for key, file in SPECIALTY_FILES.items() if not file.baseline
]


def all_specialties() -> list[dict[str, Any]]:
    """Every recognised discipline. Each is a *pack* — a reference
    catalogue the clinic enables, disables and restores (``packs.py``)."""
    return [*SPECIALTIES, *SUGGESTED_SPECIALTIES]


def specialty_keys_for(category_key: str, internal_code: str) -> list[str]:
    """Disciplines a reference treatment belongs to, as its file says."""
    found = BY_CODE.get(internal_code)
    return list(found[1].specialties) if found else []


def phase_for(category_key: str, internal_code: str) -> str | None:
    """Stage of care of a reference treatment, as its file says."""
    found = BY_CODE.get(internal_code)
    return found[1].phase if found else None


# ============================================================================
# Categories
# ============================================================================

CATEGORIES: list[dict[str, Any]] = [
    {
        "key": "diagnostico",
        "names": {"es": "Diagnóstico", "en": "Diagnostic"},
        "descriptions": {
            "es": "Servicios de diagnóstico y evaluación",
            "en": "Diagnostic and evaluation services",
        },
        "display_order": 1,
        "icon": "i-lucide-stethoscope",
    },
    {
        "key": "preventivo",
        "names": {"es": "Preventivo", "en": "Preventive"},
        "descriptions": {
            "es": "Prevención e higiene dental",
            "en": "Preventive and hygiene",
        },
        "display_order": 2,
        "icon": "i-lucide-shield-check",
    },
    {
        "key": "restauradora",
        "names": {"es": "Restauradora", "en": "Restorative"},
        "descriptions": {
            "es": "Restauración dental",
            "en": "Dental restoration",
        },
        "display_order": 3,
        "icon": "i-lucide-brush",
    },
    {
        "key": "endodoncia",
        "names": {"es": "Endodoncia", "en": "Endodontics"},
        "descriptions": {
            "es": "Tratamientos de conducto radicular",
            "en": "Root canal treatments",
        },
        "display_order": 4,
        "icon": "i-lucide-activity",
    },
    {
        "key": "periodoncia",
        "names": {"es": "Periodoncia", "en": "Periodontics"},
        "descriptions": {
            "es": "Encías y tejidos de soporte",
            "en": "Gums and supporting tissues",
        },
        "display_order": 5,
        "icon": "i-lucide-heart-pulse",
    },
    {
        "key": "cirugia",
        "names": {"es": "Cirugía", "en": "Surgery"},
        "descriptions": {
            "es": "Procedimientos quirúrgicos dentales",
            "en": "Dental surgical procedures",
        },
        "display_order": 6,
        "icon": "i-lucide-scissors",
    },
    {
        "key": "ortodoncia",
        "names": {"es": "Ortodoncia", "en": "Orthodontics"},
        "descriptions": {
            "es": "Ortodoncia y alineación",
            "en": "Orthodontics and alignment",
        },
        "display_order": 7,
        "icon": "i-lucide-align-center",
    },
    {
        "key": "estetica",
        "names": {"es": "Estética", "en": "Cosmetic"},
        "descriptions": {
            "es": "Estética dental",
            "en": "Cosmetic dentistry",
        },
        "display_order": 8,
        "icon": "i-lucide-sparkles",
    },
    {
        "key": "protesis",
        "names": {"es": "Prótesis", "en": "Prosthetics"},
        "descriptions": {
            "es": "Prótesis y férulas",
            "en": "Prosthetics and splints",
        },
        "display_order": 9,
        "icon": "i-lucide-puzzle",
    },
    {
        "key": "pediatrica",
        "names": {"es": "Odontopediatría", "en": "Pediatric"},
        "descriptions": {
            "es": "Tratamientos para niños",
            "en": "Treatments for children",
        },
        "display_order": 10,
        "icon": "i-lucide-baby",
    },
]


# ============================================================================
# Visualization presets
# ============================================================================
# Treatments
# ============================================================================

#: Browsing category -> reference treatments, in the shape the catalogue's
#: columns take. Built from ``reference/*.json``.
TREATMENTS: dict[str, list[dict[str, Any]]] = treatments_by_category()

if {category["key"] for category in CATEGORIES} != set(CATEGORY_KEYS):
    raise RuntimeError("seed.CATEGORIES and reference.CATEGORY_KEYS disagree")


def reference_items(specialty_key: str) -> list[tuple[str, dict[str, Any]]]:
    """The reference catalogue of a discipline: ``(category_key, item)``.

    Its own file's treatments first, in file order, then the ones other
    disciplines' files share with it.
    """
    own, shared = [], []
    for owner, treatment in BY_CODE.values():
        if specialty_key not in treatment.specialties:
            continue
        (own if owner == specialty_key else shared).append(
            (treatment.category, seed_item(treatment))
        )
    return own + shared


# ============================================================================
# Seeding logic
# ============================================================================


async def _ensure_vat_types(db: AsyncSession, clinic_id: UUID) -> dict[str, UUID]:
    vat_type_map: dict[str, UUID] = {}
    for vat_data in VAT_TYPES:
        existing = await db.execute(
            select(VatType).where(
                VatType.clinic_id == clinic_id,
                VatType.rate == vat_data["rate"],
            )
        )
        vat = existing.scalar_one_or_none()
        if not vat:
            vat = VatType(
                clinic_id=clinic_id,
                names=vat_data["names"],
                rate=vat_data["rate"],
                is_default=vat_data["is_default"],
                is_system=True,
            )
            db.add(vat)
            await db.flush()
        vat_type_map[vat_data["key"]] = vat.id
    return vat_type_map


async def _ensure_specialties(db: AsyncSession, clinic_id: UUID) -> dict[str, UUID]:
    """Create the clinic's baseline specialties. Matched by ``key``, so a
    renamed specialty is updated in place rather than duplicated."""
    specialty_map: dict[str, UUID] = {}
    for data in SPECIALTIES:
        existing = await db.execute(
            select(Specialty).where(
                Specialty.clinic_id == clinic_id,
                Specialty.key == data["key"],
            )
        )
        specialty = existing.scalar_one_or_none()
        if not specialty:
            specialty = Specialty(clinic_id=clinic_id, key=data["key"], names=data["names"])
            db.add(specialty)
            await db.flush()
        specialty_map[data["key"]] = specialty.id
    return specialty_map


async def _link_item_specialties(
    db: AsyncSession,
    item: TreatmentCatalogItem,
    category_key: str,
    specialty_map: dict[str, UUID],
) -> int:
    """Attach the baseline disciplines to a treatment.

    Additive on purpose: a clinic that curated its own assignments keeps
    them, and re-seeding only fills in what is missing.
    """
    wanted = [
        specialty_map[key]
        for key in specialty_keys_for(category_key, item.internal_code)
        if key in specialty_map
    ]
    if not wanted:
        return 0

    existing = set(
        (
            await db.execute(
                select(catalog_item_specialties.c.specialty_id).where(
                    catalog_item_specialties.c.catalog_item_id == item.id
                )
            )
        )
        .scalars()
        .all()
    )
    missing = [sid for sid in wanted if sid not in existing]
    if missing:
        await db.execute(
            catalog_item_specialties.insert(),
            [{"catalog_item_id": item.id, "specialty_id": sid} for sid in missing],
        )
    return len(missing)


def _reference_fields(treatment_raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a reference item into its columns and what hangs from it."""
    data = dict(treatment_raw)
    extras = {
        "odontogram_type": data.pop("odontogram_treatment_type", None),
        # Both columns are JSONB containers, so an absent key means "empty",
        # never None — an item that draws nothing still has a list of no
        # rules, and the mapping is written with that list.
        "viz_rules": data.pop("visualization_rules", None) or [],
        "viz_config": data.pop("visualization_config", None) or {},
        "vat_type": data.pop("vat_type", "exempt"),
        "sessions": data.pop("sessions", None),
    }
    data.pop("specialties", None)
    return data, extras


async def _write_dependents(
    db: AsyncSession,
    clinic_id: UUID,
    item: TreatmentCatalogItem,
    category_key: str,
    extras: dict[str, Any],
) -> None:
    """The odontogram mapping and the per-session template of an item."""
    # A declared type with no drawing rules is a legitimate pair, not an
    # incomplete one: skeletal and process types (an osteotomy, a
    # consultation, a radiograph) act on the face or on the visit and
    # deliberately draw nothing on a tooth chart — see
    # `odontogram/constants.py`. Requiring rules here left those items
    # with no mapping at all, so `_resolve_clinical_type` fell back to
    # `procedure` and a Le Fort I was filed as a generic act.
    if extras["odontogram_type"]:
        db.add(
            TreatmentOdontogramMapping(
                clinic_id=clinic_id,
                catalog_item_id=item.id,
                odontogram_treatment_type=extras["odontogram_type"],
                visualization_rules=extras["viz_rules"],
                visualization_config=extras["viz_config"],
                clinical_category=category_key,
            )
        )
    # Per-session template (multi-session billing). Treatment plans
    # snapshot this when the item is added — see ``treatment_plan``.
    for idx, session_data in enumerate(extras["sessions"] or [], start=1):
        db.add(
            CatalogItemSession(
                catalog_item_id=item.id,
                sequence=session_data.get("sequence") or idx,
                labels=session_data.get("labels") or {},
                default_price=session_data["default_price"],
            )
        )


async def upsert_reference_item(
    db: AsyncSession,
    clinic_id: UUID,
    category_key: str,
    category_id: UUID,
    treatment_raw: dict[str, Any],
    vat_type_map: dict[str, UUID],
    specialty_map: dict[str, UUID],
    *,
    restore: bool = False,
) -> tuple[str, int]:
    """Bring one reference item into a clinic's catalogue.

    Returns ``(outcome, specialty links added)``. An item the clinic
    already has is **never overwritten**: the reference files are the
    reference, and the clinic's copy is the clinic's — what it changed is
    its own. Without ``restore`` only its missing discipline links and
    phase are filled in. With ``restore`` an item the clinic deleted or
    retired comes back as it left it (outcome ``restored``); one it still
    has is left alone (``existing``).
    """
    data, extras = _reference_fields(treatment_raw)
    vat_type_id = vat_type_map.get(extras["vat_type"], vat_type_map.get("exempt"))
    phase = phase_for(category_key, data["internal_code"])

    existing = await db.execute(
        select(TreatmentCatalogItem).where(
            TreatmentCatalogItem.clinic_id == clinic_id,
            TreatmentCatalogItem.internal_code == data["internal_code"],
        )
    )
    already = existing.scalar_one_or_none()
    if already is not None:
        # The item predates the specialty and phase axes, so those may
        # still be missing even though the item itself is not.
        linked = await _link_item_specialties(db, already, category_key, specialty_map)
        if restore and (already.deleted_at is not None or not already.is_active):
            already.deleted_at = None
            already.is_active = True
            already.disabled_by_specialty = False
            return "restored", linked
        if already.default_phase is None:
            already.default_phase = phase
            return "phase", linked
        return "existing", linked

    item = TreatmentCatalogItem(
        clinic_id=clinic_id,
        category_id=category_id,
        vat_type_id=vat_type_id,
        is_system=True,
        default_phase=phase,
        **data,
    )
    db.add(item)
    await db.flush()
    await _write_dependents(db, clinic_id, item, category_key, extras)
    linked = await _link_item_specialties(db, item, category_key, specialty_map)
    return "created", linked


async def ensure_categories(db: AsyncSession, clinic_id: UUID) -> tuple[dict[str, UUID], int]:
    """The browsing categories of a clinic, created where missing."""
    created = 0
    category_map: dict[str, UUID] = {}
    for cat_data in CATEGORIES:
        existing = await db.execute(
            select(TreatmentCategory).where(
                TreatmentCategory.clinic_id == clinic_id,
                TreatmentCategory.key == cat_data["key"],
            )
        )
        category = existing.scalar_one_or_none()
        if not category:
            category = TreatmentCategory(clinic_id=clinic_id, is_system=True, **cat_data)
            db.add(category)
            await db.flush()
            created += 1
        category_map[cat_data["key"]] = category.id
    return category_map, created


async def seed_catalog(db: AsyncSession, clinic_id: UUID) -> dict:
    """Seed catalog items for a clinic. Idempotent (skips existing internal_codes)."""
    vat_type_map = await _ensure_vat_types(db, clinic_id)
    specialty_map = await _ensure_specialties(db, clinic_id)

    items_created = 0
    specialty_links = 0
    phases_set = 0
    category_map, categories_created = await ensure_categories(db, clinic_id)

    # Every keyed discipline the clinic has, not only the baseline: a pack
    # enabled later is topped up by a re-seed like the rest.
    rows = (
        await db.execute(
            select(Specialty).where(Specialty.clinic_id == clinic_id, Specialty.key.is_not(None))
        )
    ).scalars()
    active_keys: set[str] = set()
    for row in rows:
        specialty_map[row.key] = row.id
        if row.is_active:
            active_keys.add(row.key)

    for category_key, treatments in TREATMENTS.items():
        category_id = category_map.get(category_key)
        if not category_id:
            continue

        for treatment_raw in treatments:
            # A pack the clinic has not enabled contributes nothing: its
            # treatments arrive when the discipline is switched on.
            keys = specialty_keys_for(category_key, treatment_raw["internal_code"])
            if keys and not (set(keys) & active_keys):
                continue
            outcome, linked = await upsert_reference_item(
                db, clinic_id, category_key, category_id, treatment_raw, vat_type_map, specialty_map
            )
            specialty_links += linked
            if outcome == "created":
                items_created += 1
            elif outcome == "phase":
                phases_set += 1

    await db.flush()

    return {
        "categories": categories_created,
        "items": items_created,
        "vat_types": len(vat_type_map),
        "specialties": len(specialty_map),
        "specialty_links": specialty_links,
        "phases_backfilled": phases_set,
    }


async def seed_all_clinics(db: AsyncSession) -> dict:
    """Seed catalog for every clinic in the database."""
    from app.core.auth.models import Clinic

    result = await db.execute(select(Clinic))
    clinics = result.scalars().all()

    summary = {}
    for clinic in clinics:
        summary[str(clinic.id)] = await seed_catalog(db, clinic.id)
    return summary
