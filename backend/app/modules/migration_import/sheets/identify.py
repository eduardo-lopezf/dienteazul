"""Who a row of a sheet is about: the clinic's own patients and professionals.

An appointments or balances sheet names people the clinic already has —
imported before from a patients sheet, or typed in by hand. A row is tied
to a patient only when one patient fits: by ID document, email, phone,
the number the previous system gave them, or the full name (narrowed by
date of birth when the sheet has it). None or several is not a guess: the
row is left out and the preview says why.

What is found is recorded as a mapping of this job (the patient's own id
as the source id), so the usual mappers resolve it the usual way — they
never take an id from a file (``CLAUDE.md``, *External IDs*).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .common import parse_date, parse_phone, plain

#: Columns that say who the patient is, shared by every sheet that names one.
PATIENT_KEYS: dict[str, tuple[str, ...]] = {
    "full_name": ("Paciente", "nombre completo", "nombre del paciente", "patient", "full name"),
    "given_name": ("Nombre", "nombres", "nombre(s)", "first name"),
    "family_name": ("Apellidos", "apellido", "apellido paterno", "last name", "surname"),
    "second_family_name": ("Segundo apellido", "apellido materno", "second surname"),
    "date_of_birth": ("Fecha de nacimiento", "fecha nac", "nacimiento", "date of birth", "dob"),
    "national_id": ("Documento de identidad", "curp", "dni", "nif", "rfc", "national id"),
    "email": ("Correo electrónico", "correo", "email", "e-mail"),
    "phone": ("Teléfono", "telefono", "celular", "movil", "phone", "mobile"),
    "patient_number": (
        "Nº de paciente",
        "numero de paciente",
        "expediente",
        "no. expediente",
        "patient number",
    ),
}

# Where the patient mapper writes the previous system's number.
_NUMBER_IN_NOTES = re.compile(r"n[ºo°] paciente origen (\S+)", re.IGNORECASE)
_TITLES = re.compile(r"^(dr|dra|doctor|doctora|lic|mtro|mtra)\.?\s+")


def _id_doc(value: str) -> str:
    return re.sub(r"[\s\-.]", "", value).upper()


def _name(*parts: str | None) -> str:
    return plain(" ".join(p for p in parts if p))


@dataclass
class PatientMatcher:
    region: str | None
    by_id: dict[str, set[UUID]] = field(default_factory=lambda: defaultdict(set))
    by_email: dict[str, set[UUID]] = field(default_factory=lambda: defaultdict(set))
    by_phone: dict[str, set[UUID]] = field(default_factory=lambda: defaultdict(set))
    by_number: dict[str, set[UUID]] = field(default_factory=lambda: defaultdict(set))
    by_name: dict[str, set[UUID]] = field(default_factory=lambda: defaultdict(set))
    born: dict[UUID, date | None] = field(default_factory=dict)

    @classmethod
    async def load(cls, db: AsyncSession, clinic_id: UUID, region: str | None) -> PatientMatcher:
        from app.modules.patients.models import Patient

        matcher = cls(region=region)
        rows = await db.execute(select(Patient).where(Patient.clinic_id == clinic_id))
        for patient in rows.scalars():
            pid = patient.id
            matcher.born[pid] = patient.date_of_birth
            if patient.national_id:
                matcher.by_id[_id_doc(patient.national_id)].add(pid)
            if patient.email:
                matcher.by_email[patient.email.strip().lower()].add(pid)
            phone = parse_phone(patient.phone, region) if patient.phone else None
            if phone:
                matcher.by_phone[phone].add(pid)
            for number in _NUMBER_IN_NOTES.findall(patient.notes or ""):
                matcher.by_number[number.strip().lower()].add(pid)
            matcher.by_name[_name(patient.first_name, patient.last_name)].add(pid)
        return matcher

    def match(self, values: dict[str, str], date_order: str) -> tuple[UUID | None, str]:
        """The one patient ``values`` describe, or why there is none."""
        born = (
            parse_date(values["date_of_birth"], date_order) if "date_of_birth" in values else None
        )

        def narrow(found: set[UUID]) -> set[UUID]:
            if born is not None and len(found) > 1:
                return {pid for pid in found if self.born.get(pid) == born} or found
            return found

        candidates: list[set[UUID]] = []
        if "national_id" in values:
            candidates.append(self.by_id.get(_id_doc(values["national_id"]), set()))
        if "patient_number" in values:
            candidates.append(self.by_number.get(values["patient_number"].strip().lower(), set()))
        if "email" in values:
            candidates.append(self.by_email.get(values["email"].strip().lower(), set()))
        if "phone" in values:
            phone = parse_phone(values["phone"], self.region)
            candidates.append(self.by_phone.get(phone, set()) if phone else set())
        name = _name(
            values.get("full_name"),
            values.get("given_name"),
            values.get("family_name"),
            values.get("second_family_name"),
        )
        if name:
            candidates.append(self.by_name.get(name, set()))

        ambiguous = False
        for found in candidates:
            found = narrow(found)
            if len(found) == 1:
                return next(iter(found)), ""
            if len(found) > 1:
                ambiguous = True
        if ambiguous:
            return (
                None,
                "Varios pacientes coinciden: añade documento, correo o fecha de nacimiento.",
            )
        if not candidates:
            return None, "La fila no dice quién es el paciente."
        return None, "Ningún paciente de la clínica coincide."


@dataclass
class ProfessionalMatcher:
    by_name: dict[str, set[UUID]]

    @classmethod
    async def load(cls, db: AsyncSession, clinic_id: UUID) -> ProfessionalMatcher:
        from app.modules.professionals.models import Professional

        by_name: dict[str, set[UUID]] = defaultdict(set)
        rows = await db.execute(select(Professional).where(Professional.clinic_id == clinic_id))
        for pro in rows.scalars():
            by_name[_name(pro.first_name, pro.last_name)].add(pro.id)
            by_name[_name(pro.last_name, pro.first_name)].add(pro.id)
        return cls(by_name=dict(by_name))

    def match(self, value: str) -> UUID | None:
        """The professional a name means — written either way round, with
        or without "Dr." — when exactly one fits."""
        from rapidfuzz import fuzz, process

        name = _TITLES.sub("", plain(value.replace(",", " ")))
        exact = self.by_name.get(name, set())
        if len(exact) == 1:
            return next(iter(exact))
        hits = process.extract(name, list(self.by_name), scorer=fuzz.token_sort_ratio, limit=3)
        found = {pid for key, score, _ in hits if score >= 90 for pid in self.by_name[key]}
        return next(iter(found)) if len(found) == 1 else None


async def cabinets_by_name(db: AsyncSession, clinic_id: UUID) -> dict[str, UUID]:
    from app.modules.agenda.models import Cabinet

    rows = await db.execute(select(Cabinet).where(Cabinet.clinic_id == clinic_id))
    return {plain(cabinet.name): cabinet.id for cabinet in rows.scalars()}
