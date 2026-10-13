"""The clinical record is composed from the modules, not stored.

Phase 1 of `docs/features/expediente-clinico.md`. What these pin is the
property the whole design rests on: the record owns no clinical data, so it
cannot drift from the source — and the contract that makes that possible,
`get_record_sections()`, behaves like its sibling `get_subject_contributors()`
without being it.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.core.record import EntryStatus, RecordSection, SectionCategory
from app.modules.clinical_notes.models import ClinicalNote
from app.modules.media.models import Document
from app.modules.odontogram.models import Treatment
from app.modules.patients_clinical.service import PatientsClinicalService
from app.modules.periodontogram.models import PeriodontogramSnapshot
from app.modules.record.service import RecordService


async def _bootstrap(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict[str, str]
) -> dict:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]

    clinic = Clinic(
        id=uuid4(),
        name="Record Clinic",
        tax_id="B66666666",
        address={"street": "x", "city": "y"},
        settings={},
        account_tier="clinic",
    )
    db_session.add(clinic)
    await db_session.flush()
    db_session.add(ClinicMembership(id=uuid4(), user_id=user_id, clinic_id=clinic.id, role="admin"))
    await db_session.commit()

    patient = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "Ana", "last_name": "García", "phone": "+34699111222"},
    )
    return {
        "clinic_id": clinic.id,
        "patient_id": UUID(patient.json()["data"]["id"]),
        "user_id": UUID(user_id),
    }


class TestTheContract:
    def test_a_section_must_say_where_its_title_comes_from(self) -> None:
        """A record is read in one language and exported in another.

        A Spanish literal baked into a section would be wrong in both places
        the moment either changes, so the key is required rather than
        encouraged.
        """
        with pytest.raises(ValueError, match="title_key"):
            RecordSection(
                name="allergies",
                title_key="",
                category=SectionCategory.ANTECEDENTS,
                collect=lambda db, c, p: [],
            )

    def test_a_section_must_be_named(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            RecordSection(
                name="",
                title_key="record.section.x",
                category=SectionCategory.ANTECEDENTS,
                collect=lambda db, c, p: [],
            )


@pytest.mark.asyncio
class TestComposition:
    async def test_the_record_is_built_from_the_modules_that_own_the_data(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        """No table of its own: the allergy is read where the allergy lives."""
        seed = await _bootstrap(db_session, client, auth_headers)
        await PatientsClinicalService.create_allergy(
            db_session,
            seed["clinic_id"],
            seed["patient_id"],
            {"name": "Penicilina", "severity": "critical"},
            user_id=seed["user_id"],
        )
        await db_session.commit()

        record = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        assert record is not None

        by_name = {section.qualified_name: section for section in record.sections}
        assert "patients_clinical.allergies" in by_name
        entries = by_name["patients_clinical.allergies"].entries
        assert [entry.summary for entry in entries] == ["Penicilina"]
        assert entries[0].source_table == "patients_clinical_allergy"
        assert entries[0].recorded_by_user_id == seed["user_id"]

    async def test_empty_sections_still_come_back(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        """ "This module holds nothing" is an answer; a missing section is not.

        A reader of a record has to be able to tell the difference between a
        patient with no known allergies and a record that never asked.
        """
        seed = await _bootstrap(db_session, client, auth_headers)

        record = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        assert record is not None
        names = {section.qualified_name for section in record.sections}
        assert "patients_clinical.allergies" in names
        # Who the record is about is the one thing every patient has.
        assert all(
            section.entries == []
            for section in record.sections
            if section.qualified_name != "patients.identification"
        )

    async def test_the_record_reads_in_the_order_of_a_paper_expediente(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        """Every part of the chart contributes its section, in reading order."""
        seed = await _bootstrap(db_session, client, auth_headers)

        record = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        assert record is not None
        assert [section.qualified_name for section in record.sections] == [
            "patients.identification",
            "patients_clinical.health_questionnaires",
            "patients_clinical.asa_assessments",
            "patients_clinical.family_history",
            "patients_clinical.medical_context",
            "patients_clinical.allergies",
            "patients_clinical.medications",
            "patients_clinical.systemic_diseases",
            "patients_clinical.surgical_history",
            "odontogram.chart",
            "periodontogram.chartings",
            "clinical_notes.notes",
            "treatment_plan.plans",
            "treatment_plan.prescriptions",
            "media.imaging",
            "consents.consents",
            "record.disclosures",
        ]
        [identity] = record.sections[0].entries
        assert identity.summary == "Ana García"
        # A record is not a financial document.
        assert not any(key.startswith("billing") for key in identity.detail)

    async def test_the_chart_the_notes_and_the_images_are_in_the_record(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        seed = await _bootstrap(db_session, client, auth_headers)
        clinic_id, patient_id, user_id = seed["clinic_id"], seed["patient_id"], seed["user_id"]
        now = datetime.now(UTC)
        treatment = Treatment(
            clinic_id=clinic_id,
            patient_id=patient_id,
            clinical_type="caries",
            status="performed",
            recorded_at=now,
            performed_at=datetime(2024, 5, 2, tzinfo=UTC),
            performed_by=user_id,
        )
        db_session.add(treatment)
        await db_session.flush()

        def note(note_type: str, owner_type: str, owner_id: UUID, body: str) -> ClinicalNote:
            return ClinicalNote(
                clinic_id=clinic_id,
                note_type=note_type,
                owner_type=owner_type,
                owner_id=owner_id,
                body=body,
                author_id=user_id,
            )

        def document(kind: str, title: str) -> Document:
            return Document(
                clinic_id=clinic_id,
                patient_id=patient_id,
                document_type="other",
                title=title,
                original_filename=f"{title}.jpg",
                storage_path=f"test/{uuid4()}.jpg",
                mime_type="image/jpeg",
                file_size=1,
                media_kind=kind,
                uploaded_by=user_id,
            )

        db_session.add_all(
            [
                note("diagnosis", "patient", patient_id, "Caries en 16"),
                # A note left on a treatment belongs to the same patient.
                note("treatment", "treatment", treatment.id, "Obturada sin incidencias"),
                # Running the clinic is not the chart.
                note("administrative", "patient", patient_id, "Prefiere las mañanas"),
                document("xray", "Panorámica"),
                document("document", "INE"),
                PeriodontogramSnapshot(
                    clinic_id=clinic_id,
                    patient_id=patient_id,
                    status="closed",
                    recorded_at=now,
                    recorded_by=user_id,
                    closed_at=now,
                    closed_by=user_id,
                    indices={"bop_pct": 12.5},
                ),
            ]
        )
        await db_session.commit()

        record = await RecordService.compose(db_session, clinic_id, patient_id)
        assert record is not None
        by_name = {section.qualified_name: section.entries for section in record.sections}

        [charted] = by_name["odontogram.chart"]
        # Clinical time: when it was done, not when it was typed in.
        assert charted.occurred_at.year == 2024
        assert {entry.summary for entry in by_name["clinical_notes.notes"]} == {
            "Caries en 16",
            "Obturada sin incidencias",
        }
        assert [entry.summary for entry in by_name["media.imaging"]] == ["Panorámica"]
        [charting] = by_name["periodontogram.chartings"]
        assert charting.detail["bop_pct"] == 12.5

    async def test_retracted_entries_are_left_out_unless_asked_for(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        """Never deleted, not handed over by default.

        An entry that should never have been recorded is not part of what a
        colleague receives — but "what did the chart say that day" has to stay
        answerable, so it is one explicit flag away (ADR 0032).
        """
        seed = await _bootstrap(db_session, client, auth_headers)
        allergy = await PatientsClinicalService.create_allergy(
            db_session,
            seed["clinic_id"],
            seed["patient_id"],
            {"name": "Paciente equivocado", "severity": "high"},
            user_id=seed["user_id"],
        )
        await PatientsClinicalService.retract_entry(db_session, allergy, reason="wrong patient")
        await db_session.commit()

        default = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        allergies = next(
            s for s in default.sections if s.qualified_name == "patients_clinical.allergies"
        )
        assert allergies.entries == []

        full = await RecordService.compose(
            db_session, seed["clinic_id"], seed["patient_id"], include_retracted=True
        )
        allergies = next(
            s for s in full.sections if s.qualified_name == "patients_clinical.allergies"
        )
        assert [e.status for e in allergies.entries] == [EntryStatus.RETRACTED]

    async def test_a_discontinued_entry_stays_in_the_record(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        """ "No longer true" is part of the history a colleague reads."""
        seed = await _bootstrap(db_session, client, auth_headers)
        med = await PatientsClinicalService.create_medication(
            db_session,
            seed["clinic_id"],
            seed["patient_id"],
            {"name": "Sintrom"},
            user_id=seed["user_id"],
        )
        med.ended_at = datetime.now(UTC)
        await db_session.commit()

        record = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        meds = next(
            s for s in record.sections if s.qualified_name == "patients_clinical.medications"
        )
        assert [(e.summary, e.status) for e in meds.entries] == [("Sintrom", EntryStatus.ENDED)]

    async def test_entries_sort_by_clinical_time_not_by_when_they_were_typed(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        """A surgery recorded today that happened in 2019 sorts into 2019.

        Getting this wrong turns a record into a data-entry log, which is not
        what a colleague is reading it for.
        """
        seed = await _bootstrap(db_session, client, auth_headers)
        for name, year in (("Reciente", 2024), ("Antigua", 2019)):
            await PatientsClinicalService.create_surgical_history(
                db_session,
                seed["clinic_id"],
                seed["patient_id"],
                {"procedure": name, "surgery_date": datetime(year, 5, 1).date()},
                user_id=seed["user_id"],
            )
        await db_session.commit()

        record = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        surgeries = next(
            s for s in record.sections if s.qualified_name == "patients_clinical.surgical_history"
        )
        assert [e.summary for e in surgeries.entries] == ["Antigua", "Reciente"]

    async def test_a_patient_of_another_clinic_has_no_record_here(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        seed = await _bootstrap(db_session, client, auth_headers)
        assert await RecordService.compose(db_session, uuid4(), seed["patient_id"]) is None


@pytest.mark.asyncio
async def test_billing_contributes_nothing_to_a_clinical_record(
    db_session: AsyncSession,
) -> None:
    """A referral is not a financial document.

    The fiscal modules answer the subject-rights question — it is the
    patient's data — and stay out of the clinical one. A disclosure carrying
    invoice data is a privacy defect, not a feature.
    """
    from app.core.plugins.registry import module_registry

    financial = {"billing", "payments", "verifactu", "accounting_export", "cashbox"}
    for module in module_registry.list_modules():
        if module.name in financial:
            assert module.get_record_sections() == [], module.name


@pytest.mark.asyncio
class TestCoverage:
    """What a dental record is expected to hold, checked against one."""

    async def test_a_bare_record_says_what_is_missing(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        seed = await _bootstrap(db_session, client, auth_headers)

        record = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        assert record is not None
        coverage = {item.key: item for item in record.coverage}

        assert list(coverage) == [
            "identification",
            "chief_complaint",
            "family_history",
            "personal_history",
            "dental_chart",
            "diagnosis",
            "prognosis",
            "therapeutic_plan",
            "evolution_notes",
            "informed_consent",
        ]
        assert not any(item.met for item in coverage.values())
        # A name is not an identification: the record says which fields lack.
        assert coverage["identification"].missing == ["date_of_birth", "gender", "address"]

    async def test_what_is_written_down_counts(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        seed = await _bootstrap(db_session, client, auth_headers)
        patient_id = seed["patient_id"]

        saved = await client.put(
            f"/api/v1/patients_clinical/patients/{patient_id}/medical-history",
            headers=auth_headers,
            json={
                "family_history": [{"condition": "Diabetes tipo 2", "relative": "mother"}],
                "allergies": [{"name": "Penicilina", "severity": "high"}],
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["family_history"][0]["relative"] == "mother"

        plan = await client.post(
            "/api/v1/treatment_plan/treatment-plans",
            headers=auth_headers,
            json={
                "patient_id": str(patient_id),
                "diagnosis_notes": "Caries en 16",
                "prognosis": "reserved",
                "prognosis_notes": "Higiene deficiente",
            },
        )
        assert plan.status_code == 201, plan.text

        record = await RecordService.compose(db_session, seed["clinic_id"], patient_id)
        assert record is not None
        met = {item.key for item in record.coverage if item.met}
        assert met == {
            "family_history",
            "personal_history",
            "diagnosis",
            "prognosis",
            "therapeutic_plan",
        }
        by_name = {section.qualified_name: section.entries for section in record.sections}
        [relative] = by_name["patients_clinical.family_history"]
        assert relative.summary == "Diabetes tipo 2" and relative.detail["relative"] == "mother"
        [charted] = by_name["treatment_plan.plans"]
        assert charted.detail["prognosis"] == "reserved"

        # A judgement written when the plan was drafted is refined later.
        plan_id = plan.json()["data"]["id"]
        edited = await client.put(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
            headers=auth_headers,
            json={
                "prognosis": "favorable",
                "diagnosis_notes": "Caries en 16, sin afectación pulpar",
            },
        )
        assert edited.status_code == 200, edited.text
        again = await RecordService.compose(db_session, seed["clinic_id"], patient_id)
        assert again is not None
        [charted] = next(
            s.entries for s in again.sections if s.qualified_name == "treatment_plan.plans"
        )
        assert charted.detail["prognosis"] == "favorable"

    async def test_a_family_entry_dropped_from_the_form_is_retracted_not_deleted(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        seed = await _bootstrap(db_session, client, auth_headers)
        url = f"/api/v1/patients_clinical/patients/{seed['patient_id']}/medical-history"
        await client.put(
            url,
            headers=auth_headers,
            json={"family_history": [{"condition": "Hipertensión", "relative": "father"}]},
        )
        await client.put(url, headers=auth_headers, json={"family_history": []})

        default = await RecordService.compose(db_session, seed["clinic_id"], seed["patient_id"])
        full = await RecordService.compose(
            db_session, seed["clinic_id"], seed["patient_id"], include_retracted=True
        )
        assert default is not None and full is not None

        def family(record) -> list:
            return next(
                s.entries
                for s in record.sections
                if s.qualified_name == "patients_clinical.family_history"
            )

        assert family(default) == []
        assert [entry.status for entry in family(full)] == [EntryStatus.RETRACTED]
        # A fact taken back does not satisfy anything.
        assert not next(i for i in full.coverage if i.key == "family_history").met
