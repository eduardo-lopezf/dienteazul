"""The kinds of sheet a clinic can bring, and what each one needs.

``patients`` creates patients; ``appointments`` and ``balances`` attach to
patients the clinic already has. Each kind names its fields (with the
column names they are recognised by — the first is the template's), the
fields a sheet cannot go without, and its template.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from . import appointments, balances, patients
from .identify import PATIENT_KEYS


@dataclass(frozen=True)
class Kind:
    fields: dict[str, tuple[str, ...]]
    #: Each set: at least one of its fields must be assigned a column.
    required: tuple[frozenset[str], ...]
    #: What the template's columns are, in order.
    template_fields: tuple[str, ...] = ()
    example: dict[str, str] | None = None
    notes: tuple[str, ...] = ()
    title: str = ""


_WHO = frozenset(PATIENT_KEYS) - {"date_of_birth"}

KINDS: dict[str, Kind] = {
    "patients": Kind(
        fields=patients.FIELDS,
        required=(frozenset({"given_name", "full_name"}),),
    ),
    "appointments": Kind(
        fields=appointments.FIELDS,
        required=(_WHO, frozenset({"appointment_date"})),
        template_fields=tuple(appointments.EXAMPLE),
        example=appointments.EXAMPLE,
        notes=appointments.NOTES,
        title="Citas",
    ),
    "balances": Kind(
        fields=balances.FIELDS,
        required=(_WHO, frozenset({"balance", "owed", "credit"})),
        template_fields=tuple(balances.EXAMPLE),
        example=balances.EXAMPLE,
        notes=balances.NOTES,
        title="Saldos",
    ),
}


def missing_required(kind: str, assigned: set[str]) -> list[frozenset[str]]:
    return [group for group in KINDS[kind].required if not group & assigned]


def template_for(kind: str) -> bytes:
    if kind == "patients":
        return patients.template_bytes()
    from openpyxl import Workbook

    spec = KINDS[kind]
    book = Workbook()
    sheet = book.active
    sheet.title = spec.title
    sheet.append([spec.fields[f][0] for f in spec.template_fields])
    sheet.append([(spec.example or {}).get(f, "") for f in spec.template_fields])
    for index, field in enumerate(spec.template_fields):
        sheet.column_dimensions[chr(ord("A") + index)].width = max(
            14, len(spec.fields[field][0]) + 4
        )
    notes = book.create_sheet("Instrucciones")
    for line in spec.notes:
        notes.append([line])
    notes.column_dimensions["A"].width = 110
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
