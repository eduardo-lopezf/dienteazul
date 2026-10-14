"""Patients from a spreadsheet: which column is which, and the ``.dpm`` it makes.

A sheet is not imported straight into the clinic. It is turned into a
``.dpm`` with one ``patient`` row per sheet row — the payload keys the
patient mapper reads — and from there the import is the same as any
other: validated, previewed, run, idempotent. Each row's id is derived
from the file's hash and its line, so converting the same file twice and
importing it again creates nobody twice.

What a value means is decided here, once: dates by the order the person
chose (03/04 is not guessed), phones to international format by the
clinic's country, sex from the words people use. A value that does not
fit is dropped from that patient and named in the file's warnings, which
the preview shows.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from ..dpmf.writer import DpmfWriter
from .common import SOURCE_SYSTEM, parse_date, parse_phone, plain, row_uuid, suggest
from .reader import Sheet

#: Field → the column names it is recognised by (compared without
#: accents or case). The first is the one the template uses.
FIELDS: dict[str, tuple[str, ...]] = {
    "given_name": ("Nombre", "nombres", "first name", "given name", "name"),
    "family_name": (
        "Apellidos",
        "apellido",
        "apellido paterno",
        "primer apellido",
        "last name",
        "surname",
        "family name",
    ),
    "second_family_name": (
        "Segundo apellido",
        "apellido materno",
        "second surname",
        "mother's surname",
    ),
    "full_name": ("Nombre completo", "paciente", "full name", "nombre y apellidos", "patient"),
    "date_of_birth": (
        "Fecha de nacimiento",
        "nacimiento",
        "fecha nacimiento",
        "fecha nac",
        "fecha nac.",
        "f. nacimiento",
        "date of birth",
        "birth date",
        "dob",
        "birthday",
    ),
    "sex": ("Sexo", "genero", "género", "sex", "gender"),
    "national_id": (
        "Documento de identidad",
        "curp",
        "dni",
        "nif",
        "rfc",
        "identificacion",
        "id number",
        "national id",
    ),
    "phone": (
        "Teléfono",
        "telefono",
        "tel",
        "tel. fijo",
        "telefono fijo",
        "telefono casa",
        "phone",
        "landline",
    ),
    "mobile_phone": ("Celular", "movil", "móvil", "whatsapp", "mobile", "cell", "cell phone"),
    "email": ("Correo electrónico", "correo", "email", "e-mail", "mail"),
    "address_street": ("Domicilio", "direccion", "dirección", "calle", "address", "street"),
    "address_postal_code": ("Código postal", "cp", "c.p.", "postal code", "zip", "zip code"),
    "patient_number": (
        "Nº de paciente",
        "numero de paciente",
        "expediente",
        "no. expediente",
        "folio",
        "patient number",
        "record number",
    ),
    "medical_notes": (
        "Notas médicas",
        "alergias",
        "antecedentes",
        "medicacion",
        "observaciones medicas",
        "medical notes",
        "allergies",
    ),
}

_SEX = {
    "male": ("m", "h", "hombre", "masculino", "varon", "male", "man"),
    "female": ("f", "mujer", "femenino", "female", "woman"),
    "other": ("otro", "other", "x"),
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _sex(value: str) -> str | None:
    word = plain(value)
    return next((sex for sex, words in _SEX.items() if word in words), None)


def suggest_fields(headers: list[str]) -> list[str | None]:
    """The field each column of a patients sheet most likely holds."""
    return suggest(headers, FIELDS)


def convert_patients(
    sheet: Sheet,
    mapping: dict[int, str],
    *,
    date_order: str,
    region: str | None,
    digest: str,
    destination: Path,
    label: str,
) -> dict[str, int]:
    """Write ``sheet`` as a plain ``.dpm`` at ``destination``. Returns counts."""
    out = DpmfWriter(destination, source_system=SOURCE_SYSTEM)
    for cells, line in zip(sheet.rows, sheet.lines, strict=True):
        source_id = f"fila {line}"
        values = {field: cells[index].strip() for index, field in mapping.items()}
        values = {field: value for field, value in values.items() if value}

        given = values.get("given_name", "")
        family = " ".join(
            part for part in (values.get("family_name"), values.get("second_family_name")) if part
        )
        if not given and values.get("full_name"):
            first, _, rest = values["full_name"].partition(" ")
            given, family = first, family or rest
        if not given:
            out.warn("patient", source_id, "sheet.no_name", "Fila sin nombre: no se importa.")
            continue

        payload: dict[str, Any] = {"given_name": given, "family_name": family or None}

        def problem(field: str, message: str, source_id: str = source_id) -> None:
            out.warn("patient", source_id, f"sheet.invalid_{field}", message)

        if "date_of_birth" in values:
            born = parse_date(values["date_of_birth"], date_order)
            if born is None or born > date.today() or born.year < 1900:
                problem(
                    "date_of_birth", f"Fecha de nacimiento no válida: {values['date_of_birth']}."
                )
            else:
                payload["date_of_birth"] = born.isoformat()
        if "sex" in values:
            sex = _sex(values["sex"])
            if sex is None:
                problem("sex", f"Sexo no reconocido: {values['sex']}.")
            else:
                payload["sex"] = sex
        for field in ("phone", "mobile_phone"):
            if field in values:
                phone = parse_phone(values[field], region)
                if phone is None:
                    problem(field, f"Teléfono no válido: {values[field]}.")
                else:
                    payload[field] = phone
        if "email" in values:
            email = values["email"].lower()
            if _EMAIL.match(email):
                payload["email"] = email
            else:
                problem("email", f"Correo no válido: {values['email']}.")
        for field in ("national_id", "address_street", "address_postal_code", "patient_number"):
            if field in values:
                payload[field] = values[field]
        if "medical_notes" in values:
            # The patient mapper reads ``notes`` as medical alerts and
            # files each line where it belongs (allergies, medication…).
            payload["notes"] = values["medical_notes"]

        out.add(
            "patient",
            canonical_uuid=row_uuid(digest, line),
            source_id=source_id,
            payload=payload,
            raw=dict(zip(sheet.headers, cells, strict=True)),
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


def template_bytes() -> bytes:
    """An ``.xlsx`` with the columns the import recognises and one example."""
    import io

    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation

    book = Workbook()
    sheet = book.active
    sheet.title = "Pacientes"
    # The template asks for both surnames in one column.
    fields = [f for f in FIELDS if f not in ("full_name", "second_family_name")]
    sheet.append([FIELDS[f][0] for f in fields])
    example = {
        "given_name": "María",
        "family_name": "López García",
        "date_of_birth": "31/12/1980",
        "sex": "Mujer",
        "national_id": "",
        "phone": "",
        "mobile_phone": "+52 55 1234 5678",
        "email": "maria@example.com",
        "address_street": "Av. Reforma 100",
        "address_postal_code": "06600",
        "patient_number": "1024",
        "medical_notes": "Alergia a la penicilina",
    }
    sheet.append([example[f] for f in fields])
    choice = DataValidation(type="list", formula1='"Hombre,Mujer,Otro"', allow_blank=True)
    sheet.add_data_validation(choice)
    column = chr(ord("A") + fields.index("sex"))
    choice.add(f"{column}2:{column}5000")
    for index, field in enumerate(fields):
        sheet.column_dimensions[chr(ord("A") + index)].width = max(14, len(FIELDS[field][0]) + 4)
    notes = book.create_sheet("Instrucciones")
    for line in (
        "Un paciente por fila. La primera fila son los nombres de las columnas.",
        "Solo el Nombre es obligatorio; deja vacío lo que no tengas.",
        "Fechas como día/mes/año (31/12/1980); al importar se puede elegir otro orden.",
        "Teléfonos con o sin prefijo internacional; sin él se usa el del país de la clínica.",
        "Notas médicas: una alergia o medicación por línea se archiva en su sitio.",
        "Borra la fila de ejemplo antes de importar.",
    ):
        notes.append([line])
    notes.column_dimensions["A"].width = 90
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
