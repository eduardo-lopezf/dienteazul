"""Data migration runs on its own (ADR 0037).

What these pin: nothing is required — the manifest integrates every App
it writes into and depends on none; a kind of record whose App is off is
not imported, is announced in the preview, and leaves one warning in the
run; one whose App only adds a part (a note) is imported without it.
"""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.plugins.registry import module_registry
from app.modules.migration_import import MigrationImportModule
from app.modules.migration_import import service as import_service
from app.modules.migration_import.mappers import missing_for, partial_for
from app.modules.migration_import.models import ImportJob, ImportWarning
from app.modules.recalls.models import Recall


def _without(monkeypatch, *off: str) -> None:
    real = module_registry.is_installed
    monkeypatch.setattr(
        module_registry, "is_installed", lambda name: name not in off and real(name)
    )


class _Handle:
    """Just enough of a DPMF: two recalls and an empty appointment table."""

    counts = {"recall": 2, "appointment": 0}

    def entity_counts(self) -> dict[str, int]:
        return dict(self.counts)

    def entity_iter(self, entity_type: str):
        for n in range(self.counts.get(entity_type, 0)):
            yield (f"{entity_type}-{n}", str(n), "test", "{}", "{}", None)

    def warnings_iter(self):
        return iter(())

    def files_iter(self):
        return iter(())


def test_it_requires_no_app() -> None:
    manifest = MigrationImportModule.manifest
    assert manifest["depends"] == []
    assert {
        "patients",
        "patients_clinical",
        "catalog",
        "odontogram",
        "treatment_plan",
        "media",
        "clinical_notes",
        "agenda",
        "schedules",
        "recalls",
        "professionals",
        "budget",
        "payments",
        "billing",
        "consents",
    } <= set(manifest["integrates"])


def test_what_is_left_out_follows_what_is_off(monkeypatch) -> None:
    _without(monkeypatch, "recalls", "clinical_notes")
    assert missing_for("recall") == ["recalls"]
    assert missing_for("appointment") == []
    assert partial_for("appointment") == ["clinical_notes"]
    # Core-only records need nothing.
    assert missing_for("user") == []

    previews = {
        p.entity_type: p for p in import_service.ImportJobService._build_entity_previews(_Handle())
    }
    assert previews["recall"].missing_modules == ["recalls"]
    assert previews["appointment"].partial_modules == ["clinical_notes"]


@pytest.mark.asyncio
async def test_a_run_skips_what_belongs_to_an_app_that_is_off(
    monkeypatch, db_session: AsyncSession, client: AsyncClient, auth_headers: dict
) -> None:
    _without(monkeypatch, "recalls", "clinical_notes")

    @contextmanager
    def fake_open(path, passphrase=None):
        yield _Handle()

    monkeypatch.setattr(import_service, "open_dpmf", fake_open)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic = Clinic(id=uuid4(), name="Migration Clinic", tax_id="B22222222", account_tier="clinic")
    db_session.add(clinic)
    await db_session.flush()
    job = ImportJob(
        id=uuid4(),
        clinic_id=clinic.id,
        created_by=user_id,
        status="executing",
        original_filename="test.dpm",
        file_path="/nonexistent.dpm",
    )
    db_session.add(job)
    await db_session.commit()

    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=None)

    warnings = {
        w.code: w
        for w in (
            await db_session.execute(select(ImportWarning).where(ImportWarning.job_id == job.id))
        ).scalars()
    }
    assert warnings["app.disabled"].entity_type == "recall"
    assert warnings["app.partial"].entity_type == "appointment"
    assert job.processed_entities == 2
    recalls = await db_session.execute(
        select(func.count(Recall.id)).where(Recall.clinic_id == clinic.id)
    )
    assert recalls.scalar() == 0
