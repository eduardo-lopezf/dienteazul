"""Undoing an import, and the clinic's space checked before a migration.

What these pin: an import writes down what it inserts, and undoing removes
exactly that — the rows it only linked to (an existing patient an
appointments sheet was attached to) stay; the undo is refused, saying what
was found, when the clinic recorded something on the imported data after
the import; an import from before the ledger cannot be undone. And: an
upload, an import's documents or an export that does not fit in the
clinic's storage is refused before anything is written, in Spanish.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.models import Clinic, TierLimit
from app.modules.agenda.models import Appointment
from app.modules.migration_import import service as import_service
from app.modules.migration_import.models import EntityMapping, ImportCreatedRow, ImportJob
from app.modules.patients.models import Patient
from app.modules.professionals.models import Professional

SHEETS = "/api/v1/migration_import/sheets"
JOBS = "/api/v1/migration_import/jobs"
EXPORTS = "/api/v1/migration_import/exports"

PATIENTS_CSV = "Nombre;Apellidos;Correo\nAna;Ruiz;ana@example.com\nLuis;Pérez;luis@example.com\n"


async def _import(
    client: AsyncClient,
    headers: dict,
    db: AsyncSession,
    kind: str,
    csv: str,
    extra: dict | None = None,
) -> ImportJob:
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
    await client.post(f"{JOBS}/{job_id}/validate", headers=headers, json={})
    job = (await db.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
    await import_service.ImportJobService._run_pipeline(db, job, passphrase=None)
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    await db.commit()
    return job


async def _patients(db: AsyncSession, clinic: Clinic) -> set[str]:
    # Its identity, not an attribute: readable after the session expired.
    clinic_id = inspect(clinic).identity[0]
    rows = await db.execute(select(Patient.first_name).where(Patient.clinic_id == clinic_id))
    return set(rows.scalars())


@pytest.mark.asyncio
async def test_undo_removes_what_the_import_created_and_nothing_else(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    before = await _patients(db_session, test_clinic)
    job = await _import(client, auth_headers, db_session, "patients", PATIENTS_CSV)
    assert job.tracks_created
    ledger = await db_session.scalar(
        select(func.count()).select_from(ImportCreatedRow).where(ImportCreatedRow.job_id == job.id)
    )
    assert ledger >= 2
    assert await _patients(db_session, test_clinic) == before | {"Ana", "Luis"}

    job_id = job.id
    undone = await client.post(f"{JOBS}/{job_id}/undo", headers=auth_headers)
    assert undone.status_code == 202, undone.text
    db_session.expire_all()  # the undo ran in a session of its own
    after = (await client.get(f"{JOBS}/{job_id}", headers=auth_headers)).json()["data"]
    assert after["status"] == "undone" and after["undone_at"]
    assert await _patients(db_session, test_clinic) == before
    assert (
        not (await db_session.execute(select(EntityMapping).where(EntityMapping.job_id == job_id)))
        .scalars()
        .all()
    )

    # Undone is final.
    again = await client.post(f"{JOBS}/{job_id}/undo", headers=auth_headers)
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_rows_only_linked_to_stay_and_later_work_holds_the_undo(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    marta = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Marta",
        last_name="Ruiz",
        professional_type="dentist",
        is_active=True,
    )
    existing = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Eva", last_name="Sol")
    db_session.add_all([marta, existing])
    await db_session.commit()
    clinic_id, marta_id, existing_id = test_clinic.id, marta.id, existing.id

    # Appointments for a patient the clinic already had: only they are the import's.
    appointments = await _import(
        client,
        auth_headers,
        db_session,
        "appointments",
        "Paciente;Fecha;Hora\nEva Sol;03/11/2026;10:00\n",
        {"default_professional_id": str(marta_id)},
    )
    undone = await client.post(f"{JOBS}/{appointments.id}/undo", headers=auth_headers)
    assert undone.status_code == 202, undone.text
    db_session.expire_all()
    assert (
        not (
            await db_session.execute(select(Appointment).where(Appointment.clinic_id == clinic_id))
        )
        .scalars()
        .all()
    )
    assert await db_session.get(Patient, existing_id) is not None  # linked, not created
    assert await db_session.get(Professional, marta_id) is not None

    # Patients imported, then booked by the clinic after the import ended.
    patients = await _import(client, auth_headers, db_session, "patients", PATIENTS_CSV)
    patients_id = patients.id
    ana = (
        await db_session.execute(
            select(Patient).where(Patient.clinic_id == clinic_id, Patient.first_name == "Ana")
        )
    ).scalar_one()
    start = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    booked = Appointment(
        id=uuid4(),
        clinic_id=clinic_id,
        patient_id=ana.id,
        professional_id=marta_id,
        start_time=start,
        end_time=start + timedelta(minutes=30),
        status="scheduled",
        created_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(booked)
    await db_session.commit()
    refused = await client.post(f"{JOBS}/{patients_id}/undo", headers=auth_headers)
    assert refused.status_code == 409
    assert "1 citas" in refused.json()["message"]
    names = await db_session.execute(
        select(Patient.first_name).where(Patient.clinic_id == clinic_id)
    )
    assert "Ana" in set(names.scalars())


@pytest.mark.asyncio
async def test_an_import_from_before_the_ledger_cannot_be_undone(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    old = ImportJob(
        id=uuid4(),
        clinic_id=test_clinic.id,
        created_by=me.json()["data"]["user"]["id"],
        status="completed",
        original_filename="old.dpm",
        file_path="/nonexistent",
    )
    db_session.add(old)
    await db_session.commit()
    refused = await client.post(f"{JOBS}/{old.id}/undo", headers=auth_headers)
    assert refused.status_code == 409
    assert "antes de que se registrara" in refused.json()["message"]


@pytest.mark.asyncio
async def test_what_does_not_fit_in_the_clinics_storage_is_refused(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    folder = tmp_path / str(test_clinic.id)
    folder.mkdir()
    (folder / "held.bin").write_bytes(b"0" * (1024 * 1024 - 100))
    db_session.add(TierLimit(tier=test_clinic.account_tier, storage_mb=1))
    await db_session.commit()

    big = "Nombre\n" + "Ana\n" * 200
    refused = await client.post(
        SHEETS, headers=auth_headers, files={"file": ("p.csv", big.encode(), "text/csv")}
    )
    assert refused.status_code == 403
    message = refused.json()["message"]
    assert message.startswith("No hay espacio suficiente para subir esta hoja")
    assert "quedan 0.0 MB" in message

    # An export that would not fit beside what the clinic keeps.
    export = await client.post(
        EXPORTS, headers=auth_headers, json={"passphrase": "una contraseña larga"}
    )
    assert export.status_code == 202  # no documents to carry: it fits

    from app.modules.migration_import.export import ExportJobService

    monkeypatch.setattr(
        ExportJobService, "expected_bytes", staticmethod(lambda *_a, **_k: _async(5 * 1024 * 1024))
    )
    too_big = await client.post(
        EXPORTS, headers=auth_headers, json={"passphrase": "una contraseña larga"}
    )
    assert too_big.status_code == 403
    assert "generar la exportación" in too_big.json()["message"]


async def _async(value: int) -> int:
    return value


@pytest.mark.asyncio
async def test_undoing_an_import_with_documents_removes_their_files(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    from app.modules.media.models import Document
    from app.modules.media.service import DocumentService
    from app.modules.media.storage import get_storage_backend
    from app.modules.migration_import.export import write_clinic_export
    from app.modules.migration_import.service import ImportUndoService

    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    await DocumentService.create_document(
        db=db_session,
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        user_id=user_id,
        file_data=b"%PDF radiografia",
        original_filename="rx.pdf",
        mime_type="application/pdf",
        document_type="xray",
        title="Rx",
    )
    other = Clinic(id=uuid4(), name="Destino", tax_id="B44444444", account_tier="clinic")
    db_session.add(other)
    await db_session.commit()
    other_id = other.id
    target = tmp_path / "c.dpm"
    await write_clinic_export(db_session, test_clinic.id, target, passphrase="una contraseña larga")
    job = ImportJob(
        id=uuid4(),
        clinic_id=other_id,
        created_by=user_id,
        status="executing",
        original_filename="c.dpm",
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(
        db_session, job, passphrase="una contraseña larga"
    )
    job.status, job.completed_at = "completed", datetime.now(UTC)
    job.execute_options = {"status_before_undo": "completed"}
    await db_session.commit()
    (imported,) = (
        (await db_session.execute(select(Document).where(Document.clinic_id == other_id)))
        .scalars()
        .all()
    )
    path = imported.storage_path
    storage = get_storage_backend()
    assert await storage.retrieve(path) == b"%PDF radiografia"

    job.status = "undoing"
    await db_session.commit()
    job_id = job.id
    await ImportUndoService.undo_in_background(job_id, user_id)
    db_session.expire_all()
    assert (await db_session.get(ImportJob, job_id)).status == "undone"
    assert (
        not (await db_session.execute(select(Document).where(Document.clinic_id == other_id)))
        .scalars()
        .all()
    )
    assert (
        not (await db_session.execute(select(Patient).where(Patient.clinic_id == other_id)))
        .scalars()
        .all()
    )
    with pytest.raises(Exception):  # noqa: B017 — the backend's own "not found"
        await storage.retrieve(path)
