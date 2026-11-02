"""What the catalog offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import CatalogItemBrief, ReferenceSpecialty

from .models import Specialty, TreatmentCatalogItem
from .seed import all_specialties

#: The discipline no clinic is created without: general dentistry is what
#: the Treatments App is, before any speciality is added to it.
REQUIRED_SPECIALTIES = frozenset({"general"})


class CatalogReferenceSpecialties:
    def available(self) -> list[ReferenceSpecialty]:
        return [
            ReferenceSpecialty(
                key=specialty["key"],
                names=specialty["names"],
                required=specialty["key"] in REQUIRED_SPECIALTIES,
            )
            for specialty in all_specialties()
        ]

    async def enabled(self, db: AsyncSession, clinic_id: UUID) -> list[str]:
        rows = await db.scalars(
            select(Specialty.key).where(
                Specialty.clinic_id == clinic_id,
                Specialty.key.is_not(None),
                Specialty.is_active.is_(True),
            )
        )
        active = set(rows)
        return [specialty["key"] for specialty in all_specialties() if specialty["key"] in active]


class CatalogTreatments:
    """The clinic's own copy of the catalogue, as plain data.

    Rows never cross the boundary: a consumer gets ids, codes and names,
    which is all anything outside the catalog has ever needed to point
    at a treatment.
    """

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, item_ids: Collection[UUID]
    ) -> dict[UUID, CatalogItemBrief]:
        if not item_ids:
            return {}
        rows = await db.execute(
            select(
                TreatmentCatalogItem.id,
                TreatmentCatalogItem.internal_code,
                TreatmentCatalogItem.names,
            ).where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.id.in_(set(item_ids)),
            )
        )
        return {
            row.id: CatalogItemBrief(
                id=row.id, internal_code=row.internal_code, names=dict(row.names or {})
            )
            for row in rows.all()
        }

    async def list_active(self, db: AsyncSession, clinic_id: UUID) -> list[CatalogItemBrief]:
        rows = await db.execute(
            select(
                TreatmentCatalogItem.id,
                TreatmentCatalogItem.internal_code,
                TreatmentCatalogItem.names,
            )
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.is_active.is_(True),
            )
            .order_by(TreatmentCatalogItem.internal_code)
        )
        return [
            CatalogItemBrief(
                id=row.id, internal_code=row.internal_code, names=dict(row.names or {})
            )
            for row in rows.all()
        ]


specialties = CatalogReferenceSpecialties()
treatments = CatalogTreatments()
