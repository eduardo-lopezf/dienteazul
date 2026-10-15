"""Appointments from a spreadsheet, for patients the clinic already has.

One appointment per row: who (see ``identify``), when, for how long, with
whom and where, and how it went. Times are the clinic's wall clock, as the
agenda keeps them. A row without a professional takes the one chosen for
the sheet; a professional or cabinet that is not found is named in the
warnings. The result is a ``.dpm`` of ``appointment`` rows, imported the
usual way.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..dpmf.writer import DpmfWriter
from ..mappers.base import MappingResolver, running
from .common import SOURCE_SYSTEM, parse_date, parse_time, plain, row_uuid
from .identify import PATIENT_KEYS, PatientMatcher, ProfessionalMatcher, cabinets_by_name
from .reader import Sheet

FIELDS: dict[str, tuple[str, ...]] = {
    **PATIENT_KEYS,
    "appointment_date": ("Fecha", "fecha de la cita", "fecha cita", "dia", "date"),
    "appointment_time": ("Hora", "hora de la cita", "hora cita", "hora inicio", "inicio", "time"),
    "duration_minutes": ("Duración (min)", "duracion", "minutos", "duration"),
    "end_time": ("Hora fin", "hora de fin", "fin", "end time"),
    "professional": ("Profesional", "doctor", "doctora", "dentista", "odontologo", "atiende"),
    "cabinet": ("Gabinete", "consultorio", "sillon", "box", "room", "chair"),
    "status": ("Estado", "estatus", "asistencia", "status"),
    "notes": ("Notas", "observaciones", "motivo", "comentarios", "notes"),
}

# What a status cell says → the file's coarse status.
_STATUS: dict[str, tuple[str, ...]] = {
    "attended": (
        "atendida",
        "atendido",
        "asistio",
        "completada",
        "realizada",
        "finalizada",
        "attended",
        "completed",
        "done",
    ),
    "cancelled": ("cancelada", "cancelado", "anulada", "cancelled", "canceled"),
    "no_show": ("no asistio", "no se presento", "falta", "falto", "no show", "no-show"),
    "confirmed": ("confirmada", "confirmado", "confirmed"),
    "scheduled": ("programada", "pendiente", "agendada", "citada", "scheduled", "pending"),
}

DEFAULT_DURATION = 30


def _status(value: str) -> str | None:
    word = plain(value)
    return next((code for code, words in _STATUS.items() if word in words), None)


async def convert_appointments(
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
    problems: list[tuple[str | None, str]] | None = None,
    default_professional_id: UUID | None,
) -> dict[str, int]:
    patients = await PatientMatcher.load(db, clinic_id, region)
    professionals = (
        await ProfessionalMatcher.load(db, clinic_id) if running("professionals") else None
    )
    cabinets = await cabinets_by_name(db, clinic_id)
    resolver = MappingResolver(db=db, clinic_id=clinic_id, job_id=job_id)
    out = DpmfWriter(destination, source_system=SOURCE_SYSTEM)

    for cells, line in zip(sheet.rows, sheet.lines, strict=True):
        source_id = f"fila {line}"
        values = {f: cells[i].strip() for i, f in mapping.items() if cells[i].strip()}

        def skip(code: str, message: str, source_id: str = source_id) -> None:
            out.warn("appointment", source_id, f"sheet.{code}", message)

        patient_id, why = patients.match(values, date_order)
        if patient_id is None:
            skip("patient_not_found", f"Cita no importada: {why}")
            continue

        day = parse_date(values.get("appointment_date", ""), date_order)
        if day is None:
            skip(
                "invalid_date",
                f"Cita no importada: fecha no válida ({values.get('appointment_date', '')}).",
            )
            continue
        raw_date = values.get("appointment_date", "")
        start = parse_time(values["appointment_time"]) if "appointment_time" in values else None
        if start is None and len(raw_date) > 10:  # one cell with date and time
            start = parse_time(raw_date[11:16])
        if start is None:
            skip("invalid_time", "Cita no importada: falta la hora o no es válida.")
            continue

        minutes = DEFAULT_DURATION
        if "duration_minutes" in values and values["duration_minutes"].isdigit():
            minutes = int(values["duration_minutes"])
        elif "end_time" in values:
            end = parse_time(values["end_time"])
            if end is not None and end > start:
                minutes = int(
                    (datetime.combine(day, end) - datetime.combine(day, start))
                    / timedelta(minutes=1)
                )
        minutes = max(5, min(minutes, 12 * 60))

        payload: dict[str, Any] = {
            "patient_uuid": str(patient_id),
            "scheduled_date": day.isoformat(),
            "scheduled_time": start.replace(second=0).isoformat(),
            "duration_minutes": minutes,
            "coarse_status": "scheduled",
        }
        await resolver.set("patient", str(patient_id), SOURCE_SYSTEM, "patients", patient_id)

        professional_id = default_professional_id
        if professionals is not None and values.get("professional"):
            found = professionals.match(values["professional"])
            if found is not None:
                professional_id = found
            else:
                skip(
                    "professional_not_found",
                    f"Profesional no encontrado: {values['professional']}; "
                    + (
                        "se usa el elegido para la hoja."
                        if default_professional_id
                        else "cita sin profesional."
                    ),
                )
        if professional_id is not None:
            payload["professional_uuid"] = str(professional_id)
            await resolver.set(
                "professional",
                str(professional_id),
                SOURCE_SYSTEM,
                "professionals",
                professional_id,
            )

        if values.get("cabinet"):
            cabinet_id = cabinets.get(plain(values["cabinet"]))
            if cabinet_id is None:
                skip(
                    "cabinet_not_found",
                    f"Gabinete no encontrado: {values['cabinet']}; cita sin gabinete.",
                )
            else:
                payload["chair_uuid"] = str(cabinet_id)
                await resolver.set(
                    "catalog_item", str(cabinet_id), SOURCE_SYSTEM, "cabinets", cabinet_id
                )

        if values.get("status"):
            status = _status(values["status"])
            if status is None:
                skip(
                    "invalid_status", f"Estado no reconocido: {values['status']}; queda programada."
                )
            else:
                payload["coarse_status"] = status
        if values.get("notes"):
            payload["notes"] = values["notes"]

        out.add(
            "appointment",
            canonical_uuid=row_uuid(digest, line, "appointment"),
            source_id=source_id,
            payload=payload,
            raw=dict(zip(sheet.headers, cells, strict=True)),
        )

    counts = out.counts
    if problems is not None:
        problems.extend(out.problems)
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
    "appointment_date": "03/11/2026",
    "appointment_time": "10:30",
    "duration_minutes": "45",
    "professional": "Marta Ruiz",
    "cabinet": "Gabinete 1",
    "status": "Programada",
    "notes": "Revisión",
}

NOTES: tuple[str, ...] = (
    "Una cita por fila. La primera fila son los nombres de las columnas.",
    "El paciente ya debe existir en la clínica: se busca por documento, correo, teléfono, nº de paciente anterior o nombre completo.",
    "Fecha y hora son obligatorias. Si no hay duración, cada cita dura 30 minutos.",
    "Profesional y gabinete se buscan por su nombre. Si falta el profesional se usa el que elijas al importar.",
    "Estado: Programada, Confirmada, Atendida, Cancelada o No asistió.",
    "Borra la fila de ejemplo antes de importar.",
)
