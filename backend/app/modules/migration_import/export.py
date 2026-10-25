"""Export a clinic to a DPMF file — the way back of the importer.

What goes in is what the importer here reads back, in the shape its
mappers expect: professionals, cabinets, the treatment catalogue,
patients, appointments and recalls — and, in Diente Azul's own shape
(``mappers/native.py``), the medical history, the odontogram, budgets,
payments, the patient's account, treatment plans, invoices, clinical
notes, consents, health questionnaires, prescriptions, payment plans, documents and their
attachments, and the change histories of budgets, invoices and plans — the files
themselves embedded in the ``.dpm``. Each row also carries the whole
original record as ``raw_source_data``, so the file loses nothing even
where the importer does not use a field yet.

Like the import it requires no other App (ADR 0037): a kind of record
whose App is off is left out, and the file says so in ``_warnings``.
Every query is scoped to the clinic exporting. The passphrase is
mandatory — the file holds patients' data — and never stored.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.models import Clinic

from .dpmf.writer import DpmfWriter, package
from .mappers import running
from .models import ExportJob

logger = logging.getLogger(__name__)

SOURCE_SYSTEM = "dienteazul"
EXPORTER_TOOL = "dienteazul-export"
EXPORTER_VERSION = "0.1.0"
MIN_PASSPHRASE = 12

#: What is collected → the modules its rows are read from.
EXPORTS: dict[str, tuple[str, ...]] = {
    "professional": ("professionals",),
    "catalog_item": ("agenda",),
    "treatment_catalog_item": ("catalog",),
    "patient": ("patients",),
    "appointment": ("patients", "agenda"),
    "recall": ("patients", "recalls"),
    "medical_history": ("patients", "patients_clinical"),
    "odontogram": ("patients", "odontogram"),
    "budgets": ("patients", "budget"),
    "payments": ("patients", "payments"),
    "plans": ("patients", "treatment_plan", "odontogram"),
    "invoices": ("patients", "billing"),
    "clinical_notes": ("patients", "clinical_notes"),
    "consents": ("patients", "consents"),
    "documents": ("patients", "media"),
    "questionnaires": ("patients", "patients_clinical"),
    "prescriptions": ("patients", "treatment_plan"),
    "payment_plans": ("patients", "payments"),
    "attachments": ("patients", "media"),
    "budget_history": ("budget",),
    "invoice_history": ("billing",),
    "plan_history": ("treatment_plan",),
}


def _row(instance: Any) -> dict[str, Any]:
    """Every column of ``instance``, as stored."""
    return {
        column.key: getattr(instance, column.key)
        for column in inspect(instance).mapper.column_attrs
    }


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _rows(db: AsyncSession, model: Any, clinic_id: UUID) -> Iterable[Any]:
    result = await db.execute(select(model).where(model.clinic_id == clinic_id).order_by(model.id))
    return result.scalars().all()


async def _professionals(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.professionals.models import Professional

    for pro in await _rows(db, Professional, clinic_id):
        out.add(
            "professional",
            canonical_uuid=str(pro.id),
            source_id=str(pro.id),
            payload={
                "given_name": pro.first_name,
                "family_name": pro.last_name,
                "email": pro.email,
                "role": pro.professional_type,
                "deactivated": not pro.is_active,
                # Active here means practising now: the importer's
                # "no recent activity" filter must not hide them.
                "last_activity_at": date.today().isoformat() if pro.is_active else None,
            },
            raw=_row(pro),
        )


async def _cabinets(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.agenda.models import Cabinet

    for cabinet in await _rows(db, Cabinet, clinic_id):
        out.add(
            "catalog_item",
            canonical_uuid=str(cabinet.id),
            source_id=str(cabinet.id),
            payload={"kind": "chair", "name": cabinet.name, "code": cabinet.name},
            raw=_row(cabinet),
        )


async def _catalog(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.catalog.models import TreatmentCatalogItem

    for item in await _rows(db, TreatmentCatalogItem, clinic_id):
        if item.deleted_at is not None:
            continue
        names = item.names or {}
        out.add(
            "treatment_catalog_item",
            canonical_uuid=str(item.id),
            source_id=str(item.id),
            payload={
                "code": item.internal_code,
                "name": names.get("es") or next(iter(names.values()), item.internal_code),
                "reference_price": item.default_price,
                "duration_minutes": item.default_duration_minutes,
                "deactivated": not item.is_active,
            },
            raw=_row(item),
        )


_SEX = {"male": "male", "female": "female", "other": "other", "prefer_not_say": "unknown"}


async def _patients(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.patients.models import Patient

    for patient in await _rows(db, Patient, clinic_id):
        address = patient.address or {}
        out.add(
            "patient",
            canonical_uuid=str(patient.id),
            source_id=str(patient.id),
            payload={
                "given_name": patient.first_name,
                "family_name": patient.last_name,
                "date_of_birth": _iso(patient.date_of_birth),
                "sex": _SEX.get(patient.gender or ""),
                "national_id": patient.national_id,
                "phone": patient.phone,
                "email": patient.email,
                "address_street": address.get("street"),
                "address_postal_code": address.get("postal_code"),
                "deactivated_at": None if patient.status == "active" else patient.status,
                "gdpr_consent": False if patient.do_not_contact else None,
                # ``notes`` is left to ``raw_source_data``: the importer
                # reads that key as medical alerts to classify, which a
                # clinic's free-text notes are not.
            },
            raw=_row(patient),
        )


# What an appointment's status is called in the file.
_APPOINTMENT_STATUS = {
    "scheduled": "scheduled",
    "confirmed": "confirmed",
    "checked_in": "confirmed",
    "in_treatment": "confirmed",
    "completed": "attended",
    "no_show": "no_show",
    "cancelled": "cancelled",
}


async def _appointments(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.agenda.models import Appointment

    for apt in await _rows(db, Appointment, clinic_id):
        if apt.patient_id is None:
            out.warn("appointment", str(apt.id), "appointment.no_patient", "Cita sin paciente.")
            continue
        # The agenda reads a stored time by its written parts (wall
        # clock), and the importer writes them back the same way.
        start = apt.start_time.astimezone(UTC) if apt.start_time.tzinfo else apt.start_time
        minutes = int((apt.end_time - apt.start_time).total_seconds() // 60)
        out.add(
            "appointment",
            canonical_uuid=str(apt.id),
            source_id=str(apt.id),
            payload={
                "patient_uuid": str(apt.patient_id),
                "professional_uuid": str(apt.professional_id) if apt.professional_id else None,
                "scheduled_date": start.date().isoformat(),
                "scheduled_time": start.time().replace(tzinfo=None).isoformat(),
                "duration_minutes": max(minutes, 1),
                "coarse_status": _APPOINTMENT_STATUS.get(apt.status, "unknown"),
                "chair_uuid": str(apt.cabinet_id) if apt.cabinet_id else None,
            },
            raw=_row(apt),
        )


async def _recalls(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.recalls.models import Recall

    for recall in await _rows(db, Recall, clinic_id):
        out.add(
            "recall",
            canonical_uuid=str(recall.id),
            source_id=str(recall.id),
            payload={
                "patient_uuid": str(recall.patient_id),
                "professional_uuid": (
                    str(recall.assigned_professional_id)
                    if recall.assigned_professional_id
                    else None
                ),
                "scheduled_date": _iso(recall.due_date or recall.due_month),
                "contact_date": _iso(recall.last_contact_attempt_at),
                "attended": recall.status == "done",
                "scheduled": recall.status == "contacted_scheduled",
                "comments": recall.reason_note,
                "observations": f"Motivo: {recall.reason}" if recall.reason else None,
            },
            raw=_row(recall),
        )


# --- Medical history and odontogram, in Diente Azul's own shape ---------
#
# These are read back by ``mappers/native.py``, field by field. Ended and
# retracted entries travel too: the record keeps them (ADR 0032).

_MEDICAL: dict[str, tuple[str, tuple[str, ...]]] = {
    "allergy": ("Allergy", ("name", "type", "severity", "reaction", "notes")),
    "medication": ("Medication", ("name", "dosage", "frequency", "start_date", "notes")),
    "systemic_disease": (
        "SystemicDisease",
        ("name", "type", "diagnosis_date", "is_controlled", "is_critical", "medications", "notes"),
    ),
    "surgical_history": (
        "SurgicalHistory",
        ("procedure", "surgery_date", "complications", "notes"),
    ),
    "family_history": ("FamilyHistory", ("condition", "relative", "notes")),
    "asa_assessment": ("AsaAssessment", ("assessed_at", "asa_class", "is_emergency", "rationale")),
}


async def _medical_history(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.patients_clinical import models

    for entity_type, (model_name, fields) in _MEDICAL.items():
        for entry in await _rows(db, getattr(models, model_name), clinic_id):
            payload: dict[str, Any] = {f: getattr(entry, f) for f in fields}
            payload.update(
                patient_uuid=str(entry.patient_id),
                professional_uuid=(
                    str(entry.recorded_by_professional_id)
                    if entry.recorded_by_professional_id
                    else None
                ),
                ended_at=entry.ended_at,
                retracted_at=entry.retracted_at,
                retraction_reason=entry.retraction_reason,
                created_at=entry.created_at,
            )
            out.add(
                entity_type,
                canonical_uuid=str(entry.id),
                source_id=str(entry.id),
                payload=payload,
                raw=_row(entry),
            )

    context_fields = (
        "is_pregnant",
        "pregnancy_week",
        "is_lactating",
        "is_on_anticoagulants",
        "anticoagulant_medication",
        "inr_value",
        "last_inr_date",
        "is_smoker",
        "smoking_frequency",
        "alcohol_consumption",
        "bruxism",
        "adverse_reactions_to_anesthesia",
        "anesthesia_reaction_details",
    )
    result = await db.execute(
        select(models.MedicalContext).where(models.MedicalContext.clinic_id == clinic_id)
    )
    for context in result.scalars():
        out.add(
            "medical_context",
            canonical_uuid=str(context.patient_id),
            source_id=str(context.patient_id),
            payload={
                "patient_uuid": str(context.patient_id),
                **{f: getattr(context, f) for f in context_fields},
            },
            raw=_row(context),
        )


async def _odontogram(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from sqlalchemy.orm import selectinload

    from app.modules.odontogram.models import ToothRecord, Treatment

    for tooth in await _rows(db, ToothRecord, clinic_id):
        out.add(
            "tooth_record",
            canonical_uuid=str(tooth.id),
            source_id=str(tooth.id),
            payload={
                "patient_uuid": str(tooth.patient_id),
                "tooth_number": tooth.tooth_number,
                "tooth_type": tooth.tooth_type,
                "general_condition": tooth.general_condition,
                "surfaces": tooth.surfaces,
                "notes": tooth.notes,
                "is_displaced": tooth.is_displaced,
                "is_rotated": tooth.is_rotated,
                "displacement_notes": tooth.displacement_notes,
            },
            raw=_row(tooth),
        )

    profiles = await _account_profiles(db, clinic_id)

    result = await db.execute(
        select(Treatment)
        .options(selectinload(Treatment.teeth))
        .where(Treatment.clinic_id == clinic_id, Treatment.deleted_at.is_(None))
        .order_by(Treatment.id)
    )
    for treatment in result.scalars():
        out.add(
            "clinical_treatment",
            canonical_uuid=str(treatment.id),
            source_id=str(treatment.id),
            payload={
                "patient_uuid": str(treatment.patient_id),
                "clinical_type": treatment.clinical_type,
                "scope": treatment.scope,
                "arch": treatment.arch,
                "catalog_item_uuid": (
                    str(treatment.catalog_item_id) if treatment.catalog_item_id else None
                ),
                "status": treatment.status,
                "recorded_at": treatment.recorded_at,
                "performed_at": treatment.performed_at,
                "professional_uuid": _named(profiles, treatment.performed_by),
                "price_snapshot": treatment.price_snapshot,
                "duration_snapshot": treatment.duration_snapshot,
                "vat_rate_snapshot": treatment.vat_rate_snapshot,
                "notes": treatment.notes,
                "teeth": [
                    {
                        "tooth_number": tooth.tooth_number,
                        "role": tooth.role,
                        "surfaces": tooth.surfaces,
                    }
                    for tooth in treatment.teeth
                ],
            },
            raw={key: value for key, value in _row(treatment).items()},
        )


# --- Budgets, payments and the patient's account ------------------------
#
# Native types too: dental-bridge's ``budget`` and ``payment`` mappers
# translate Gesdén. Deleted budgets stay home; the patient-facing link's
# token and access code are the source's and are not carried.

_SIGNATURE_FIELDS = (
    "signature_type",
    "signed_items",
    "signed_by_name",
    "signed_by_email",
    "relationship_to_patient",
    "signature_method",
    "signature_data",
    "ip_address",
    "user_agent",
    "signed_at",
    "external_signature_id",
    "external_provider",
    "document_hash",
)


async def _budgets(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from sqlalchemy.orm import selectinload

    from app.modules.budget.models import Budget

    result = await db.execute(
        select(Budget)
        .options(selectinload(Budget.items), selectinload(Budget.signatures))
        .where(Budget.clinic_id == clinic_id, Budget.deleted_at.is_(None))
        # Rows are read back in id order whatever the order here; a version
        # whose parent comes later is linked when it lands (native._LaterLinks).
        .order_by(Budget.version, Budget.created_at)
    )
    for budget in result.scalars():
        out.add(
            "treatment_budget",
            canonical_uuid=str(budget.id),
            source_id=budget.budget_number,
            payload={
                "patient_uuid": str(budget.patient_id),
                "budget_number": budget.budget_number,
                "version": budget.version,
                "parent_budget_uuid": str(budget.parent_budget_id)
                if budget.parent_budget_id
                else None,
                "status": budget.status,
                "valid_from": budget.valid_from,
                "valid_until": budget.valid_until,
                "professional_uuid": (
                    str(budget.assigned_professional_id)
                    if budget.assigned_professional_id
                    else None
                ),
                "global_discount_type": budget.global_discount_type,
                "global_discount_value": budget.global_discount_value,
                "subtotal": budget.subtotal,
                "total_discount": budget.total_discount,
                "total_tax": budget.total_tax,
                "total": budget.total,
                "internal_notes": budget.internal_notes,
                "patient_notes": budget.patient_notes,
                "insurance_estimate": budget.insurance_estimate,
                "accepted_via": budget.accepted_via,
                "rejection_reason": budget.rejection_reason,
                "rejection_note": budget.rejection_note,
                "plan_number_snapshot": budget.plan_number_snapshot,
                "plan_status_snapshot": budget.plan_status_snapshot,
                "created_at": budget.created_at,
                "items": [
                    {
                        "uuid": str(item.id),
                        "catalog_item_uuid": str(item.catalog_item_id),
                        "treatment_uuid": str(item.treatment_id) if item.treatment_id else None,
                        "unit_price": item.unit_price,
                        "quantity": item.quantity,
                        "discount_type": item.discount_type,
                        "discount_value": item.discount_value,
                        "vat_rate": item.vat_rate,
                        "line_subtotal": item.line_subtotal,
                        "line_discount": item.line_discount,
                        "line_tax": item.line_tax,
                        "line_total": item.line_total,
                        "tooth_number": item.tooth_number,
                        "surfaces": item.surfaces,
                        "invoiced_quantity": item.invoiced_quantity,
                        "display_order": item.display_order,
                        "notes": item.notes,
                    }
                    for item in sorted(budget.items, key=lambda i: i.display_order)
                ],
                "signatures": [
                    {f: getattr(sign, f) for f in _SIGNATURE_FIELDS} for sign in budget.signatures
                ],
            },
            raw={
                k: v
                for k, v in _row(budget).items()
                if k not in ("public_token", "public_auth_secret_hash")
            },
        )


async def _payments(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from sqlalchemy.orm import selectinload

    from app.modules.payments.models import PatientEarnedEntry, Payment

    result = await db.execute(
        select(Payment)
        .options(selectinload(Payment.allocations), selectinload(Payment.refunds))
        .where(Payment.clinic_id == clinic_id)
        .order_by(Payment.payment_date, Payment.id)
    )
    for payment in result.scalars():
        out.add(
            "patient_payment",
            canonical_uuid=str(payment.id),
            source_id=str(payment.id),
            payload={
                "patient_uuid": str(payment.patient_id),
                "amount": payment.amount,
                "currency": payment.currency,
                "method": payment.method,
                "payment_date": payment.payment_date,
                "reference": payment.reference,
                "notes": payment.notes,
                "created_at": payment.created_at,
                "allocations": [
                    {
                        "target_type": share.target_type,
                        "budget_uuid": str(share.budget_id) if share.budget_id else None,
                        "amount": share.amount,
                    }
                    for share in payment.allocations
                ],
                "refunds": [
                    {
                        "amount": refund.amount,
                        "method": refund.method,
                        "reason_code": refund.reason_code,
                        "reason_note": refund.reason_note,
                        "refunded_at": refund.refunded_at,
                    }
                    for refund in payment.refunds
                ],
            },
            raw=_row(payment),
        )

    for entry in await _rows(db, PatientEarnedEntry, clinic_id):
        out.add(
            "earned_entry",
            canonical_uuid=str(entry.id),
            source_id=str(entry.id),
            payload={
                "patient_uuid": str(entry.patient_id),
                "treatment_uuid": str(entry.treatment_id),
                "catalog_item_uuid": str(entry.catalog_item_id) if entry.catalog_item_id else None,
                "source_session_id": str(entry.source_session_id)
                if entry.source_session_id
                else None,
                "description": entry.description,
                "amount": entry.amount,
                "performed_at": entry.performed_at,
                "professional_uuid": str(entry.professional_id) if entry.professional_id else None,
            },
            raw=_row(entry),
        )


async def _account_profiles(db: AsyncSession, clinic_id: UUID) -> dict[str, UUID]:
    """Account or profile id → the directory profile the file names.

    ``performed_by`` and ``completed_by`` are accounts; the file names
    professionals by their directory profile, which is the account's id
    or carries it."""
    profiles: dict[str, UUID] = {}
    if running("professionals"):
        from app.modules.professionals.models import Professional

        for pro in await _rows(db, Professional, clinic_id):
            profiles[str(pro.id)] = pro.id
            if pro.user_id:
                profiles.setdefault(str(pro.user_id), pro.id)
    return profiles


def _named(profiles: dict[str, UUID], account: UUID | None) -> str | None:
    found = profiles.get(str(account)) if account else None
    return str(found) if found else None


async def _invoices(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from sqlalchemy.orm import selectinload

    from app.modules.billing.models import Invoice

    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items), selectinload(Invoice.invoice_payments))
        .where(Invoice.clinic_id == clinic_id, Invoice.deleted_at.is_(None))
        # As for budget versions: a credit note read before its invoice is
        # linked when the invoice lands.
        .order_by(Invoice.credit_note_for_id.is_not(None), Invoice.issue_date, Invoice.created_at)
    )
    for invoice in result.scalars():
        out.add(
            "patient_invoice",
            canonical_uuid=str(invoice.id),
            source_id=invoice.invoice_number or str(invoice.id),
            payload={
                "patient_uuid": str(invoice.patient_id),
                "invoice_number": invoice.invoice_number,
                "budget_uuid": str(invoice.budget_id) if invoice.budget_id else None,
                "credit_note_for_uuid": (
                    str(invoice.credit_note_for_id) if invoice.credit_note_for_id else None
                ),
                "status": invoice.status,
                "issue_date": invoice.issue_date,
                "due_date": invoice.due_date,
                "payment_term_days": invoice.payment_term_days,
                "billing_name": invoice.billing_name,
                "billing_tax_id": invoice.billing_tax_id,
                "billing_address": invoice.billing_address,
                "billing_email": invoice.billing_email,
                "subtotal": invoice.subtotal,
                "total_discount": invoice.total_discount,
                "total_tax": invoice.total_tax,
                "total": invoice.total,
                "internal_notes": invoice.internal_notes,
                "public_notes": invoice.public_notes,
                "compliance_data": invoice.compliance_data,
                "document_hash": invoice.document_hash,
                "previous_hash": invoice.previous_hash,
                "created_at": invoice.created_at,
                "items": [
                    {
                        "budget_item_uuid": str(item.budget_item_id)
                        if item.budget_item_id
                        else None,
                        "catalog_item_uuid": (
                            str(item.catalog_item_id) if item.catalog_item_id else None
                        ),
                        "description": item.description,
                        "internal_code": item.internal_code,
                        "unit_price": item.unit_price,
                        "quantity": item.quantity,
                        "discount_type": item.discount_type,
                        "discount_value": item.discount_value,
                        "vat_rate": item.vat_rate,
                        "vat_exempt_reason": item.vat_exempt_reason,
                        "line_subtotal": item.line_subtotal,
                        "line_discount": item.line_discount,
                        "line_tax": item.line_tax,
                        "line_total": item.line_total,
                        "tooth_number": item.tooth_number,
                        "surfaces": item.surfaces,
                        "display_order": item.display_order,
                    }
                    for item in sorted(invoice.items, key=lambda i: i.display_order)
                ],
                "payments": [
                    {"payment_uuid": str(applied.payment_id), "amount": applied.amount}
                    for applied in invoice.invoice_payments
                ],
            },
            raw=_row(invoice),
        )


async def _plans(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from sqlalchemy.orm import selectinload

    from app.modules.treatment_plan.models import PlannedTreatmentItem, TreatmentPlan

    profiles = await _account_profiles(db, clinic_id)
    result = await db.execute(
        select(TreatmentPlan)
        .options(selectinload(TreatmentPlan.items).selectinload(PlannedTreatmentItem.sessions))
        .where(TreatmentPlan.clinic_id == clinic_id, TreatmentPlan.deleted_at.is_(None))
        .order_by(TreatmentPlan.created_at)
    )
    for plan in result.scalars():
        out.add(
            "treatment_plan",
            canonical_uuid=str(plan.id),
            source_id=plan.plan_number,
            payload={
                "patient_uuid": str(plan.patient_id),
                "plan_number": plan.plan_number,
                "title": plan.title,
                "status": plan.status,
                "closure_reason": plan.closure_reason,
                "closure_note": plan.closure_note,
                "closed_at": plan.closed_at,
                "confirmed_at": plan.confirmed_at,
                "budget_uuid": str(plan.budget_id) if plan.budget_id else None,
                "professional_uuid": (
                    str(plan.assigned_professional_id) if plan.assigned_professional_id else None
                ),
                "diagnosis_notes": plan.diagnosis_notes,
                "prognosis": plan.prognosis,
                "prognosis_notes": plan.prognosis_notes,
                "internal_notes": plan.internal_notes,
                "created_at": plan.created_at,
                "items": [
                    {
                        "uuid": str(item.id),
                        "treatment_uuid": str(item.treatment_id),
                        "phase": item.phase,
                        "sequence_order": item.sequence_order,
                        "status": item.status,
                        "completed_without_appointment": item.completed_without_appointment,
                        "completed_at": item.completed_at,
                        "completed_by_uuid": _named(profiles, item.completed_by),
                        "professional_uuid": (
                            str(item.assigned_professional_id)
                            if item.assigned_professional_id
                            else None
                        ),
                        "notes": item.notes,
                        "sessions": [
                            {
                                "sequence": session.sequence,
                                "label": session.label,
                                "amount": session.amount,
                                "status": session.status,
                                "completed_at": session.completed_at,
                                "completed_by_uuid": _named(profiles, session.completed_by),
                                "notes": session.notes,
                            }
                            for session in sorted(item.sessions, key=lambda s: s.sequence)
                        ],
                    }
                    for item in sorted(plan.items, key=lambda i: i.sequence_order)
                ],
            },
            raw=_row(plan),
        )


async def _clinical_notes(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.clinical_notes.models import ClinicalNote, ClinicalNoteVersion

    profiles = await _account_profiles(db, clinic_id)
    versions: dict[UUID, list[Any]] = {}
    for old in await _rows(db, ClinicalNoteVersion, clinic_id):
        versions.setdefault(old.note_id, []).append(old)
    # Deleted notes travel too: the record keeps what it said (ADR 0032).
    for note in await _rows(db, ClinicalNote, clinic_id):
        author = note.authored_by_professional_id or note.author_id
        out.add(
            "clinical_note",
            canonical_uuid=str(note.id),
            source_id=str(note.id),
            payload={
                "note_type": note.note_type,
                "owner_type": note.owner_type,
                "owner_uuid": str(note.owner_id),
                "tooth_number": note.tooth_number,
                "body": note.body,
                "vitals": note.vitals,
                "professional_uuid": _named(profiles, author),
                "version": note.version,
                "amended_at": note.amended_at,
                "deleted_at": note.deleted_at,
                "created_at": note.created_at,
                "versions": [
                    {
                        "version": old.version,
                        "body": old.body,
                        "superseded_at": old.superseded_at,
                        "professional_uuid": _named(
                            profiles, old.superseded_by_professional_id or old.superseded_by_user_id
                        ),
                        "amendment_reason": old.amendment_reason,
                    }
                    for old in sorted(versions.get(note.id, []), key=lambda v: v.version)
                ],
            },
            raw=_row(note),
        )


async def _consents(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.consents.models import Consent, ConsentTemplate

    for template in await _rows(db, ConsentTemplate, clinic_id):
        out.add(
            "consent_template",
            canonical_uuid=str(template.id),
            source_id=str(template.id),
            payload={
                "kind": template.kind,
                "title": template.title,
                "body": template.body,
                "version": template.version,
                "is_active": template.is_active,
            },
            raw=_row(template),
        )
    for consent in await _rows(db, Consent, clinic_id):
        out.add(
            "patient_consent",
            canonical_uuid=str(consent.id),
            source_id=str(consent.id),
            payload={
                "patient_uuid": str(consent.patient_id),
                "kind": consent.kind,
                "status": consent.status,
                "title": consent.title,
                "body": consent.body,
                "template_uuid": str(consent.template_id) if consent.template_id else None,
                "template_version": consent.template_version,
                "procedure_label": consent.procedure_label,
                "plan_uuid": str(consent.plan_id) if consent.plan_id else None,
                "professional_uuid": (
                    str(consent.explained_by_professional_id)
                    if consent.explained_by_professional_id
                    else None
                ),
                "explained_by_name": consent.explained_by_name,
                "explained_by_license": consent.explained_by_license,
                "signed_at": consent.signed_at,
                "signed_by_name": consent.signed_by_name,
                "signer_capacity": consent.signer_capacity,
                "signature_method": consent.signature_method,
                "signature_data": consent.signature_data,
                "regulation": consent.regulation,
                "declined_at": consent.declined_at,
                "revoked_at": consent.revoked_at,
                "status_note": consent.status_note,
                "created_at": consent.created_at,
            },
            raw=_row(consent),
        )


#: The files a ``.dpm`` can carry, in total. The envelope is sealed in one
#: piece (AES-GCM over the whole file, as the reader expects), so the file
#: is held in memory twice while it is built; past this, export without
#: documents.
MAX_DOCUMENT_BYTES = int(
    getattr(settings, "MIGRATION_EXPORT_MAX_DOCUMENT_BYTES", 500 * 1024 * 1024)
)


class DocumentsTooLargeError(ValueError):
    """The clinic's files do not fit in one sealed ``.dpm``."""


async def _documents(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    import hashlib

    from app.modules.media.models import Document
    from app.modules.media.service import DocumentService

    documents = await _rows(db, Document, clinic_id)
    total = sum(document.file_size or 0 for document in documents)
    if total > MAX_DOCUMENT_BYTES:
        raise DocumentsTooLargeError(
            f"Los documentos suman {total // (1024 * 1024)} MB y el archivo admite "
            f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MB; exporta sin documentos."
        )
    for document in documents:
        try:
            data = await DocumentService.download_document(document)
        except Exception:  # a file the storage no longer has
            out.warn(
                "stored_document",
                str(document.id),
                "file_missing",
                f"Documento «{document.title}» sin su archivo en el almacenamiento.",
            )
            continue
        out.add_blob(str(document.id), data)
        out.add(
            "stored_document",
            canonical_uuid=str(document.id),
            source_id=str(document.id),
            payload={
                "patient_uuid": str(document.patient_id),
                "sha256": hashlib.sha256(data).hexdigest(),
                "title": document.title,
                "description": document.description,
                "document_type": document.document_type,
                "original_filename": document.original_filename,
                "mime_type": document.mime_type,
                "media_kind": document.media_kind,
                "media_category": document.media_category,
                "media_subtype": document.media_subtype,
                "captured_at": document.captured_at,
                "tags": document.tags,
                "status": document.status,
                "paired_document_uuid": (
                    str(document.paired_document_id) if document.paired_document_id else None
                ),
                "created_at": document.created_at,
            },
            raw={k: v for k, v in _row(document).items() if k != "storage_path"},
        )


async def _questionnaires(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.patients_clinical.models import HealthQuestionnaire

    fields = (
        "taken_at",
        "form_version",
        "chief_complaint",
        "blood_type",
        "declared_allergies",
        "answers",
        "conditions",
        "drugs_detail",
        "other_conditions",
        "signed_at",
        "signed_by_name",
        "signer_capacity",
        "signature_data",
        "regulation",
        "ended_at",
        "retracted_at",
        "retraction_reason",
        "created_at",
    )
    for questionnaire in await _rows(db, HealthQuestionnaire, clinic_id):
        out.add(
            "health_questionnaire",
            canonical_uuid=str(questionnaire.id),
            source_id=str(questionnaire.id),
            payload={
                "patient_uuid": str(questionnaire.patient_id),
                "scan_document_uuid": (
                    str(questionnaire.scan_document_id) if questionnaire.scan_document_id else None
                ),
                "professional_uuid": (
                    str(questionnaire.recorded_by_professional_id)
                    if questionnaire.recorded_by_professional_id
                    else None
                ),
                **{f: getattr(questionnaire, f) for f in fields},
            },
            raw=_row(questionnaire),
        )


async def _prescriptions(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.treatment_plan.models import TreatmentPrescription

    profiles = await _account_profiles(db, clinic_id)
    for prescription in await _rows(db, TreatmentPrescription, clinic_id):
        out.add(
            "prescription_record",
            canonical_uuid=str(prescription.id),
            source_id=str(prescription.id),
            payload={
                "patient_uuid": str(prescription.patient_id),
                "plan_item_uuid": (
                    str(prescription.plan_item_id) if prescription.plan_item_id else None
                ),
                "treatment_label": prescription.treatment_label,
                "professional_uuid": (
                    str(prescription.professional_id) if prescription.professional_id else None
                ),
                "professional_name": prescription.professional_name,
                "professional_license": prescription.professional_license,
                "body": prescription.body,
                "issued_by_uuid": _named(profiles, prescription.issued_by),
                "created_at": prescription.created_at,
            },
            raw=_row(prescription),
        )


async def _payment_plans(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from sqlalchemy.orm import selectinload

    from app.modules.payments.models import CollectionContact, PaymentSchedule

    result = await db.execute(
        select(PaymentSchedule)
        .options(selectinload(PaymentSchedule.instalments))
        .where(PaymentSchedule.clinic_id == clinic_id)
        .order_by(PaymentSchedule.id)
    )
    for schedule in result.scalars():
        out.add(
            "payment_schedule",
            canonical_uuid=str(schedule.id),
            source_id=str(schedule.id),
            payload={
                "patient_uuid": str(schedule.patient_id),
                "budget_uuid": str(schedule.budget_id) if schedule.budget_id else None,
                "status": schedule.status,
                "notes": schedule.notes,
                "created_at": schedule.created_at,
                "instalments": [
                    {
                        "sequence": instalment.sequence,
                        "label": instalment.label,
                        "due_date": instalment.due_date,
                        "amount": instalment.amount,
                    }
                    for instalment in sorted(schedule.instalments, key=lambda i: i.sequence)
                ],
            },
            raw=_row(schedule),
        )
    profiles = await _account_profiles(db, clinic_id)
    for contact in await _rows(db, CollectionContact, clinic_id):
        out.add(
            "collection_contact",
            canonical_uuid=str(contact.id),
            source_id=str(contact.id),
            payload={
                "patient_uuid": str(contact.patient_id),
                "channel": contact.channel,
                "note": contact.note,
                "contacted_by_uuid": _named(profiles, contact.contacted_by),
                "created_at": contact.created_at,
            },
            raw=_row(contact),
        )


async def _attachments(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    from app.modules.media.models import MediaAttachment

    for link in await _rows(db, MediaAttachment, clinic_id):
        out.add(
            "document_attachment",
            canonical_uuid=str(link.id),
            source_id=str(link.id),
            payload={
                "document_uuid": str(link.document_id),
                "owner_type": link.owner_type,
                "owner_uuid": str(link.owner_id),
                "display_order": link.display_order,
            },
            raw=_row(link),
        )


async def _account_names(db: AsyncSession, clinic_id: UUID) -> dict[str, str]:
    """Who each account of the clinic was, for history entries whose author
    does not come along as a professional."""
    from app.core.auth.models import ClinicMembership, User

    rows = await db.execute(
        select(User.id, User.first_name, User.last_name)
        .join(ClinicMembership, ClinicMembership.user_id == User.id)
        .where(ClinicMembership.clinic_id == clinic_id)
    )
    return {str(uid): f"{first or ''} {last or ''}".strip() for uid, first, last in rows.all()}


def _history_models() -> dict[str, tuple[Any, str, str, str, tuple[str, ...]]]:
    """Entity type → (model, parent id column, actor column, moment column,
    fields)."""
    from app.modules.billing.models import InvoiceHistory
    from app.modules.budget.models import BudgetHistory
    from app.modules.treatment_plan.models import TreatmentPlanHistory

    changes = ("action", "previous_state", "new_state", "notes")
    return {
        "budget_change": (BudgetHistory, "budget_id", "changed_by", "changed_at", changes),
        "invoice_change": (InvoiceHistory, "invoice_id", "changed_by", "changed_at", changes),
        "plan_change": (
            TreatmentPlanHistory,
            "treatment_plan_id",
            "actor_user_id",
            "created_at",
            ("action", "from_status", "to_status", "payload"),
        ),
    }


async def _history(entity_type: str, db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    model, parent, actor, when, fields = _history_models()[entity_type]
    profiles = await _account_profiles(db, clinic_id)
    names = await _account_names(db, clinic_id)
    for entry in await _rows(db, model, clinic_id):
        account = getattr(entry, actor)
        out.add(
            entity_type,
            canonical_uuid=str(entry.id),
            source_id=str(entry.id),
            payload={
                "parent_uuid": str(getattr(entry, parent)),
                "actor_uuid": _named(profiles, account),
                "at": getattr(entry, when),
                **{f: getattr(entry, f) for f in fields},
            },
            raw={**_row(entry), "actor_name": names.get(str(account)) if account else None},
        )


async def _budget_history(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    await _history("budget_change", db, clinic_id, out)


async def _invoice_history(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    await _history("invoice_change", db, clinic_id, out)


async def _plan_history(db: AsyncSession, clinic_id: UUID, out: DpmfWriter) -> None:
    await _history("plan_change", db, clinic_id, out)


_COLLECTORS = {
    "professional": _professionals,
    "catalog_item": _cabinets,
    "treatment_catalog_item": _catalog,
    "patient": _patients,
    "appointment": _appointments,
    "recall": _recalls,
    "medical_history": _medical_history,
    "odontogram": _odontogram,
    "budgets": _budgets,
    "payments": _payments,
    "plans": _plans,
    "invoices": _invoices,
    "clinical_notes": _clinical_notes,
    "consents": _consents,
    "documents": _documents,
    "questionnaires": _questionnaires,
    "prescriptions": _prescriptions,
    "payment_plans": _payment_plans,
    "attachments": _attachments,
    "budget_history": _budget_history,
    "invoice_history": _invoice_history,
    "plan_history": _plan_history,
}


async def write_clinic_export(
    db: AsyncSession,
    clinic_id: UUID,
    destination: Path,
    *,
    passphrase: str,
    include_documents: bool = True,
) -> dict[str, int]:
    """Write the clinic's ``.dpm`` to ``destination``. Returns rows per type.

    ``include_documents`` embeds every file (radiographs, photos, scans);
    without it the records still name their documents, which do not come.
    """
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"passphrase must be at least {MIN_PASSPHRASE} characters")
    clinic = await db.get(Clinic, clinic_id)
    with tempfile.TemporaryDirectory(prefix="dpmf-export-") as tmp:
        plain = Path(tmp) / "export.sqlite"
        out = DpmfWriter(plain, source_system=SOURCE_SYSTEM)
        for entity_type, collect in _COLLECTORS.items():
            if entity_type in ("documents", "attachments") and not include_documents:
                if entity_type == "documents":
                    out.warn("stored_document", None, "left_out", "Exportado sin documentos.")
                continue
            missing = [m for m in EXPORTS[entity_type] if not running(m)]
            if missing:
                out.warn(
                    entity_type,
                    None,
                    "app.disabled",
                    f"No exportado: no está activo {', '.join(missing)}.",
                )
                continue
            await collect(db, clinic_id, out)
        counts = out.counts
        out.finish(
            {
                "exporter_tool": EXPORTER_TOOL,
                "exporter_version": EXPORTER_VERSION,
                "source_adapter_version": EXPORTER_VERSION,
                "tenant_label": clinic.name if clinic else "",
            }
        )
        package(plain, destination, passphrase=passphrase)
    return counts


#: How long an export's file stays on the server. It holds every patient's
#: data: it is there to be downloaded, not kept. Past this the file is
#: removed (``expire_exports``, hourly) and the record stays, ``expired``.
RETENTION = timedelta(days=int(getattr(settings, "MIGRATION_EXPORT_RETENTION_DAYS", 7)))


def expires_at(job: ExportJob) -> datetime | None:
    """When a ready export's file goes; ``None`` when it has no file."""
    if job.status != "completed" or job.completed_at is None:
        return None
    return job.completed_at + RETENTION


class ExportJobService:
    """The export jobs of a clinic: started, run in the background, fetched."""

    @staticmethod
    async def expire_old(db: AsyncSession, now: datetime | None = None) -> int:
        """Remove every file past its retention, across clinics. Returns how many."""
        cutoff = (now or datetime.now(UTC)) - RETENTION
        result = await db.execute(
            select(ExportJob).where(
                ExportJob.status == "completed", ExportJob.completed_at < cutoff
            )
        )
        expired = 0
        for job in result.scalars():
            if job.file_path:
                Path(job.file_path).unlink(missing_ok=True)
            job.file_path = None
            job.file_size = 0
            job.status = "expired"
            expired += 1
        await db.flush()
        return expired

    @staticmethod
    def file_for(job_id: UUID, clinic_id: UUID) -> Path:
        from .lifecycle import _staging_root

        folder = _staging_root() / "exports" / str(clinic_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{job_id}.dpm"

    @staticmethod
    async def expected_bytes(db: AsyncSession, clinic_id: UUID, include_documents: bool) -> int:
        """What a new export will take on the server, plus what the clinic's
        kept exports already do: the documents dominate; records are small."""
        from sqlalchemy import func

        kept = await db.scalar(
            select(func.coalesce(func.sum(ExportJob.file_size), 0)).where(
                ExportJob.clinic_id == clinic_id, ExportJob.status == "completed"
            )
        )
        documents = 0
        if include_documents and running("media"):
            from app.modules.media.models import Document

            documents = await db.scalar(
                select(func.coalesce(func.sum(Document.file_size), 0)).where(
                    Document.clinic_id == clinic_id
                )
            )
        return int(kept or 0) + int(documents or 0)

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, user_id: UUID) -> ExportJob:
        job = ExportJob(clinic_id=clinic_id, created_by=user_id, status="pending")
        db.add(job)
        await db.flush()
        return job

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, job_id: UUID) -> ExportJob | None:
        result = await db.execute(
            select(ExportJob).where(ExportJob.id == job_id, ExportJob.clinic_id == clinic_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list(db: AsyncSession, clinic_id: UUID, limit: int = 20) -> list[ExportJob]:
        result = await db.execute(
            select(ExportJob)
            .where(ExportJob.clinic_id == clinic_id)
            .order_by(ExportJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def run(
        db: AsyncSession, job: ExportJob, *, passphrase: str, include_documents: bool = True
    ) -> ExportJob:
        """Write the file for ``job``. Failures are kept on the row."""
        destination = ExportJobService.file_for(job.id, job.clinic_id)
        job.status = "running"
        job.error = None
        job.error_code = None
        await db.commit()
        try:
            counts = await write_clinic_export(
                db,
                job.clinic_id,
                destination,
                passphrase=passphrase,
                include_documents=include_documents,
            )
        except Exception as exc:
            logger.exception("export %s failed", job.id)
            destination.unlink(missing_ok=True)
            job.status = "failed"
            job.error = str(exc)
            job.error_code = "migration_import.export.failed"
        else:
            job.status = "completed"
            job.file_path = str(destination)
            job.file_size = destination.stat().st_size
            job.entity_counts = counts
            job.completed_at = datetime.now(UTC)
        await db.commit()
        return job

    @staticmethod
    async def run_in_background(
        job_id: UUID, *, passphrase: str, include_documents: bool = True
    ) -> None:
        """BackgroundTask entry point: its own session, like the import."""
        from app.database import async_session_maker

        async with async_session_maker() as db:
            job = await db.get(ExportJob, job_id)
            if job is None or job.status != "pending":
                return
            await ExportJobService.run(
                db, job, passphrase=passphrase, include_documents=include_documents
            )

    @staticmethod
    async def delete_file(db: AsyncSession, job: ExportJob) -> ExportJob:
        """Remove the file; the row stays as the record of the export."""
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        job.file_path = None
        job.file_size = 0
        job.status = "deleted"
        await db.flush()
        return job
