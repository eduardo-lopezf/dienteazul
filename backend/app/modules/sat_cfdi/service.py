"""What the SAT module keeps about each CFDI. Every query filters by clinic."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SatCfdi

#: Billing's ``severity`` vocabulary: ``ok | warning | pending | error``.
SEVERITY = {
    "pending": "pending",
    "stamped": "ok",
    "rejected": "error",
    "cancel_requested": "pending",
    "cancelled": "ok",
}


def compliance_block(cfdi: SatCfdi) -> dict:
    """What billing keeps of a CFDI in ``Invoice.compliance_data["MX"]``."""
    block = {"cfdi_id": str(cfdi.id), "state": cfdi.state, "severity": SEVERITY[cfdi.state]}
    if cfdi.uuid:
        block["uuid"] = cfdi.uuid
    return block


class SatCfdiService:
    @staticmethod
    async def queue(
        db: AsyncSession,
        clinic_id: UUID,
        invoice_id: UUID,
        kind: str,
        related_cfdi_id: UUID | None = None,
    ) -> SatCfdi:
        """A ``pending`` CFDI for the stamping job (ADR 0067)."""
        cfdi = SatCfdi(
            clinic_id=clinic_id,
            invoice_id=invoice_id,
            kind=kind,
            state="pending",
            related_cfdi_id=related_cfdi_id,
            attempts=0,
        )
        db.add(cfdi)
        await db.flush()
        return cfdi

    @staticmethod
    async def document_cfdi(db: AsyncSession, clinic_id: UUID, invoice_id: UUID) -> SatCfdi | None:
        """The CFDI that stands for the document itself — its ingreso or
        egreso, not its payment complements. The newest, if it was ever
        queued again."""
        result = await db.execute(
            select(SatCfdi)
            .where(
                SatCfdi.clinic_id == clinic_id,
                SatCfdi.invoice_id == invoice_id,
                SatCfdi.kind.in_(("I", "E")),
            )
            .order_by(SatCfdi.created_at.desc(), SatCfdi.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_invoice(
        db: AsyncSession, clinic_id: UUID, invoice_id: UUID
    ) -> list[SatCfdi]:
        result = await db.execute(
            select(SatCfdi)
            .where(SatCfdi.clinic_id == clinic_id, SatCfdi.invoice_id == invoice_id)
            .order_by(SatCfdi.created_at, SatCfdi.id)
        )
        return list(result.scalars().all())
