"""Specialty packs: a discipline's reference catalogue, switched per clinic.

Each of the seventeen recognised disciplines comes with a reference
catalogue — its treatments, and the plan templates the treatment-plan
module keeps for it. A clinic **enables** the ones it practises, edits
what it gets freely, **disables** the ones it does not want in its
catalogue, and can **restore** one to the reference.

- *Enable* adds what the clinic lacks and brings back what disabling
  switched off. It never touches a treatment the clinic already has: the
  reference is a starting point, the clinic's catalogue is the clinic's.
- *Disable* deactivates the treatments that belong to no other enabled
  discipline. Nothing is deleted — plans, budgets and the chart point at
  them — and a treatment the clinic created itself is left alone.
- *Restore* brings back the reference treatments the clinic lacks or
  deleted or retired — the deleted and retired ones as the clinic left
  them. It **never overwrites** a treatment the clinic has: the reference
  files stay the reference, and what the clinic made of its copy is its
  own. Plans and budgets already made are not touched either.

Plan templates are the treatment-plan module's. This module only says
what happened (``catalog.specialty_enabled`` / ``_restored``) and that
module reacts (ADR 0042: events write).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.events.types import EventType

from .models import Specialty, TreatmentCatalogItem, catalog_item_specialties
from .reference import BY_CODE, SPECIALTY_FILES, ReferenceTreatment, seed_item
from .seed import (
    _ensure_vat_types,
    all_specialties,
    ensure_categories,
    reference_items,
    upsert_reference_item,
)

#: What a clinic is most likely to have made its own on a treatment.
_COMPARED = ("names", "default_price", "default_duration_minutes", "pricing_strategy")


class UnknownSpecialtyError(ValueError):
    """Not one of the recognised disciplines."""


@dataclass(frozen=True, slots=True)
class PackStatus:
    key: str
    names: dict[str, str]
    enabled: bool
    #: Treatments in the discipline's reference catalogue.
    reference_count: int
    #: Of those, how many the clinic has, active.
    installed_count: int
    #: Of those, how many the clinic changed from the reference.
    customised_count: int
    #: Reference treatments the clinic does not have at all — added to the
    #: reference after the clinic enabled the discipline.
    missing_count: int
    #: The specialty row, when the clinic has one.
    specialty_id: UUID | None


@dataclass(frozen=True, slots=True)
class PackTreatment:
    """A reference treatment, and where the clinic stands on it."""

    code: str
    names: dict[str, str]
    reference_price: Decimal | None
    minutes: int | None
    #: ``active`` in the clinic's catalogue, ``inactive`` there, or ``missing``.
    state: str
    customised: bool
    clinic_price: Decimal | None


@dataclass(frozen=True, slots=True)
class PackGroup:
    key: str
    names: dict[str, str]
    treatments: list[PackTreatment]


@dataclass(frozen=True, slots=True)
class PackDetail:
    status: PackStatus
    #: The discipline's own treatments, by sub-area, in reading order.
    subareas: list[PackGroup]
    #: Treatments other disciplines' files hold and share with this one,
    #: grouped by the discipline that holds them.
    shared: list[PackGroup]


def _definition(key: str) -> dict[str, Any]:
    for spec in all_specialties():
        if spec["key"] == key:
            return spec
    raise UnknownSpecialtyError(key)


def _differs(item: TreatmentCatalogItem, reference: dict[str, Any]) -> bool:
    return any(getattr(item, column) != reference.get(column) for column in _COMPARED)


class SpecialtyPackService:
    @staticmethod
    async def _specialties(db: AsyncSession, clinic_id: UUID) -> dict[str, Specialty]:
        rows = (
            await db.execute(
                select(Specialty).where(
                    Specialty.clinic_id == clinic_id, Specialty.key.is_not(None)
                )
            )
        ).scalars()
        return {row.key: row for row in rows}

    @staticmethod
    async def _items(
        db: AsyncSession, clinic_id: UUID, codes: list[str]
    ) -> dict[str, TreatmentCatalogItem]:
        if not codes:
            return {}
        rows = (
            await db.execute(
                select(TreatmentCatalogItem).where(
                    TreatmentCatalogItem.clinic_id == clinic_id,
                    TreatmentCatalogItem.internal_code.in_(codes),
                )
            )
        ).scalars()
        return {row.internal_code: row for row in rows}

    @classmethod
    async def status(cls, db: AsyncSession, clinic_id: UUID, key: str) -> PackStatus:
        definition = _definition(key)
        specialty = (await cls._specialties(db, clinic_id)).get(key)
        reference = [item for _, item in reference_items(key)]
        owned = await cls._items(db, clinic_id, [item["internal_code"] for item in reference])
        installed = customised = missing = 0
        for item in reference:
            row = owned.get(item["internal_code"])
            if row is None:
                missing += 1
                continue
            if not row.is_active or row.deleted_at is not None:
                continue
            installed += 1
            customised += _differs(row, item)
        return PackStatus(
            key=key,
            names=specialty.names if specialty else definition["names"],
            enabled=bool(specialty and specialty.is_active),
            reference_count=len(reference),
            installed_count=installed,
            customised_count=customised,
            missing_count=missing,
            specialty_id=specialty.id if specialty else None,
        )

    @classmethod
    async def detail(cls, db: AsyncSession, clinic_id: UUID, key: str) -> PackDetail:
        """The discipline's reference treatments, grouped by sub-area.

        Sub-areas are the reference's, resolved by code (ADR 0048): every
        clinic gets them, and a treatment the clinic created has none —
        it is not part of any reference.
        """
        status = await cls.status(db, clinic_id, key)
        claimed = [
            (owner, treatment)
            for owner, treatment in BY_CODE.values()
            if key in treatment.specialties
        ]
        owned = await cls._items(db, clinic_id, [treatment.code for _, treatment in claimed])

        def stand(treatment: ReferenceTreatment) -> PackTreatment:
            row = owned.get(treatment.code)
            if row is None:
                state = "missing"
            elif row.is_active and row.deleted_at is None:
                state = "active"
            else:
                state = "inactive"
            return PackTreatment(
                code=treatment.code,
                names=row.names if row is not None else treatment.names.model_dump(),
                reference_price=treatment.price,
                minutes=treatment.minutes,
                state=state,
                customised=state == "active" and _differs(row, seed_item(treatment)),
                clinic_price=row.default_price if row is not None else None,
            )

        own_file = SPECIALTY_FILES[key]
        subareas = [
            PackGroup(
                key=subarea.key,
                names=subarea.names.model_dump(),
                treatments=[
                    stand(treatment)
                    for owner, treatment in claimed
                    if owner == key and treatment.subarea == subarea.key
                ],
            )
            for subarea in own_file.subareas
        ]
        shared = [
            PackGroup(
                key=other,
                names=SPECIALTY_FILES[other].names.model_dump(),
                treatments=[stand(t) for owner, t in claimed if owner == other],
            )
            for other in SPECIALTY_FILES
            if other != key and any(owner == other for owner, _ in claimed)
        ]
        return PackDetail(
            status=status,
            subareas=[group for group in subareas if group.treatments],
            shared=shared,
        )

    @classmethod
    async def list(cls, db: AsyncSession, clinic_id: UUID) -> list[PackStatus]:
        return [await cls.status(db, clinic_id, spec["key"]) for spec in all_specialties()]

    @classmethod
    async def _apply(
        cls, db: AsyncSession, clinic_id: UUID, key: str, *, restore: bool
    ) -> dict[str, int]:
        """Bring the discipline's reference items into the clinic's catalogue."""
        specialty_map = {k: row.id for k, row in (await cls._specialties(db, clinic_id)).items()}
        vat_type_map = await _ensure_vat_types(db, clinic_id)
        category_map, _ = await ensure_categories(db, clinic_id)
        counts = {"created": 0, "restored": 0, "existing": 0, "phase": 0}
        for category_key, item in reference_items(key):
            outcome, _ = await upsert_reference_item(
                db,
                clinic_id,
                category_key,
                category_map[category_key],
                item,
                vat_type_map,
                specialty_map,
                restore=restore,
            )
            counts[outcome] += 1
        return counts

    @classmethod
    async def enable(cls, db: AsyncSession, clinic_id: UUID, key: str) -> PackStatus:
        definition = _definition(key)
        specialty = (await cls._specialties(db, clinic_id)).get(key)
        if specialty is None:
            specialty = Specialty(clinic_id=clinic_id, key=key, names=definition["names"])
            db.add(specialty)
        specialty.is_active = True
        await db.flush()

        await cls._apply(db, clinic_id, key, restore=False)
        # What disabling switched off comes back; what the clinic retired
        # by hand stays retired.
        await db.execute(
            update(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.disabled_by_specialty.is_(True),
                TreatmentCatalogItem.id.in_(
                    select(catalog_item_specialties.c.catalog_item_id).where(
                        catalog_item_specialties.c.specialty_id == specialty.id
                    )
                ),
            )
            .values(is_active=True, disabled_by_specialty=False)
        )
        await db.flush()
        event_bus.publish_after_commit(
            db,
            EventType.CATALOG_SPECIALTY_ENABLED,
            {"clinic_id": str(clinic_id), "specialty_key": key},
        )
        return await cls.status(db, clinic_id, key)

    @classmethod
    async def disable(cls, db: AsyncSession, clinic_id: UUID, key: str) -> PackStatus:
        _definition(key)
        specialty = (await cls._specialties(db, clinic_id)).get(key)
        if specialty is None or not specialty.is_active:
            return await cls.status(db, clinic_id, key)
        specialty.is_active = False
        await db.flush()

        # Treatments of this discipline that no enabled discipline still claims.
        still_claimed = (
            select(catalog_item_specialties.c.catalog_item_id)
            .join(Specialty, Specialty.id == catalog_item_specialties.c.specialty_id)
            .where(Specialty.clinic_id == clinic_id, Specialty.is_active.is_(True))
        )
        await db.execute(
            update(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.is_active.is_(True),
                # The reference ones only: a treatment the clinic created
                # is the clinic's to retire.
                TreatmentCatalogItem.is_system.is_(True),
                TreatmentCatalogItem.id.in_(
                    select(catalog_item_specialties.c.catalog_item_id).where(
                        catalog_item_specialties.c.specialty_id == specialty.id
                    )
                ),
                TreatmentCatalogItem.id.not_in(still_claimed),
            )
            .values(is_active=False, disabled_by_specialty=True)
        )
        await db.flush()
        event_bus.publish_after_commit(
            db,
            EventType.CATALOG_SPECIALTY_DISABLED,
            {"clinic_id": str(clinic_id), "specialty_key": key},
        )
        return await cls.status(db, clinic_id, key)

    @classmethod
    async def restore(cls, db: AsyncSession, clinic_id: UUID, key: str) -> PackStatus:
        """Put the discipline's reference treatments back to the reference.

        Only for an enabled discipline: restoring one the clinic switched
        off would bring its treatments back through the side door.
        """
        _definition(key)
        specialty = (await cls._specialties(db, clinic_id)).get(key)
        if specialty is None or not specialty.is_active:
            raise ValueError("Enable the specialty before restoring it")
        await cls._apply(db, clinic_id, key, restore=True)
        await db.flush()
        event_bus.publish_after_commit(
            db,
            EventType.CATALOG_SPECIALTY_RESTORED,
            {"clinic_id": str(clinic_id), "specialty_key": key},
        )
        return await cls.status(db, clinic_id, key)

    @staticmethod
    async def active_item_count(db: AsyncSession, clinic_id: UUID) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.is_active.is_(True),
            )
        )
        return int(result.scalar_one())
