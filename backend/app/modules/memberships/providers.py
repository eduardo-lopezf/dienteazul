"""What memberships offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import MemberDiscount

from .service import BenefitService


class MemberBenefitsProvider:
    async def discount_for(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        catalog_item_id: UUID,
        on: date,
    ) -> MemberDiscount | None:
        return await BenefitService.discount_for(db, clinic_id, patient_id, catalog_item_id, on)

    async def apply(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        catalog_item_id: UUID,
        treatment_id: UUID,
        on: date,
    ) -> MemberDiscount | None:
        return await BenefitService.apply(
            db, clinic_id, patient_id, catalog_item_id, treatment_id, on
        )

    async def release(self, db: AsyncSession, clinic_id: UUID, treatment_id: UUID) -> None:
        await BenefitService.release(db, clinic_id, treatment_id)


member_benefits = MemberBenefitsProvider()
