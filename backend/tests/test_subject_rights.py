"""The subject-rights contract, and what it does to real patient data.

Two things are being pinned. First the contract itself: a module cannot
stay silent about whether its data is erasable, because
:class:`SubjectContributor` refuses to be constructed without either an
``anonymize`` callable or a stated ``retention_reason``. Second the
behaviour that matters when a patient actually asks — a name disappears
from the clinical record while the invoice that carries it survives, and
the export says so rather than leaving the clinic to discover it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth.models import Clinic, User
from app.core.privacy import (
    ANONYMIZED,
    SubjectContributor,
    SubjectDataService,
    anonymize_instance,
)
from app.modules.billing.models import Invoice
from app.modules.patients.models import Patient
from app.modules.patients_clinical.models import Allergy, LegalGuardian


class TestContributorContract:
    def test_erasable_contributor_needs_no_reason(self) -> None:
        contributor = SubjectContributor(name="x", export=_noop_export, anonymize=_noop_anonymize)
        assert contributor.erasable

    def test_silence_about_erasability_is_refused(self) -> None:
        # The whole point: a module that neither erases nor explains why
        # would be data quietly surviving an erasure request.
        with pytest.raises(ValueError, match="must state a retention_reason"):
            SubjectContributor(name="x", export=_noop_export)

    def test_cannot_both_erase_and_claim_retention(self) -> None:
        with pytest.raises(ValueError, match="can only be one"):
            SubjectContributor(
                name="x",
                export=_noop_export,
                anonymize=_noop_anonymize,
                retention_reason="because",
            )

    def test_name_is_required(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            SubjectContributor(name="", export=_noop_export, anonymize=_noop_anonymize)


class TestAnonymizeInstance:
    def test_scrubs_classified_columns(self) -> None:
        patient = Patient(
            clinic_id=uuid4(),
            first_name="Ana",
            last_name="García",
            phone="5512345678",
            email="ana@example.com",
            national_id="GOMA850101HDFNRL09",
        )
        scrubbed = anonymize_instance(patient)

        assert scrubbed >= 5
        assert patient.phone is None
        assert patient.email is None
        assert patient.national_id is None
        # Non-nullable columns cannot go to NULL, so they carry a marker.
        assert patient.first_name == ANONYMIZED
        assert patient.last_name == ANONYMIZED

    def test_leaves_financial_columns_alone(self) -> None:
        # Erasing the name off a fiscal document breaks the record rather
        # than protecting the person.
        patient = Patient(
            clinic_id=uuid4(),
            first_name="Ana",
            last_name="García",
            billing_name="Ana García",
            billing_tax_id="GOMA850101AB1",
        )
        anonymize_instance(patient)

        assert patient.billing_name == "Ana García"
        assert patient.billing_tax_id == "GOMA850101AB1"

    def test_ignores_unclassified_columns(self) -> None:
        patient = Patient(clinic_id=uuid4(), first_name="A", last_name="B", status="active")
        anonymize_instance(patient)
        assert patient.status == "active"

    def test_is_idempotent(self) -> None:
        patient = Patient(clinic_id=uuid4(), first_name="Ana", last_name="G", phone="55")
        anonymize_instance(patient)
        assert anonymize_instance(patient) == 0


@pytest.mark.asyncio
class TestFanOutOverModules:
    async def test_export_gathers_every_installed_module(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        sections = await SubjectDataService.export(db_session, clinic.id, patient.id)

        by_name = {s.qualified_name: s for s in sections}
        assert "patients.identity" in by_name
        assert "patients_clinical.clinical_history" in by_name
        assert "billing.invoices" in by_name

    async def test_export_carries_the_actual_values(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        sections = await SubjectDataService.export(db_session, clinic.id, patient.id)

        identity = next(s for s in sections if s.qualified_name == "patients.identity")
        assert identity.rows[0]["first_name"] == "Ana"
        assert identity.rows[0]["national_id"] == "GOMA850101HDFNRL09"

        history = next(
            s for s in sections if s.qualified_name == "patients_clinical.clinical_history"
        )
        assert any(row["name"] == "Penicilina" for row in history.rows)

    async def test_empty_sections_still_reported(self, db_session) -> None:
        # "This module holds nothing" is an answer; a missing section is
        # not, because the reader cannot tell it was asked.
        clinic, patient = await _bootstrap(db_session, with_invoice=False)
        sections = await SubjectDataService.export(db_session, clinic.id, patient.id)

        invoices = next(s for s in sections if s.qualified_name == "billing.invoices")
        assert invoices.rows == []

    async def test_export_is_scoped_to_the_clinic(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        other_clinic = Clinic(id=uuid4(), name="Otra", tax_id="B2", account_tier="clinic")
        db_session.add(other_clinic)
        await db_session.flush()

        sections = await SubjectDataService.export(db_session, other_clinic.id, patient.id)
        assert all(section.rows == [] for section in sections)


@pytest.mark.asyncio
class TestErasure:
    async def test_scrubs_identity_and_clinical_data(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        await SubjectDataService.anonymize(db_session, clinic.id, patient.id)
        await db_session.flush()

        refreshed = (
            await db_session.execute(select(Patient).where(Patient.id == patient.id))
        ).scalar_one()
        assert refreshed.first_name == ANONYMIZED
        assert refreshed.phone is None
        assert refreshed.national_id is None
        # A quasi-identifier: harmless alone, re-identifying next to a
        # clinical record.
        assert refreshed.date_of_birth is None
        # The row survives — invoices and appointments point at it.
        assert refreshed.status == "archived"

    async def test_third_party_contacts_go_too(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        await SubjectDataService.anonymize(db_session, clinic.id, patient.id)
        await db_session.flush()

        guardian = (
            await db_session.execute(
                select(LegalGuardian).where(LegalGuardian.patient_id == patient.id)
            )
        ).scalar_one()
        assert guardian.name == ANONYMIZED
        assert guardian.dni is None

    async def test_invoices_are_retained_with_a_reason(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        scrubbed, retained = await SubjectDataService.anonymize(db_session, clinic.id, patient.id)
        await db_session.flush()

        assert "billing.invoices" not in scrubbed
        reasons = {r.qualified_name: r.reason for r in retained}
        assert "billing.invoices" in reasons
        assert "fiscal" in reasons["billing.invoices"].lower()

        invoice = (
            await db_session.execute(select(Invoice).where(Invoice.patient_id == patient.id))
        ).scalar_one()
        assert invoice.billing_name == "Ana García"

    async def test_reports_what_it_scrubbed(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        scrubbed, _ = await SubjectDataService.anonymize(db_session, clinic.id, patient.id)

        assert scrubbed["patients.identity"] > 0
        assert scrubbed["patients_clinical.contacts"] > 0

    async def test_other_patients_are_untouched(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        other = Patient(
            clinic_id=clinic.id, first_name="Beto", last_name="Ruiz", phone="5599999999"
        )
        db_session.add(other)
        await db_session.flush()

        await SubjectDataService.anonymize(db_session, clinic.id, patient.id)
        await db_session.flush()

        refreshed = (
            await db_session.execute(select(Patient).where(Patient.id == other.id))
        ).scalar_one()
        assert refreshed.first_name == "Beto"
        assert refreshed.phone == "5599999999"


@pytest.mark.asyncio
class TestEveryContributorRuns:
    """Smoke the whole fan-out against a real patient.

    Cheap, and it is what catches a broken ``ChildLink`` chain or a
    column renamed out from under a query — failures that would otherwise
    surface the first time a clinic answered a real request.
    """

    async def test_every_export_executes(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        sections = await SubjectDataService.export(db_session, clinic.id, patient.id)
        assert len(sections) >= 20

    async def test_every_anonymize_executes(self, db_session) -> None:
        clinic, patient = await _bootstrap(db_session)
        scrubbed, retained = await SubjectDataService.anonymize(db_session, clinic.id, patient.id)
        await db_session.flush()
        assert scrubbed
        assert retained

    async def test_clinical_sections_refuse_erasure(self, db_session) -> None:
        # The design principle: identity is erased, the clinical record is
        # retained and thereby becomes pseudonymous.
        clinic, patient = await _bootstrap(db_session)
        _, retained = await SubjectDataService.anonymize(db_session, clinic.id, patient.id)

        names = {r.qualified_name for r in retained}
        assert {
            "agenda.appointments",
            "odontogram.dental_chart",
            "periodontogram.periodontal_charts",
            "treatment_plan.treatment_plans",
            "clinical_notes.notes",
            "media.documents",
            "payments.payments",
            "billing.invoices",
        } <= names

    async def test_outreach_sections_do_erase(self, db_session) -> None:
        # Nothing obliges a clinic to keep a reminder it sent.
        clinic, patient = await _bootstrap(db_session)
        scrubbed, retained = await SubjectDataService.anonymize(db_session, clinic.id, patient.id)

        retained_names = {r.qualified_name for r in retained}
        for section in (
            "recalls.recalls",
            "notifications.messages",
            "patient_timeline.timeline",
            "budget.budgets",
            "migration_import.source_records",
        ):
            assert section not in retained_names
            assert section in scrubbed


class TestCoverage:
    """Which modules answer, and which are deliberately silent."""

    # Modules that hold nothing about a patient. Each entry is a
    # decision, not an omission: catalogs, staff schedules, the clinic's
    # own channel settings and report queries hold no patient row.
    #
    # `cashbox` is the till, and its own models say so: a movement is
    # money in or out that is *not* a patient payment, and the three
    # tables key on `clinics.id` and `users.id` with no `patient_id`
    # anywhere. The one place patient-derived figures could have landed is
    # a closing's `snapshot`, and that holds totals by payment method with
    # their counts — no rows, no identifiers. Patient payments live in
    # `payments`, which contributes for both modules.
    SILENT_BY_DESIGN = {
        "accounting_export",
        # One row per staff account that subscribed a calendar client:
        # clinic, user, token, last access. No patient column and no
        # appointment copy — the feed renders what the agenda holds at
        # the moment it is polled, so an erasure there is immediately
        # reflected in what the subscription serves.
        "calendar_feed",
        "cashbox",
        "catalog",
        # Settlements with professionals. No patient column; `lines` is a
        # frozen per-treatment snapshot (treatment id, session label,
        # amounts) of what an associate was paid on. The patient's side of
        # that money is exported and retained by `payments`
        # (PatientEarnedEntry). Pinned by
        # test_liquidations_stays_free_of_patient_data.
        "liquidations",
        "professionals",
        "reports",
        "schedules",
        "whatsapp_kapso",
        # KNOWN GAP, not a decision. Copilot transcripts hold patient
        # names in cleartext, but a conversation's ``context`` blob is
        # client-supplied with no guaranteed shape, so there is no
        # reliable way to find the conversations about one patient. A
        # best-effort JSONB match would look like coverage while missing
        # rows, which is worse than an honest gap. See ADR 0026.
        "copilot",
    }

    def test_every_other_module_contributes(self) -> None:
        from app.core.plugins.loader import discover_and_register
        from app.core.plugins.registry import module_registry

        discover_and_register()
        silent = {
            module.name
            for module in module_registry.list_discovered()
            if not module.get_subject_contributors()
        }
        unexpected = silent - self.SILENT_BY_DESIGN
        assert not unexpected, (
            "These modules contribute nothing to a subject request, so their data "
            "survives an erasure and is missing from an export. Implement "
            "get_subject_contributors(), or add them to SILENT_BY_DESIGN with a "
            f"reason: {sorted(unexpected)}"
        )

    def test_liquidations_stays_free_of_patient_data(self) -> None:
        # `liquidations` is silent only because neither its tables nor the
        # frozen `lines` snapshot name a patient. The day either does, it
        # needs a privacy.py that exports those lines and states a
        # retention_reason — settled figures must not be rewritten.
        from app.modules.liquidations.models import Liquidation, ProfessionalCommission
        from app.modules.liquidations.schemas import LiquidationLine

        columns = {
            column.name
            for model in (Liquidation, ProfessionalCommission)
            for column in model.__table__.columns
        }
        assert not {name for name in columns if "patient" in name}
        assert set(LiquidationLine.model_fields) == {
            "treatment_id",
            "description",
            "performed_at",
            "earned",
            "collected",
        }

    def test_silence_list_has_no_stale_entries(self) -> None:
        from app.core.plugins.loader import discover_and_register
        from app.core.plugins.registry import module_registry

        discover_and_register()
        silent = {
            module.name
            for module in module_registry.list_discovered()
            if not module.get_subject_contributors()
        }
        stale = self.SILENT_BY_DESIGN - silent
        assert not stale, f"SILENT_BY_DESIGN entries that now contribute: {sorted(stale)}"

    def test_every_contributor_declares_its_erasability(self) -> None:
        from app.core.plugins.loader import discover_and_register
        from app.core.plugins.registry import module_registry

        discover_and_register()
        for module in module_registry.list_discovered():
            for contributor in module.get_subject_contributors():
                assert contributor.erasable or contributor.retention_reason, (
                    module.name,
                    contributor.name,
                )


async def _noop_export(db, clinic_id, patient_id):  # noqa: ARG001
    return []


async def _noop_anonymize(db, clinic_id, patient_id):  # noqa: ARG001
    return 0


async def _bootstrap(db_session, *, with_invoice: bool = True):
    clinic = Clinic(id=uuid4(), name="C", tax_id="B1", account_tier="clinic")
    author = User(
        id=uuid4(),
        email=f"admin-{uuid4().hex[:8]}@test.local",
        password_hash="x",
        first_name="A",
        last_name="A",
    )
    db_session.add_all([clinic, author])
    await db_session.flush()

    patient = Patient(
        clinic_id=clinic.id,
        first_name="Ana",
        last_name="García",
        phone="5512345678",
        email="ana@example.com",
        national_id="GOMA850101HDFNRL09",
        national_id_type="curp",
        date_of_birth=date(1985, 1, 1),
        billing_name="Ana García",
        billing_tax_id="GOMA850101AB1",
    )
    db_session.add(patient)
    await db_session.flush()

    db_session.add_all(
        [
            Allergy(clinic_id=clinic.id, patient_id=patient.id, name="Penicilina"),
            LegalGuardian(
                clinic_id=clinic.id,
                patient_id=patient.id,
                name="Luis García",
                relationship="padre",
                dni="12345678Z",
                phone="5511112222",
            ),
        ]
    )
    if with_invoice:
        db_session.add(
            Invoice(
                clinic_id=clinic.id,
                patient_id=patient.id,
                billing_name="Ana García",
                billing_tax_id="GOMA850101AB1",
                total=Decimal("100.00"),
                created_by=author.id,
            )
        )
    await db_session.flush()
    return clinic, patient
