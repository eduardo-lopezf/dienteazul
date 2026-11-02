"""What this module answers when a patient exercises their rights.

Almost all of the inventory is about things, not people: articles,
shelves, batches, movements. One table is not. ``inv_implant_traces``
records which batch of which device went into which patient, and it
exists because a manufacturer's recall has to be answerable with a list
of names.

That is why this section **refuses erasure**. Traceability of an
implanted medical device is an obligation the clinic carries towards the
patient and towards the authority, and it outlives a deletion request
the same way a fiscal record does: scrubbing the link would not protect
the patient, it would make the clinic unable to warn them if their batch
is withdrawn.

Export is unconditional — portability has no such exception — and it is
also the practical answer to "what am I carrying?", which is a question
patients ask.

See ``app.core.privacy.subject`` and ADR 0026.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.privacy import SubjectContributor

from .models import ImplantTrace

RETENTION_REASON = (
    "La trazabilidad de un producto sanitario implantado es una obligación legal: "
    "la clínica debe poder identificar qué lote lleva cada paciente para avisarle "
    "si el fabricante lo retira. Por eso este registro se conserva aunque se "
    "soliciten la supresión del resto de los datos."
)


async def _export_traces(
    db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> list[dict[str, Any]]:
    """Every device recorded for this patient, named rather than keyed.

    The ids of articles and batches mean nothing outside this database,
    so the export carries the code, the name and the batch the patient
    would need to give to anybody else.
    """
    result = await db.execute(
        select(ImplantTrace)
        .options(joinedload(ImplantTrace.item), joinedload(ImplantTrace.lot))
        .where(ImplantTrace.clinic_id == clinic_id, ImplantTrace.patient_id == patient_id)
        .order_by(ImplantTrace.placed_on)
    )
    return [
        {
            "placed_on": trace.placed_on,
            "device_code": trace.item.code,
            "device_name": trace.item.name,
            "lot_code": trace.lot.lot_code,
            "lot_expires_on": trace.lot.expires_on,
            "serial_number": trace.serial_number,
            "tooth_number": trace.tooth_number,
            "notes": trace.notes,
            "recorded_at": trace.created_at,
        }
        for trace in result.unique().scalars().all()
    ]


def get_subject_contributors() -> list[SubjectContributor]:
    return [
        SubjectContributor(
            name="implant_traces",
            export=_export_traces,
            # No `anonymize`: see RETENTION_REASON. The contract refuses
            # silence about erasability, which is the point of ADR 0026.
            retention_reason=RETENTION_REASON,
        )
    ]
