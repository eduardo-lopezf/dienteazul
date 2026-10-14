"""Opening balances from a spreadsheet: what each patient owed, or had paid
ahead, in the previous system.

One row per patient. A positive balance — or an amount in an "owes"
column — lands on the patient's account as a charge described as the
previous balance; a negative one — or an amount in an "in favour" column —
as a payment on account. Amounts read both 1,234.50 and 1.234,50. The
result is a ``.dpm`` of ``debt`` and ``payment`` rows, imported the usual
way; patients are found as in ``identify``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..dpmf.writer import DpmfWriter
from ..mappers.base import MappingResolver
from .common import SOURCE_SYSTEM, parse_amount, parse_date, row_uuid
from .identify import PATIENT_KEYS, PatientMatcher
from .reader import Sheet

FIELDS: dict[str, tuple[str, ...]] = {
    **PATIENT_KEYS,
    "balance": ("Saldo", "saldo pendiente", "saldo actual", "balance"),
    "owed": ("Debe", "adeudo", "deuda", "por cobrar", "owed", "amount due"),
    "credit": ("A favor", "saldo a favor", "anticipo", "credito", "credit"),
    "balance_date": ("Fecha del saldo", "fecha de corte", "fecha", "as of", "date"),
    "concept": ("Concepto", "descripcion", "detalle", "concept", "description"),
}

PREVIOUS = "Saldo anterior"


async def convert_balances(
    db: AsyncSession,
    *,
    clinic_id: UUID,
    job_id: UUID,
    sheet: Sheet,
    mapping: dict[int, str],
    date_order: str,
    region: str | None,
    digest: str,
    destination: Path,
    label: str,
) -> dict[str, int]:
    patients = await PatientMatcher.load(db, clinic_id, region)
    resolver = MappingResolver(db=db, clinic_id=clinic_id, job_id=job_id)
    out = DpmfWriter(destination, source_system=SOURCE_SYSTEM)

    for cells, line in zip(sheet.rows, sheet.lines, strict=True):
        source_id = f"fila {line}"
        values = {f: cells[i].strip() for i, f in mapping.items() if cells[i].strip()}

        amounts: dict[str, Decimal] = {}
        for column in ("balance", "owed", "credit"):
            if column in values:
                amount = parse_amount(values[column])
                if amount is None:
                    out.warn(
                        "debt",
                        source_id,
                        "sheet.invalid_amount",
                        f"Importe no válido: {values[column]}.",
                    )
                    continue
                amounts[column] = amount
        owed = max(amounts.get("balance", Decimal(0)), Decimal(0)) + abs(
            amounts.get("owed", Decimal(0))
        )
        credit = max(-amounts.get("balance", Decimal(0)), Decimal(0)) + abs(
            amounts.get("credit", Decimal(0))
        )
        if not owed and not credit:
            continue  # nothing owed either way: nothing to bring

        patient_id, why = patients.match(values, date_order)
        if patient_id is None:
            out.warn("debt", source_id, "sheet.patient_not_found", f"Saldo no importado: {why}")
            continue
        await resolver.set("patient", str(patient_id), SOURCE_SYSTEM, "patients", patient_id)

        when = (
            parse_date(values["balance_date"], date_order) if "balance_date" in values else None
        ) or date.today()
        concept = values.get("concept") or PREVIOUS
        raw: dict[str, Any] = dict(zip(sheet.headers, cells, strict=True))
        if owed:
            out.add(
                "debt",
                canonical_uuid=row_uuid(digest, line, "debt"),
                source_id=source_id,
                payload={
                    "patient_uuid": str(patient_id),
                    "owed_amount": str(owed),
                    "due_date": when.isoformat(),
                    "description": concept,
                },
                raw=raw,
            )
        if credit:
            out.add(
                "payment",
                canonical_uuid=row_uuid(digest, line, "credit"),
                source_id=source_id,
                payload={
                    "patient_uuid": str(patient_id),
                    "amount": str(credit),
                    "paid_on": when.isoformat(),
                    "notes": f"{concept} (a favor del paciente)",
                },
                raw=raw,
            )

    counts = out.counts
    out.finish(
        {
            "exporter_tool": "dienteazul-sheet",
            "exporter_version": "0.1.0",
            "source_adapter_version": "0.1.0",
            "tenant_label": label,
        }
    )
    return counts


EXAMPLE: dict[str, str] = {
    "full_name": "María López García",
    "national_id": "",
    "balance": "1,250.00",
    "balance_date": "31/10/2026",
    "concept": "Saldo anterior",
}

NOTES: tuple[str, ...] = (
    "Una fila por paciente. La primera fila son los nombres de las columnas.",
    "El paciente ya debe existir en la clínica: se busca por documento, correo, teléfono, nº de paciente anterior o nombre completo.",
    "Saldo positivo: lo que el paciente debe. Negativo: lo que tiene a favor. También puedes usar dos columnas, Debe y A favor.",
    "Los importes se leen con punto o coma decimal (1,250.00 o 1.250,00).",
    "Si no hay fecha se usa la del día de la importación.",
    "Borra la fila de ejemplo antes de importar.",
)
