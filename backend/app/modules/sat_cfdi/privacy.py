"""What this module answers when a patient exercises their rights.

The CFDIs of the patient's invoices. They do not link to the patient:
they link to the invoice, and it is ``billing`` — in ``manifest.depends``
— that knows whose each one is. They are not deleted: a CFDI stamped by
the SAT is a fiscal record the clinic must keep.

See ``app.core.privacy.subject`` and ADR 0026.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import SubjectContributor, row_to_dict
from app.modules.billing.models import Invoice

from .models import SatCfdi, SatReceiver

SAT_RETENTION = (
    "Los CFDI timbrados por el SAT son comprobantes fiscales: el Código Fiscal "
    "de la Federación (art. 30) obliga a conservarlos cinco años. No se "
    "suprimen ni se anonimizan."
)


async def _export_cfdis(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[dict[str, Any]]:
    invoices = select(Invoice.id).where(
        Invoice.clinic_id == clinic_id, Invoice.patient_id == patient_id
    )
    result = await db.execute(
        select(SatCfdi)
        .where(SatCfdi.clinic_id == clinic_id, SatCfdi.invoice_id.in_(invoices))
        .order_by(SatCfdi.created_at, SatCfdi.id)
    )
    return [row_to_dict(row) for row in result.scalars().all()]


RECEIVER_RETENTION = (
    "El régimen, el código postal fiscal y el uso del CFDI del receptor son "
    "los datos con los que se timbraron sus CFDI, y hacen falta para "
    "cancelarlos o sustituirlos mientras se conservan."
)


async def _export_receivers(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[dict[str, Any]]:
    """The fiscal profiles of the RFCs the patient's invoices were issued to."""
    rfcs = select(func.upper(func.trim(Invoice.billing_tax_id))).where(
        Invoice.clinic_id == clinic_id, Invoice.patient_id == patient_id
    )
    result = await db.execute(
        select(SatReceiver)
        .where(SatReceiver.clinic_id == clinic_id, SatReceiver.rfc.in_(rfcs))
        .order_by(SatReceiver.rfc)
    )
    return [row_to_dict(row) for row in result.scalars().all()]


def get_subject_contributors() -> list[SubjectContributor]:
    return [
        SubjectContributor(
            name="sat_cfdis",
            export=_export_cfdis,
            retention_reason=SAT_RETENTION,
        ),
        SubjectContributor(
            name="sat_receivers",
            export=_export_receivers,
            retention_reason=RECEIVER_RETENTION,
        ),
    ]
