"""Receivers' fiscal profiles, kept by RFC. Every query filters by clinic."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SatReceiver


class SatReceiverService:
    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, rfc: str) -> SatReceiver | None:
        result = await db.execute(
            select(SatReceiver).where(
                SatReceiver.clinic_id == clinic_id, SatReceiver.rfc == rfc.strip().upper()
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def save(
        db: AsyncSession,
        clinic_id: UUID,
        rfc: str,
        *,
        tax_regime: str,
        tax_zip_code: str,
        cfdi_use: str,
    ) -> SatReceiver:
        rfc = rfc.strip().upper()
        receiver = await SatReceiverService.get(db, clinic_id, rfc)
        if receiver is None:
            receiver = SatReceiver(clinic_id=clinic_id, rfc=rfc)
            db.add(receiver)
        receiver.tax_regime = tax_regime
        receiver.tax_zip_code = tax_zip_code
        receiver.cfdi_use = cfdi_use
        await db.flush()
        return receiver
