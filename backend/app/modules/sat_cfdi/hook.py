"""The SAT's side of billing's compliance contract (ADR 0067).

Registered for Mexico (``MX``). It never calls the PAC: it validates what
must be refused at once and writes the CFDI a scheduled job will stamp
after commit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.hooks import BillingComplianceHook
from app.modules.billing.models import Invoice

from .issuer import SatIssuerService
from .models import CANCEL_REASONS, PUBLIC_RFC, RFC, SatCfdi
from .receivers import SatReceiverService
from .service import SatCfdiService, compliance_block


def _compliance(cfdi: SatCfdi) -> dict[str, Any]:
    return {"MX": compliance_block(cfdi)}


class SatCfdiHook(BillingComplianceHook):
    @property
    def country_code(self) -> str:
        return "MX"

    @property
    def name(self) -> str:
        return "SAT (CFDI 4.0)"

    @property
    def module_name(self) -> str:
        return "sat_cfdi"

    @property
    def cancellation_needs_confirmation(self) -> bool:
        # The SAT may wait for the receiver to accept it.
        return True

    async def validate_before_issue(
        self, invoice: Invoice, db: AsyncSession
    ) -> tuple[bool, str | None]:
        missing = await SatIssuerService.not_ready(db, invoice.clinic_id)
        if missing:
            return False, missing
        rfc = (invoice.billing_tax_id or "").strip().upper()
        if not RFC.match(rfc):
            return False, (
                "El RFC del receptor no es válido. Usa el de su constancia de situación "
                "fiscal, o XAXX010101000 para público en general."
            )
        if rfc != PUBLIC_RFC and await SatReceiverService.get(db, invoice.clinic_id, rfc) is None:
            return False, (
                f"Para facturar a {rfc} ante el SAT faltan su régimen fiscal, su código "
                "postal fiscal y el uso del CFDI."
            )
        return True, None

    async def on_invoice_issued(self, invoice: Invoice, db: AsyncSession) -> dict[str, Any]:
        cfdi = await SatCfdiService.queue(db, invoice.clinic_id, invoice.id, "I")
        return _compliance(cfdi)

    async def on_credit_note_issued(
        self, credit_note: Invoice, original_invoice: Invoice, db: AsyncSession
    ) -> dict[str, Any]:
        ingreso = await SatCfdiService.document_cfdi(
            db, original_invoice.clinic_id, original_invoice.id
        )
        cfdi = await SatCfdiService.queue(
            db,
            credit_note.clinic_id,
            credit_note.id,
            "E",
            related_cfdi_id=ingreso.id if ingreso else None,
        )
        return _compliance(cfdi)

    async def before_cancel(
        self,
        invoice: Invoice,
        reason: str,
        substitute: Invoice | None,
        db: AsyncSession,
    ) -> tuple[bool, str | None]:
        if reason not in CANCEL_REASONS:
            return False, "El motivo de cancelación del SAT debe ser 01, 02, 03 o 04."
        cfdi = await SatCfdiService.document_cfdi(db, invoice.clinic_id, invoice.id)
        if cfdi is None or cfdi.state != "stamped":
            return False, (
                "El CFDI de esta factura todavía no está timbrado; el SAT no tiene nada que cancelar."
            )
        if reason == "01":
            if substitute is None:
                return False, "El motivo 01 necesita la factura que sustituye a esta."
            replacement = await SatCfdiService.document_cfdi(db, invoice.clinic_id, substitute.id)
            if replacement is None or replacement.state != "stamped":
                return False, "La factura sustituta tiene que estar timbrada antes de cancelar."
        return True, None

    async def on_invoice_cancelled(
        self,
        invoice: Invoice,
        reason: str,
        substitute: Invoice | None,
        cancelled_by: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        cfdi = await SatCfdiService.document_cfdi(db, invoice.clinic_id, invoice.id)
        if cfdi is None:  # before_cancel refuses this; nothing to record
            return {}
        replacement = None
        if reason == "01" and substitute is not None:
            replacement = await SatCfdiService.document_cfdi(db, invoice.clinic_id, substitute.id)
        cfdi.state = "cancel_requested"
        cfdi.cancel_reason = reason
        cfdi.substitute_cfdi_id = replacement.id if replacement else None
        cfdi.cancel_requested_by = cancelled_by
        await db.flush()
        return _compliance(cfdi)
