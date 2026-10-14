"""Appointments and opening balances from a spreadsheet.

What these pin: rows attach to patients the clinic already has — by ID
document, or by name narrowed by date of birth — and a row that fits
nobody, or several, is left out with a warning; professionals are found
however their name is written; times read "10:30 a.m."; amounts read
"1.250,50"; what a patient owes becomes a charge described as the
previous balance and what they have in favour a payment on account; and
importing the same file twice brings nothing twice.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.agenda.models import Appointment, Cabinet
from app.modules.migration_import import service as import_service
from app.modules.migration_import.models import ImportJob, ImportWarning
from app.modules.migration_import.sheets.common import parse_amount, parse_time
from app.modules.patients.models import Patient
from app.modules.payments.models import PatientEarnedEntry, Payment
from app.modules.professionals.models import Professional

SHEETS = "/api/v1/migration_import/sheets"
JOBS = "/api/v1/migration_import/jobs"


def test_amounts_and_times_read_as_written() -> None:
    assert parse_amount("1.250,50") == Decimal("1250.50")
    assert parse_amount("$1,250.50") == Decimal("1250.50")
    assert parse_amount("-300") == Decimal("-300")
    assert parse_amount("(80,00)") == Decimal("-80.00")
    assert parse_amount("1.250") == Decimal("1250")
    assert parse_amount("abc") is None
    assert parse_time("10:30 a.m.").isoformat() == "10:30:00"
    assert parse_time("4:15 PM").isoformat() == "16:15:00"
    assert parse_time("09:00:00").isoformat() == "09:00:00"


async def _people(db: AsyncSession, clinic: Clinic) -> dict:
    def patient(first: str, last: str, **extra) -> Patient:
        return Patient(id=uuid4(), clinic_id=clinic.id, first_name=first, last_name=last, **extra)

    people = {
        "curp": patient("José", "Núñez Peña", national_id="NUPJ850403HDFXXX01"),
        "ana_80": patient("Ana", "Ruiz", date_of_birth=date(1980, 1, 1)),
        "ana_95": patient("Ana", "Ruiz", date_of_birth=date(1995, 5, 5)),
    }
    marta = Professional(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Marta",
        last_name="Ruiz",
        professional_type="dentist",
        is_active=True,
    )
    db.add_all([*people.values(), marta])
    await db.commit()
    people["marta"] = marta
    return people


async def _import(
    client: AsyncClient,
    headers: dict,
    db: AsyncSession,
    kind: str,
    csv: str,
    extra: dict | None = None,
) -> str:
    up = await client.post(
        SHEETS,
        headers=headers,
        data={"kind": kind},
        files={"file": (f"{kind}.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert up.status_code == 201, up.text
    body = up.json()["data"]
    mapping = {
        str(c["index"]): c["suggested_field"] for c in body["columns"] if c["suggested_field"]
    }
    done = await client.post(
        f"{SHEETS}/{body['job']['id']}/convert",
        headers=headers,
        json={"mapping": mapping, "date_order": "dmy", **(extra or {})},
    )
    assert done.status_code == 200, done.text
    job_id = body["job"]["id"]
    valid = await client.post(f"{JOBS}/{job_id}/validate", headers=headers, json={})
    assert valid.json()["data"]["status"] == "validated", valid.text
    job = (await db.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
    await import_service.ImportJobService._run_pipeline(db, job, passphrase=None)
    return job_id


async def _warnings(db: AsyncSession, job_id: str) -> set[tuple[str, str]]:
    rows = await db.execute(select(ImportWarning).where(ImportWarning.job_id == job_id))
    return {(w.source_id or "", w.code) for w in rows.scalars()}


@pytest.mark.asyncio
async def test_appointments_attach_to_the_clinics_patients(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    people = await _people(db_session, test_clinic)
    up = await client.post(
        SHEETS,
        headers=auth_headers,
        data={"kind": "appointments"},
        files={"file": ("c.csv", b"Paciente;Fecha;Hora\nX;01/01/2027;10:00\n", "text/csv")},
    )
    assert {p["name"] for p in up.json()["data"]["professionals"]} >= {"Marta Ruiz"}

    csv = "\n".join(
        [
            "Paciente;CURP;Fecha de nacimiento;Fecha;Hora;Hora fin;Profesional;Gabinete;Estado;Notas",
            ";NUPJ850403HDFXXX01;;03/11/2026;10:30 a.m.;11:15;Dra. Ruiz Marta;Gabinete 1;Atendida;Limpieza",
            "Ana Ruiz;;05/05/1995;04/11/2026;16:00;;;;;",
            "Ana Ruiz;;;05/11/2026;09:00;;;;;",
            "Nadie Conocido;;;06/11/2026;09:00;;;;;",
            "Ana Ruiz;;01/01/1980;07/11/2026;;;;;;",
        ]
    )
    job_id = await _import(
        client,
        auth_headers,
        db_session,
        "appointments",
        csv,
        {"default_professional_id": str(people["marta"].id)},
    )

    rows = (
        (
            await db_session.execute(
                select(Appointment).where(Appointment.clinic_id == test_clinic.id)
            )
        )
        .scalars()
        .all()
    )
    by_patient = {a.patient_id: a for a in rows}
    assert set(by_patient) == {people["curp"].id, people["ana_95"].id}
    jose = by_patient[people["curp"].id]
    assert jose.start_time == datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
    assert (jose.end_time - jose.start_time).total_seconds() == 45 * 60
    assert jose.status == "completed"
    assert jose.professional_id == people["marta"].id
    cabinet = (
        await db_session.execute(select(Cabinet).where(Cabinet.clinic_id == test_clinic.id))
    ).scalar_one()
    assert jose.cabinet_id == cabinet.id
    # No professional in the row: the one chosen for the sheet.
    assert by_patient[people["ana_95"].id].professional_id == people["marta"].id

    warnings = await _warnings(db_session, job_id)
    assert ("fila 4", "dpmf.sheet.patient_not_found") in warnings  # two Ana Ruiz, no date of birth
    assert ("fila 5", "dpmf.sheet.patient_not_found") in warnings
    assert ("fila 6", "dpmf.sheet.invalid_time") in warnings

    # The same file again: nothing twice.
    await _import(
        client,
        auth_headers,
        db_session,
        "appointments",
        csv,
        {"default_professional_id": str(people["marta"].id)},
    )
    again = (
        (
            await db_session.execute(
                select(Appointment).where(Appointment.clinic_id == test_clinic.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(again) == 2


@pytest.mark.asyncio
async def test_balances_become_charges_and_payments_on_account(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    people = await _people(db_session, test_clinic)
    csv = "\n".join(
        [
            "CURP;Paciente;Fecha de nacimiento;Saldo;Fecha del saldo",
            "NUPJ850403HDFXXX01;;;1.250,50;31/10/2026",
            ";Ana Ruiz;05/05/1995;-300;31/10/2026",
            ";Ana Ruiz;01/01/1980;0;31/10/2026",
        ]
    )
    await _import(client, auth_headers, db_session, "balances", csv)

    charges = (
        (
            await db_session.execute(
                select(PatientEarnedEntry).where(PatientEarnedEntry.clinic_id == test_clinic.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(c.patient_id, c.amount, c.description) for c in charges] == [
        (people["curp"].id, Decimal("1250.50"), "Saldo anterior")
    ]
    payments = (
        (await db_session.execute(select(Payment).where(Payment.clinic_id == test_clinic.id)))
        .scalars()
        .all()
    )
    assert [(p.patient_id, p.amount) for p in payments] == [
        (people["ana_95"].id, Decimal("300.00"))
    ]
    assert "a favor" in payments[0].notes

    await _import(client, auth_headers, db_session, "balances", csv)
    assert (
        len(
            (
                await db_session.execute(
                    select(PatientEarnedEntry).where(PatientEarnedEntry.clinic_id == test_clinic.id)
                )
            )
            .scalars()
            .all()
        )
        == 1
    )


@pytest.mark.asyncio
async def test_a_sheet_says_who_and_what(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    up = await client.post(
        SHEETS,
        headers=auth_headers,
        data={"kind": "balances"},
        files={"file": ("s.csv", b"Paciente;Saldo\nAna;10\n", "text/csv")},
    )
    job_id = up.json()["data"]["job"]["id"]
    no_amount = await client.post(
        f"{SHEETS}/{job_id}/convert", headers=auth_headers, json={"mapping": {"0": "full_name"}}
    )
    assert no_amount.status_code == 422
    no_patient = await client.post(
        f"{SHEETS}/{job_id}/convert", headers=auth_headers, json={"mapping": {"1": "balance"}}
    )
    assert no_patient.status_code == 422
    for kind in ("patients", "appointments", "balances"):
        template = await client.get(f"{SHEETS}/template?kind={kind}", headers=auth_headers)
        assert template.status_code == 200 and template.content[:2] == b"PK"
