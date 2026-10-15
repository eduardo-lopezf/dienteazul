"""A clinic exported to a ``.dpm`` file, and read back.

What these pin: the file opens with the importer's own reader, its
integrity hash holds, it cannot be opened without the passphrase, it only
carries the exporting clinic's rows, and importing it into another clinic
brings the records back. Over HTTP: an administrator starts the export,
downloads the file and removes it; the passphrase is required and long.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.agenda.models import Appointment, Cabinet
from app.modules.migration_import import service as import_service
from app.modules.migration_import.dpmf import open_dpmf
from app.modules.migration_import.dpmf.crypto import DpmeError
from app.modules.migration_import.export import write_clinic_export
from app.modules.migration_import.models import ImportJob, ImportWarning
from app.modules.patients.models import Patient
from app.modules.professionals.models import Professional
from app.modules.recalls.models import Recall

PASSPHRASE = "una contraseña bastante larga"
EXPORTS = "/api/v1/migration_import/exports"


async def _fill(db: AsyncSession, clinic: Clinic, patient: Patient) -> dict:
    professional = Professional(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Marta",
        last_name="Ruiz",
        professional_type="dentist",
        is_active=True,
    )
    db.add(professional)
    cabinet = (await db.execute(select(Cabinet).where(Cabinet.clinic_id == clinic.id))).scalar_one()
    start = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    appointment = Appointment(
        id=uuid4(),
        clinic_id=clinic.id,
        patient_id=patient.id,
        professional_id=professional.id,
        cabinet_id=cabinet.id,
        cabinet=cabinet.name,
        start_time=start,
        end_time=start + timedelta(minutes=45),
        status="scheduled",
    )
    recall = Recall(
        clinic_id=clinic.id,
        patient_id=patient.id,
        due_month=date(2027, 1, 1),
        reason="hygiene",
        reason_note="Limpieza semestral",
        priority="normal",
        status="pending",
    )
    db.add_all([appointment, recall])
    # Another clinic's patient, which must not travel.
    other = Clinic(id=uuid4(), name="Otra", tax_id="B99999999", account_tier="clinic")
    db.add(other)
    await db.flush()
    db.add(Patient(id=uuid4(), clinic_id=other.id, first_name="Ajena", last_name="X"))
    await db.commit()
    return {"appointment": appointment, "recall": recall, "other": other}


@pytest.mark.asyncio
async def test_the_file_reads_back_sealed_and_scoped(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient, tmp_path: Path
) -> None:
    await _fill(db_session, test_clinic, test_patient)
    target = tmp_path / "clinic.dpm"

    counts = await write_clinic_export(db_session, test_clinic.id, target, passphrase=PASSPHRASE)
    assert counts["patient"] == 1  # the other clinic's patient stays home
    assert counts["appointment"] == 1 and counts["recall"] == 1
    assert counts["catalog_item"] == 1 and counts["professional"] == 1

    with open_dpmf(target, passphrase=PASSPHRASE) as handle:
        assert handle.recompute_integrity_hash() == handle.declared_integrity_hash()
        assert handle.source_system() == "dienteazul"
        assert handle.meta["tenant_label"] == test_clinic.name
        rows = list(handle.entity_iter("patient"))
        assert '"given_name": "Test"' in rows[0][3]

    with pytest.raises(DpmeError):
        with open_dpmf(target, passphrase="no es la contraseña"):
            pass
    with pytest.raises(DpmeError):
        with open_dpmf(target):
            pass
    with pytest.raises(ValueError):
        await write_clinic_export(db_session, test_clinic.id, target, passphrase="corta")


@pytest.mark.asyncio
async def test_importing_the_file_brings_the_clinic_back(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    filled = await _fill(db_session, test_clinic, test_patient)
    target = tmp_path / "clinic.dpm"
    await write_clinic_export(db_session, test_clinic.id, target, passphrase=PASSPHRASE)

    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    job = ImportJob(
        id=uuid4(),
        clinic_id=filled["other"].id,
        created_by=me.json()["data"]["user"]["id"],
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    names = {
        (p.first_name, p.last_name)
        for p in (
            await db_session.execute(select(Patient).where(Patient.clinic_id == filled["other"].id))
        ).scalars()
    }
    assert ("Test", "Patient") in names
    recalls = (
        (await db_session.execute(select(Recall).where(Recall.clinic_id == filled["other"].id)))
        .scalars()
        .all()
    )
    assert [r.reason_note for r in recalls] == ["Limpieza semestral\nMotivo: hygiene"]
    cabinets = (
        (
            await db_session.execute(
                select(Cabinet.name).where(Cabinet.clinic_id == filled["other"].id)
            )
        )
        .scalars()
        .all()
    )
    assert "Gabinete 1" in cabinets
    appointments = (
        (
            await db_session.execute(
                select(Appointment).where(Appointment.clinic_id == filled["other"].id)
            )
        )
        .scalars()
        .all()
    )
    assert [(a.start_time, a.end_time - a.start_time, a.status) for a in appointments] == [
        (filled["appointment"].start_time, timedelta(minutes=45), "scheduled")
    ]


@pytest.mark.asyncio
async def test_an_admin_exports_downloads_and_removes_the_file(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic, test_patient: Patient
) -> None:
    short = await client.post(EXPORTS, headers=auth_headers, json={"passphrase": "corta"})
    assert short.status_code == 422

    started = await client.post(EXPORTS, headers=auth_headers, json={"passphrase": PASSPHRASE})
    assert started.status_code == 202, started.text
    export_id = started.json()["data"]["id"]

    done = (await client.get(f"{EXPORTS}/{export_id}", headers=auth_headers)).json()["data"]
    assert done["status"] == "completed", done
    assert done["entity_counts"]["patient"] == 1
    assert "passphrase" not in done

    file = await client.get(f"{EXPORTS}/{export_id}/download", headers=auth_headers)
    assert file.status_code == 200
    assert file.content[:4] == b"DPME"

    removed = await client.delete(f"{EXPORTS}/{export_id}/file", headers=auth_headers)
    assert removed.json()["data"]["status"] == "deleted"
    gone = await client.get(f"{EXPORTS}/{export_id}/download", headers=auth_headers)
    assert gone.status_code == 409
    listed = (await client.get(EXPORTS, headers=auth_headers)).json()["data"]
    assert [row["id"] for row in listed] == [export_id]


@pytest.mark.asyncio
async def test_the_medical_history_and_odontogram_travel_as_they_were(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    """Exported in Diente Azul's own shape and read back field by field —
    including what was ended or retracted, which the record keeps."""
    from app.modules.odontogram.models import ToothRecord, Treatment, TreatmentTooth
    from app.modules.patients_clinical.models import (
        Allergy,
        AsaAssessment,
        MedicalContext,
        Medication,
    )

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    # The dentist who performs the treatment: an account with its profile.
    db_session.add(
        Professional(
            id=uuid4(),
            clinic_id=clinic,
            user_id=user_id,
            first_name="Test",
            last_name="Dentist",
            professional_type="dentist",
            is_active=True,
        )
    )
    db_session.add_all(
        [
            Allergy(
                clinic_id=clinic,
                patient_id=patient,
                name="Penicilina",
                severity="high",
                reaction="Urticaria",
            ),
            Allergy(
                clinic_id=clinic,
                patient_id=patient,
                name="Látex",
                severity="low",
                retracted_at=datetime(2026, 1, 2, tzinfo=UTC),
                retraction_reason="Otro paciente",
            ),
            Medication(
                clinic_id=clinic,
                patient_id=patient,
                name="Enalapril",
                dosage="10 mg",
                start_date=date(2024, 3, 1),
                ended_at=datetime(2025, 6, 1, tzinfo=UTC),
            ),
            MedicalContext(clinic_id=clinic, patient_id=patient, is_smoker=True, bruxism=True),
            AsaAssessment(
                clinic_id=clinic,
                patient_id=patient,
                asa_class=2,
                assessed_at=datetime(2026, 2, 3, tzinfo=UTC),
                rationale="HTA controlada",
            ),
        ]
    )
    tooth = ToothRecord(
        clinic_id=clinic,
        patient_id=patient,
        tooth_number=16,
        tooth_type="permanent",
        general_condition="filled",
        surfaces={"O": "filled"},
    )
    db_session.add(tooth)
    await db_session.flush()
    treatment = Treatment(
        clinic_id=clinic,
        patient_id=patient,
        clinical_type="filling_composite",
        scope="tooth",
        status="performed",
        recorded_at=datetime(2026, 2, 3, 9, 0, tzinfo=UTC),
        performed_at=datetime(2026, 2, 3, 9, 30, tzinfo=UTC),
        performed_by=user_id,
        price_snapshot=Decimal("850.00"),
        notes="Resina A2",
        source_module="odontogram",
    )
    db_session.add(treatment)
    await db_session.flush()
    db_session.add(
        TreatmentTooth(
            treatment_id=treatment.id,
            tooth_record_id=tooth.id,
            tooth_number=16,
            surfaces=["O", "M"],
        )
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["allergy"] == 2 and counts["medication"] == 1
    assert counts["medical_context"] == 1 and counts["asa_assessment"] == 1
    assert counts["tooth_record"] == 1 and counts["clinical_treatment"] == 1

    other = filled["other"].id
    job = ImportJob(
        id=uuid4(),
        clinic_id=other,
        created_by=user_id,
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    async def rows(model):
        return (
            (await db_session.execute(select(model).where(model.clinic_id == other)))
            .scalars()
            .all()
        )

    allergies = {a.name: a for a in await rows(Allergy)}
    assert (
        allergies["Penicilina"].reaction == "Urticaria"
        and allergies["Penicilina"].severity == "high"
    )
    assert allergies["Látex"].retracted_at is not None
    assert allergies["Látex"].retraction_reason == "Otro paciente"
    (medication,) = await rows(Medication)
    assert medication.start_date == date(2024, 3, 1) and medication.ended_at is not None
    (context,) = await rows(MedicalContext)
    assert context.is_smoker and context.bruxism
    (asa,) = await rows(AsaAssessment)
    assert asa.asa_class == 2 and asa.rationale == "HTA controlada"

    (moved,) = await rows(Treatment)
    assert (moved.clinical_type, moved.status, moved.price_snapshot, moved.notes) == (
        "filling_composite",
        "performed",
        Decimal("850.00"),
        "Resina A2",
    )
    assert moved.performed_at == datetime(2026, 2, 3, 9, 30, tzinfo=UTC)
    assert moved.performed_by is not None
    teeth = (
        (
            await db_session.execute(
                select(TreatmentTooth).where(TreatmentTooth.treatment_id == moved.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(t.tooth_number, t.surfaces) for t in teeth] == [(16, ["O", "M"])]
    (record,) = await rows(ToothRecord)
    assert (record.general_condition, record.surfaces) == ("filled", {"O": "filled"})


@pytest.mark.asyncio
async def test_budgets_payments_and_the_account_travel_as_they_were(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    """A budget with its line, its signature and the treatment it covers;
    a payment allocated to it and partly refunded; the account's charge."""
    from app.modules.budget.models import Budget, BudgetItem, BudgetSignature
    from app.modules.odontogram.models import Treatment
    from app.modules.payments.models import (
        PatientEarnedEntry,
        Payment,
        PaymentAllocation,
        Refund,
    )
    from tests.test_treatment_plan import _seed_catalog_crown

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    crown_id = await _seed_catalog_crown(db_session, clinic)

    treatment = Treatment(
        clinic_id=clinic,
        patient_id=patient,
        clinical_type="crown",
        scope="tooth",
        status="performed",
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
        performed_at=datetime(2026, 3, 1, tzinfo=UTC),
        catalog_item_id=crown_id,
        source_module="odontogram",
    )
    db_session.add(treatment)
    await db_session.flush()
    budget = Budget(
        clinic_id=clinic,
        patient_id=patient,
        budget_number="PRES-2026-0001",
        version=1,
        status="accepted",
        valid_from=date(2026, 2, 1),
        created_by=user_id,
        subtotal=Decimal("500.00"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("500.00"),
        accepted_via="in_clinic",
    )
    db_session.add(budget)
    await db_session.flush()
    db_session.add_all(
        [
            BudgetItem(
                clinic_id=clinic,
                budget_id=budget.id,
                catalog_item_id=crown_id,
                unit_price=Decimal("500.00"),
                quantity=1,
                vat_rate=0.0,
                line_subtotal=Decimal("500.00"),
                line_discount=Decimal("0"),
                line_tax=Decimal("0"),
                line_total=Decimal("500.00"),
                tooth_number=16,
                treatment_id=treatment.id,
            ),
            BudgetSignature(
                clinic_id=clinic,
                budget_id=budget.id,
                signature_type="full_acceptance",
                signed_by_name="Test Patient",
                relationship_to_patient="patient",
                signature_method="drawn",
                signed_at=datetime(2026, 2, 2, tzinfo=UTC),
            ),
        ]
    )
    payment = Payment(
        clinic_id=clinic,
        patient_id=patient,
        amount=Decimal("300.00"),
        currency="EUR",
        method="card",
        payment_date=date(2026, 2, 5),
        recorded_by=user_id,
    )
    db_session.add(payment)
    await db_session.flush()
    db_session.add_all(
        [
            PaymentAllocation(
                clinic_id=clinic,
                payment_id=payment.id,
                target_type="budget",
                budget_id=budget.id,
                amount=Decimal("300.00"),
                created_by=user_id,
            ),
            Refund(
                clinic_id=clinic,
                payment_id=payment.id,
                amount=Decimal("50.00"),
                method="card",
                reason_code="other",
                reason_note="Ajuste",
                refunded_at=datetime(2026, 2, 6, tzinfo=UTC),
                refunded_by=user_id,
            ),
            PatientEarnedEntry(
                clinic_id=clinic,
                patient_id=patient,
                treatment_id=treatment.id,
                catalog_item_id=crown_id,
                source_session_id=uuid4(),
                amount=Decimal("500.00"),
                performed_at=datetime(2026, 3, 1, tzinfo=UTC),
                source_event="test",
                description="Corona 16",
            ),
        ]
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["treatment_budget"] == 1
    assert counts["patient_payment"] == 1 and counts["earned_entry"] == 1

    other = filled["other"].id
    # The catalogue the budget prices: the target clinic has the same item.
    other_crown = await _seed_catalog_crown(db_session, other)
    job = ImportJob(
        id=uuid4(),
        clinic_id=other,
        created_by=user_id,
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    async def rows(model):
        return (
            (await db_session.execute(select(model).where(model.clinic_id == other)))
            .scalars()
            .all()
        )

    (moved_budget,) = await rows(Budget)
    assert (moved_budget.budget_number, moved_budget.status, moved_budget.total) == (
        "PRES-2026-0001",
        "accepted",
        Decimal("500.00"),
    )
    (line,) = await rows(BudgetItem)
    assert str(line.catalog_item_id) == str(other_crown)
    assert line.tooth_number == 16 and line.line_total == Decimal("500.00")
    (moved_treatment,) = await rows(Treatment)
    assert line.treatment_id == moved_treatment.id
    assert moved_treatment.budget_item_id == line.id  # and back, as in the source
    (signature,) = await rows(BudgetSignature)
    assert signature.signed_by_name == "Test Patient"

    (moved_payment,) = await rows(Payment)
    assert (moved_payment.amount, moved_payment.method) == (Decimal("300.00"), "card")
    (share,) = await rows(PaymentAllocation)
    assert (share.target_type, share.budget_id) == ("budget", moved_budget.id)
    (refund,) = await rows(Refund)
    assert refund.amount == Decimal("50.00") and refund.reason_note == "Ajuste"
    (charge,) = await rows(PatientEarnedEntry)
    assert (charge.amount, charge.treatment_id, charge.description) == (
        Decimal("500.00"),
        moved_treatment.id,
        "Corona 16",
    )


@pytest.mark.asyncio
async def test_plans_and_invoices_travel_as_they_were(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    """A plan with its treatment, phase and sessions, tied to its budget; an
    invoice billing the budget line, with the payment applied and a credit
    note — historical, its fiscal fingerprint left out without opt-in."""
    from app.modules.billing.models import Invoice, InvoiceItem, InvoicePayment
    from app.modules.budget.models import Budget, BudgetItem
    from app.modules.odontogram.models import Treatment
    from app.modules.payments.models import Payment
    from app.modules.treatment_plan.models import (
        PlannedTreatmentItem,
        PlannedTreatmentItemSession,
        TreatmentPlan,
    )
    from tests.test_treatment_plan import _seed_catalog_crown

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    crown_id = await _seed_catalog_crown(db_session, clinic)

    treatment = Treatment(
        clinic_id=clinic,
        patient_id=patient,
        clinical_type="crown",
        scope="tooth",
        status="performed",
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
        catalog_item_id=crown_id,
        source_module="treatment_plan",
    )
    budget = Budget(
        clinic_id=clinic,
        patient_id=patient,
        budget_number="PRES-2026-0002",
        status="accepted",
        valid_from=date(2026, 2, 1),
        created_by=user_id,
        subtotal=Decimal("500"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("500"),
    )
    db_session.add_all([treatment, budget])
    await db_session.flush()
    line = BudgetItem(
        clinic_id=clinic,
        budget_id=budget.id,
        catalog_item_id=crown_id,
        unit_price=Decimal("500"),
        quantity=1,
        vat_rate=0.0,
        line_subtotal=Decimal("500"),
        line_discount=Decimal("0"),
        line_tax=Decimal("0"),
        line_total=Decimal("500"),
        treatment_id=treatment.id,
        invoiced_quantity=1,
    )
    plan = TreatmentPlan(
        clinic_id=clinic,
        patient_id=patient,
        plan_number="PLAN-0007",
        title="Rehabilitación",
        status="active",
        budget_id=budget.id,
        created_by=user_id,
        confirmed_at=datetime(2026, 2, 2, tzinfo=UTC),
        diagnosis_notes="Fractura 16",
    )
    payment = Payment(
        clinic_id=clinic,
        patient_id=patient,
        amount=Decimal("500"),
        currency="EUR",
        method="cash",
        payment_date=date(2026, 3, 2),
        recorded_by=user_id,
    )
    db_session.add_all([line, plan, payment])
    await db_session.flush()
    item = PlannedTreatmentItem(
        clinic_id=clinic,
        treatment_plan_id=plan.id,
        treatment_id=treatment.id,
        phase="rehabilitacion",
        sequence_order=1,
        status="completed",
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
        completed_by=user_id,
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            PlannedTreatmentItemSession(
                plan_item_id=item.id,
                sequence=1,
                label="Tallado",
                amount=Decimal("200"),
                status="completed",
                completed_at=datetime(2026, 2, 20, tzinfo=UTC),
            ),
            PlannedTreatmentItemSession(
                plan_item_id=item.id,
                sequence=2,
                label="Cementado",
                amount=Decimal("300"),
                status="completed",
            ),
        ]
    )
    invoice = Invoice(
        clinic_id=clinic,
        patient_id=patient,
        invoice_number="F-2026-0001",
        status="paid",
        issue_date=date(2026, 3, 2),
        budget_id=budget.id,
        subtotal=Decimal("500"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("500"),
        created_by=user_id,
        document_hash="abc123",
        billing_name="Test Patient",
    )
    db_session.add(invoice)
    await db_session.flush()
    credit = Invoice(
        clinic_id=clinic,
        patient_id=patient,
        invoice_number="R-2026-0001",
        status="issued",
        issue_date=date(2026, 3, 3),
        credit_note_for_id=invoice.id,
        subtotal=Decimal("-50"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("-50"),
        created_by=user_id,
    )
    db_session.add_all(
        [
            credit,
            InvoiceItem(
                clinic_id=clinic,
                invoice_id=invoice.id,
                budget_item_id=line.id,
                catalog_item_id=crown_id,
                description="Corona 16",
                unit_price=Decimal("500"),
                quantity=1,
                vat_rate=0.0,
                line_subtotal=Decimal("500"),
                line_discount=Decimal("0"),
                line_tax=Decimal("0"),
                line_total=Decimal("500"),
            ),
            InvoicePayment(
                clinic_id=clinic,
                invoice_id=invoice.id,
                payment_id=payment.id,
                amount=Decimal("500"),
                created_by=user_id,
            ),
        ]
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["treatment_plan"] == 1 and counts["patient_invoice"] == 2

    other = filled["other"].id
    other_crown = await _seed_catalog_crown(db_session, other)
    job = ImportJob(
        id=uuid4(),
        clinic_id=other,
        created_by=user_id,
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    async def rows(model, *where):
        clause = [model.clinic_id == other, *where] if hasattr(model, "clinic_id") else list(where)
        return (await db_session.execute(select(model).where(*clause))).scalars().all()

    (moved_plan,) = await rows(TreatmentPlan)
    (moved_budget,) = await rows(Budget)
    (moved_treatment,) = await rows(Treatment)
    assert (moved_plan.plan_number, moved_plan.status, moved_plan.title) == (
        "PLAN-0007",
        "active",
        "Rehabilitación",
    )
    assert moved_plan.budget_id == moved_budget.id
    assert moved_plan.diagnosis_notes == "Fractura 16"
    (moved_item,) = await rows(PlannedTreatmentItem)
    assert (moved_item.treatment_id, moved_item.phase, moved_item.status) == (
        moved_treatment.id,
        "rehabilitacion",
        "completed",
    )
    sessions = await rows(
        PlannedTreatmentItemSession, PlannedTreatmentItemSession.plan_item_id == moved_item.id
    )
    assert sorted((s.sequence, s.label, s.amount) for s in sessions) == [
        (1, "Tallado", Decimal("200.00")),
        (2, "Cementado", Decimal("300.00")),
    ]

    invoices = {i.invoice_number: i for i in await rows(Invoice)}
    original, note = invoices["F-2026-0001"], invoices["R-2026-0001"]
    assert (original.status, original.total, original.budget_id) == (
        "paid",
        Decimal("500.00"),
        moved_budget.id,
    )
    assert original.series_id is None and original.document_hash is None  # no opt-in
    assert note.credit_note_for_id == original.id
    (moved_line,) = await rows(BudgetItem)
    (invoice_line,) = await rows(InvoiceItem)
    assert invoice_line.budget_item_id == moved_line.id
    assert str(invoice_line.catalog_item_id) == str(other_crown)
    (applied,) = await rows(InvoicePayment)
    (moved_payment,) = await rows(Payment)
    assert (applied.invoice_id, applied.payment_id) == (original.id, moved_payment.id)
    warnings = (
        (await db_session.execute(select(ImportWarning).where(ImportWarning.job_id == job.id)))
        .scalars()
        .all()
    )
    assert "patient_invoice.fiscal_data_skipped" in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_notes_and_consents_travel_as_they_were(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    """Notes come back on what they were written about, with their amended
    bodies and the deleted ones; consents with their template, signature
    and revocation — and a paper signature says its scan did not come."""
    from app.modules.clinical_notes.models import ClinicalNote, ClinicalNoteVersion
    from app.modules.consents.models import Consent, ConsentTemplate
    from app.modules.odontogram.models import Treatment

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    treatment = Treatment(
        clinic_id=clinic,
        patient_id=patient,
        clinical_type="extraction",
        scope="tooth",
        status="performed",
        recorded_at=datetime(2026, 4, 1, tzinfo=UTC),
        source_module="odontogram",
    )
    db_session.add(treatment)
    await db_session.flush()
    amended = ClinicalNote(
        clinic_id=clinic,
        note_type="diagnosis",
        owner_type="patient",
        owner_id=patient,
        tooth_number=36,
        body="Caries profunda",
        author_id=user_id,
        version=2,
        amended_at=datetime(2026, 4, 2, tzinfo=UTC),
    )
    db_session.add_all(
        [
            amended,
            ClinicalNote(
                clinic_id=clinic,
                note_type="treatment",
                owner_type="treatment",
                owner_id=treatment.id,
                body="Sin complicaciones",
                author_id=user_id,
            ),
            ClinicalNote(
                clinic_id=clinic,
                note_type="appointment_clinical",
                owner_type="appointment",
                owner_id=filled["appointment"].id,
                body="Llegó con dolor",
                author_id=user_id,
            ),
            ClinicalNote(
                clinic_id=clinic,
                note_type="administrative",
                owner_type="patient",
                owner_id=patient,
                body="Nota equivocada",
                author_id=user_id,
                deleted_at=datetime(2026, 4, 3, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        ClinicalNoteVersion(
            clinic_id=clinic,
            note_id=amended.id,
            version=1,
            body="Caries",
            superseded_at=datetime(2026, 4, 2, tzinfo=UTC),
            superseded_by_user_id=user_id,
            amendment_reason="Precisión",
        )
    )
    template = ConsentTemplate(
        clinic_id=clinic, kind="informed", title="Extracción", body="Riesgos…", version=2
    )
    db_session.add(template)
    await db_session.flush()
    png = {"png": "data:image/png;base64,AAAA"}
    db_session.add_all(
        [
            Consent(
                clinic_id=clinic,
                patient_id=patient,
                kind="informed",
                status="signed",
                title="Extracción 36",
                body="Riesgos…",
                template_id=template.id,
                template_version=2,
                explained_by_name="Marta Ruiz",
                explained_by_license="CED-1",
                signed_at=datetime(2026, 4, 1, tzinfo=UTC),
                signed_by_name="Test Patient",
                signer_capacity="patient",
                signature_method="screen",
                signature_data=png,
                regulation="NOM-004",
            ),
            Consent(
                clinic_id=clinic,
                patient_id=patient,
                kind="data_use",
                status="revoked",
                title="Datos",
                body="…",
                signed_at=datetime(2026, 1, 1, tzinfo=UTC),
                signed_by_name="Test Patient",
                signer_capacity="patient",
                signature_method="screen",
                signature_data=png,
                revoked_at=datetime(2026, 3, 1, tzinfo=UTC),
                status_note="Lo pidió",
            ),
            Consent(
                clinic_id=clinic,
                patient_id=patient,
                kind="informed",
                status="signed",
                title="Papel",
                body="…",
                explained_by_name="Marta Ruiz",
                signed_at=datetime(2026, 2, 1, tzinfo=UTC),
                signed_by_name="Test Patient",
                signer_capacity="patient",
                signature_method="paper",
                signature_data={"document_id": str(uuid4())},
            ),
        ]
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["clinical_note"] == 4
    assert counts["consent_template"] == 1 and counts["patient_consent"] == 3

    other = filled["other"].id
    job = ImportJob(
        id=uuid4(),
        clinic_id=other,
        created_by=user_id,
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    async def rows(model):
        return (
            (await db_session.execute(select(model).where(model.clinic_id == other)))
            .scalars()
            .all()
        )

    notes = {n.body: n for n in await rows(ClinicalNote)}
    (moved_patient,) = [p for p in await rows(Patient) if p.first_name == "Test"]
    (moved_treatment,) = await rows(Treatment)
    (moved_appointment,) = await rows(Appointment)
    diagnosis = notes["Caries profunda"]
    assert (diagnosis.owner_id, diagnosis.tooth_number, diagnosis.version) == (
        moved_patient.id,
        36,
        2,
    )
    assert notes["Sin complicaciones"].owner_id == moved_treatment.id
    assert notes["Llegó con dolor"].owner_id == moved_appointment.id
    assert notes["Nota equivocada"].deleted_at is not None
    (old,) = await rows(ClinicalNoteVersion)
    assert (old.note_id, old.body, old.amendment_reason) == (diagnosis.id, "Caries", "Precisión")

    (moved_template,) = await rows(ConsentTemplate)
    consents = {c.title: c for c in await rows(Consent)}
    signed = consents["Extracción 36"]
    assert signed.template_id == moved_template.id and signed.template_version == 2
    assert (signed.explained_by_name, signed.explained_by_license, signed.regulation) == (
        "Marta Ruiz",
        "CED-1",
        "NOM-004",
    )
    assert signed.signature_data == png and signed.status == "signed"
    revoked = consents["Datos"]
    assert revoked.status == "revoked" and revoked.revoked_at is not None
    paper = consents["Papel"]
    assert paper.signature_method == "paper" and paper.signature_data is None
    codes = {
        w.code
        for w in (
            await db_session.execute(select(ImportWarning).where(ImportWarning.job_id == job.id))
        ).scalars()
    }
    assert "patient_consent.scan_not_carried" in codes


@pytest.mark.asyncio
async def test_documents_and_questionnaires_travel_with_their_files(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Files travel inside the ``.dpm`` and land through Media; a
    questionnaire and a consent signed on paper point at their scan as
    imported; a file that does not match its fingerprint is refused;
    without documents the scan is named as missing; past the size the
    envelope holds, the export says to leave documents out."""
    import json
    import sqlite3

    from app.modules.consents.models import Consent
    from app.modules.media.models import Document
    from app.modules.media.service import DocumentService
    from app.modules.migration_import import export as export_module
    from app.modules.migration_import.dpmf.compress import compress_to, decompress_to
    from app.modules.migration_import.dpmf.crypto import decrypt_to, encrypt_to
    from app.modules.patients_clinical.models import HealthQuestionnaire

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    pdf = b"%PDF-1.4 cuestionario firmado"
    scan = await DocumentService.create_document(
        db=db_session,
        clinic_id=clinic,
        patient_id=patient,
        user_id=user_id,
        file_data=pdf,
        original_filename="cuestionario.pdf",
        mime_type="application/pdf",
        document_type="consent",
        title="Cuestionario firmado",
    )
    db_session.add_all(
        [
            HealthQuestionnaire(
                clinic_id=clinic,
                patient_id=patient,
                taken_at=datetime(2026, 5, 1, tzinfo=UTC),
                form_version="1",
                answers={"hypertension": True},
                conditions=["diabetes"],
                scan_document_id=scan.id,
                regulation="NOM-004",
            ),
            Consent(
                clinic_id=clinic,
                patient_id=patient,
                kind="informed",
                status="signed",
                title="En papel",
                body="…",
                explained_by_name="Marta Ruiz",
                signed_at=datetime(2026, 5, 1, tzinfo=UTC),
                signed_by_name="Test Patient",
                signer_capacity="patient",
                signature_method="paper",
                signature_data={"document_id": str(scan.id)},
            ),
        ]
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["stored_document"] == 1 and counts["health_questionnaire"] == 1

    other = filled["other"].id

    async def run(path: Path, into: object = None) -> ImportJob:
        job = ImportJob(
            id=uuid4(),
            clinic_id=into or other,
            created_by=user_id,
            status="executing",
            original_filename=path.name,
            file_path=str(path),
        )
        db_session.add(job)
        await db_session.commit()
        await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)
        return job

    async def codes(job: ImportJob) -> set[str]:
        rows = await db_session.execute(select(ImportWarning).where(ImportWarning.job_id == job.id))
        return {w.code for w in rows.scalars()}

    # A file whose bytes were altered after the export is refused.
    altered = tmp_path / "altered.dpm"
    inner, plain = tmp_path / "inner.zst", tmp_path / "plain.sqlite"
    decrypt_to(target, inner, passphrase=PASSPHRASE)
    decompress_to(inner, plain)
    conn = sqlite3.connect(plain)
    conn.execute("UPDATE _blobs SET data = ?", (b"otra cosa",))
    conn.commit()
    conn.close()
    compress_to(plain, inner)
    encrypt_to(inner, altered, passphrase=PASSPHRASE)
    # Into a clinic of its own: what it did bring stays imported there.
    elsewhere = Clinic(id=uuid4(), name="Tercera", tax_id="B77777777", account_tier="clinic")
    db_session.add(elsewhere)
    await db_session.commit()
    refused = await run(altered, elsewhere.id)
    assert "stored_document.file_altered" in await codes(refused)
    assert (
        not (await db_session.execute(select(Document).where(Document.clinic_id == elsewhere.id)))
        .scalars()
        .all()
    )

    # The real file.
    await run(target)
    (moved,) = (
        (await db_session.execute(select(Document).where(Document.clinic_id == other)))
        .scalars()
        .all()
    )
    assert (moved.title, moved.mime_type, moved.document_type) == (
        "Cuestionario firmado",
        "application/pdf",
        "consent",
    )
    assert await DocumentService.download_document(moved) == pdf
    (questionnaire,) = (
        (
            await db_session.execute(
                select(HealthQuestionnaire).where(HealthQuestionnaire.clinic_id == other)
            )
        )
        .scalars()
        .all()
    )
    assert questionnaire.scan_document_id == moved.id
    assert questionnaire.answers == {"hypertension": True}
    assert questionnaire.regulation == "NOM-004"
    (letter,) = (
        (await db_session.execute(select(Consent).where(Consent.clinic_id == other)))
        .scalars()
        .all()
    )
    assert letter.signature_data == {"document_id": str(moved.id)}

    # Without documents: the scan is named as not carried.
    bare = tmp_path / "bare.dpm"
    counts = await write_clinic_export(
        db_session, clinic, bare, passphrase=PASSPHRASE, include_documents=False
    )
    assert "stored_document" not in counts
    with open_dpmf(bare, passphrase=PASSPHRASE) as handle:
        assert handle.meta["embedded_files"] == "0"
        assert any(w[3] == "left_out" for w in handle.warnings_iter())
        consent_row = next(handle.entity_iter("patient_consent"))
        assert json.loads(consent_row[3])["signature_data"] == {"document_id": str(scan.id)}

    # Past what one sealed file holds.
    monkeypatch.setattr(export_module, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(export_module.DocumentsTooLargeError):
        await write_clinic_export(db_session, clinic, tmp_path / "big.dpm", passphrase=PASSPHRASE)


@pytest.mark.asyncio
async def test_prescriptions_and_payment_plans_travel_as_they_were(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    """A prescription keeps the doctor block it was printed with and its plan
    line; a payment plan its budget and instalments; a collection contact
    the day it was made."""
    from app.modules.budget.models import Budget
    from app.modules.odontogram.models import Treatment
    from app.modules.payments.models import (
        CollectionContact,
        PaymentSchedule,
        PaymentScheduleInstalment,
    )
    from app.modules.treatment_plan.models import (
        PlannedTreatmentItem,
        TreatmentPlan,
        TreatmentPrescription,
    )

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    treatment = Treatment(
        clinic_id=clinic,
        patient_id=patient,
        clinical_type="extraction",
        scope="tooth",
        status="planned",
        recorded_at=datetime(2026, 6, 1, tzinfo=UTC),
        source_module="treatment_plan",
    )
    budget = Budget(
        clinic_id=clinic,
        patient_id=patient,
        budget_number="PRES-2026-0009",
        status="accepted",
        valid_from=date(2026, 6, 1),
        created_by=user_id,
        subtotal=Decimal("900"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("900"),
    )
    plan = TreatmentPlan(
        clinic_id=clinic,
        patient_id=patient,
        plan_number="PLAN-0009",
        status="active",
        created_by=user_id,
    )
    db_session.add_all([treatment, budget, plan])
    await db_session.flush()
    item = PlannedTreatmentItem(
        clinic_id=clinic, treatment_plan_id=plan.id, treatment_id=treatment.id, sequence_order=1
    )
    db_session.add(item)
    await db_session.flush()
    schedule = PaymentSchedule(
        clinic_id=clinic,
        patient_id=patient,
        budget_id=budget.id,
        status="active",
        notes="Tres pagos",
        created_by=user_id,
    )
    db_session.add(schedule)
    await db_session.flush()
    db_session.add_all(
        [
            TreatmentPrescription(
                clinic_id=clinic,
                patient_id=patient,
                plan_item_id=item.id,
                treatment_label="Extracción 38",
                professional_name="Dra. Marta Ruiz",
                professional_license="CED-1234",
                body="Amoxicilina 500 mg c/8 h, 7 días",
                issued_by=user_id,
            ),
            PaymentScheduleInstalment(
                clinic_id=clinic,
                schedule_id=schedule.id,
                sequence=1,
                label="Anticipo",
                due_date=date(2026, 6, 1),
                amount=Decimal("300"),
            ),
            PaymentScheduleInstalment(
                clinic_id=clinic,
                schedule_id=schedule.id,
                sequence=2,
                label="Resto",
                due_date=date(2026, 7, 1),
                amount=Decimal("600"),
            ),
            CollectionContact(
                clinic_id=clinic,
                patient_id=patient,
                channel="phone",
                note="No contesta",
                contacted_by=user_id,
                created_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["prescription_record"] == 1
    assert counts["payment_schedule"] == 1 and counts["collection_contact"] == 1

    other = filled["other"].id
    job = ImportJob(
        id=uuid4(),
        clinic_id=other,
        created_by=user_id,
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    async def rows(model):
        return (
            (await db_session.execute(select(model).where(model.clinic_id == other)))
            .scalars()
            .all()
        )

    (prescription,) = await rows(TreatmentPrescription)
    (moved_item,) = await rows(PlannedTreatmentItem)
    assert prescription.plan_item_id == moved_item.id
    assert (
        prescription.professional_name,
        prescription.professional_license,
        prescription.body,
    ) == (
        "Dra. Marta Ruiz",
        "CED-1234",
        "Amoxicilina 500 mg c/8 h, 7 días",
    )
    (moved_schedule,) = await rows(PaymentSchedule)
    (moved_budget,) = await rows(Budget)
    assert (moved_schedule.budget_id, moved_schedule.notes) == (moved_budget.id, "Tres pagos")
    instalments = sorted(await rows(PaymentScheduleInstalment), key=lambda i: i.sequence)
    assert [(i.label, i.due_date, i.amount) for i in instalments] == [
        ("Anticipo", date(2026, 6, 1), Decimal("300.00")),
        ("Resto", date(2026, 7, 1), Decimal("600.00")),
    ]
    (contact,) = await rows(CollectionContact)
    assert (contact.channel, contact.note, contact.created_at) == (
        "phone",
        "No contesta",
        datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_attachments_and_histories_travel_as_they_were(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    """A document comes back attached to the note and plan line it was; the
    change histories keep each action, moment and state — and their author
    when that author came along as a professional."""
    from app.modules.billing.models import Invoice, InvoiceHistory
    from app.modules.budget.models import Budget, BudgetHistory
    from app.modules.clinical_notes.models import ClinicalNote
    from app.modules.media.models import MediaAttachment
    from app.modules.media.service import DocumentService
    from app.modules.odontogram.models import Treatment
    from app.modules.treatment_plan.models import (
        PlannedTreatmentItem,
        TreatmentPlan,
        TreatmentPlanHistory,
    )

    filled = await _fill(db_session, test_clinic, test_patient)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    clinic, patient = test_clinic.id, test_patient.id
    # The account that makes the changes is a professional with a profile.
    db_session.add(
        Professional(
            id=uuid4(),
            clinic_id=clinic,
            user_id=user_id,
            first_name="Test",
            last_name="Dentist",
            professional_type="dentist",
            is_active=True,
        )
    )
    treatment = Treatment(
        clinic_id=clinic,
        patient_id=patient,
        clinical_type="extraction",
        scope="tooth",
        status="planned",
        recorded_at=datetime(2026, 6, 1, tzinfo=UTC),
        source_module="treatment_plan",
    )
    budget = Budget(
        clinic_id=clinic,
        patient_id=patient,
        budget_number="PRES-2026-0011",
        status="accepted",
        valid_from=date(2026, 6, 1),
        created_by=user_id,
        subtotal=Decimal("100"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("100"),
    )
    plan = TreatmentPlan(
        clinic_id=clinic,
        patient_id=patient,
        plan_number="PLAN-0011",
        status="active",
        created_by=user_id,
    )
    invoice = Invoice(
        clinic_id=clinic,
        patient_id=patient,
        invoice_number="F-2026-0011",
        status="issued",
        issue_date=date(2026, 6, 2),
        subtotal=Decimal("100"),
        total_discount=Decimal("0"),
        total_tax=Decimal("0"),
        total=Decimal("100"),
        created_by=user_id,
    )
    db_session.add_all([treatment, budget, plan, invoice])
    await db_session.flush()
    item = PlannedTreatmentItem(
        clinic_id=clinic, treatment_plan_id=plan.id, treatment_id=treatment.id, sequence_order=1
    )
    note = ClinicalNote(
        clinic_id=clinic,
        note_type="diagnosis",
        owner_type="patient",
        owner_id=patient,
        body="Ver radiografía",
        author_id=user_id,
    )
    db_session.add_all([item, note])
    await db_session.flush()
    xray = await DocumentService.create_document(
        db=db_session,
        clinic_id=clinic,
        patient_id=patient,
        user_id=user_id,
        file_data=b"%PDF radiografia",
        original_filename="rx.pdf",
        mime_type="application/pdf",
        document_type="xray",
        title="Radiografía 38",
    )
    db_session.add_all(
        [
            MediaAttachment(
                clinic_id=clinic, document_id=xray.id, owner_type="clinical_note", owner_id=note.id
            ),
            MediaAttachment(
                clinic_id=clinic,
                document_id=xray.id,
                owner_type="plan_item",
                owner_id=item.id,
                display_order=1,
            ),
            BudgetHistory(
                clinic_id=clinic,
                budget_id=budget.id,
                action="accepted",
                changed_by=user_id,
                changed_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                previous_state={"status": "draft"},
                new_state={"status": "accepted"},
            ),
            InvoiceHistory(
                clinic_id=clinic,
                invoice_id=invoice.id,
                action="issued",
                changed_by=user_id,
                changed_at=datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
                notes="Emitida",
            ),
            TreatmentPlanHistory(
                clinic_id=clinic,
                treatment_plan_id=plan.id,
                action="status_changed",
                from_status="draft",
                to_status="active",
                actor_user_id=None,
                created_at=datetime(2026, 6, 1, 13, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    target = tmp_path / "clinic.dpm"
    counts = await write_clinic_export(db_session, clinic, target, passphrase=PASSPHRASE)
    assert counts["document_attachment"] == 2
    assert counts["budget_change"] == 1 and counts["invoice_change"] == 1
    assert counts["plan_change"] == 1

    other = filled["other"].id
    job = ImportJob(
        id=uuid4(),
        clinic_id=other,
        created_by=user_id,
        status="executing",
        original_filename=target.name,
        file_path=str(target),
    )
    db_session.add(job)
    await db_session.commit()
    await import_service.ImportJobService._run_pipeline(db_session, job, passphrase=PASSPHRASE)

    async def rows(model):
        return (
            (await db_session.execute(select(model).where(model.clinic_id == other)))
            .scalars()
            .all()
        )

    links = {a.owner_type: a for a in await rows(MediaAttachment)}
    (moved_note,) = await rows(ClinicalNote)
    (moved_item,) = await rows(PlannedTreatmentItem)
    assert links["clinical_note"].owner_id == moved_note.id
    assert links["plan_item"].owner_id == moved_item.id
    assert links["plan_item"].display_order == 1
    assert links["clinical_note"].document_id == links["plan_item"].document_id

    (budget_entry,) = await rows(BudgetHistory)
    (moved_budget,) = await rows(Budget)
    assert (budget_entry.budget_id, budget_entry.action, budget_entry.changed_at) == (
        moved_budget.id,
        "accepted",
        datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    assert budget_entry.new_state == {"status": "accepted"}
    # The professional came along: the change is still theirs, not the importer's.
    assert str(budget_entry.changed_by) != str(user_id)
    (invoice_entry,) = await rows(InvoiceHistory)
    assert (invoice_entry.action, invoice_entry.notes) == ("issued", "Emitida")
    (plan_entry,) = await rows(TreatmentPlanHistory)
    assert (plan_entry.from_status, plan_entry.to_status, plan_entry.actor_user_id) == (
        "draft",
        "active",
        None,
    )
    assert plan_entry.created_at == datetime(2026, 6, 1, 13, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_an_export_file_expires_and_its_record_stays(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    """The file is there to be downloaded, not kept: past its retention it is
    removed (and refused even before the hourly task runs); the record of
    the export stays, ``expired``."""
    from app.modules.migration_import.export import RETENTION, ExportJobService
    from app.modules.migration_import.models import ExportJob
    from app.modules.migration_import.tasks import expire_exports

    started = await client.post(EXPORTS, headers=auth_headers, json={"passphrase": PASSPHRASE})
    export_id = started.json()["data"]["id"]
    ready = (await client.get(f"{EXPORTS}/{export_id}", headers=auth_headers)).json()["data"]
    assert ready["status"] == "completed"
    completed = datetime.fromisoformat(ready["completed_at"])
    assert datetime.fromisoformat(ready["expires_at"]) == completed + RETENTION

    job = await db_session.get(ExportJob, UUID(export_id))
    path = Path(job.file_path)
    assert path.exists()

    # Not yet: nothing happens.
    assert await ExportJobService.expire_old(db_session) == 0

    # Past its retention: refused at once, then removed by the task.
    job.completed_at = datetime.now(UTC) - RETENTION - timedelta(minutes=1)
    await db_session.commit()
    late = await client.get(f"{EXPORTS}/{export_id}/download", headers=auth_headers)
    assert late.status_code == 409
    assert "caducó" in late.json()["message"]

    await expire_exports()
    db_session.expire_all()
    gone = (await client.get(f"{EXPORTS}/{export_id}", headers=auth_headers)).json()["data"]
    assert (gone["status"], gone["file_size"], gone["expires_at"]) == ("expired", 0, None)
    assert not path.exists()
