"""What commissions offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import CommissionTerms

from .service import CommissionService, switched_on


class CommissionRatesProvider:
    async def in_use(self, db: AsyncSession, clinic_id: UUID) -> bool:
        return await switched_on(db, clinic_id)

    async def terms(
        self, db: AsyncSession, clinic_id: UUID, professional_id: UUID
    ) -> CommissionTerms | None:
        return await CommissionService.terms(db, clinic_id, professional_id)


commission_rates = CommissionRatesProvider()
