"""Records Diente Azul writes out of itself, read back field by field.

dental-bridge's canonical types describe another program, and their
mappers translate from it (Gesdén's treatment codes, its statuses). A
clinic exported from Diente Azul does not need translating: its medical
history and its odontogram go into the file in their own shape, and these
mappers put them back as they were — dates, who answered for each entry,
what was ended or retracted (ADR 0032: nothing is dropped for being no
longer true).

A professional in the file is the source's directory profile; the
professional mapper made it an account here, and ``_profile`` mirrors that
account into the directory, the way the agenda does, so a column pointing
at ``professionals.id`` holds.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ..models import ImportWarning
from .base import MapperContext


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _d(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def _patient(
    ctx: MapperContext, payload: dict[str, Any], entity_type: str, source_id: str
) -> UUID | None:
    patient_uuid = payload.get("patient_uuid")
    patient_id = await ctx.resolver.get("patient", str(patient_uuid)) if patient_uuid else None
    if patient_id is None:
        ctx.db.add(
            ImportWarning(
                job_id=ctx.job_id,
                entity_type=entity_type,
                source_id=source_id,
                severity="warn",
                code=f"{entity_type}.unmapped_patient",
                message="Omitido: el paciente no se importó.",
            )
        )
    return patient_id


async def _account(ctx: MapperContext, professional_uuid: Any) -> UUID | None:
    """The account the file's professional became here, if any."""
    if not professional_uuid:
        return None
    return await ctx.resolver.get("professional", str(professional_uuid))


async def _profile(ctx: MapperContext, professional_uuid: Any) -> UUID | None:
    """The directory profile for the file's professional, when there is one."""
    from app.core.contracts import ProfessionalDirectory, provider

    account = await _account(ctx, professional_uuid)
    directory = provider(ProfessionalDirectory)
    if account is None or directory is None:
        return None
    await directory.ensure_profile(ctx.db, ctx.clinic_id, account)
    from app.modules.professionals.models import Professional

    return account if await ctx.db.get(Professional, account) is not None else None


# --- Medical history -------------------------------------------------------

_ENTRY_COLUMNS = ("ended_at", "retracted_at")


class MedicalEntryMapper:
    """One entry of the medical history: allergy, medication, disease,
    surgery, family history or ASA class. The payload carries the model's
    own columns."""

    def __init__(
        self,
        model_path: str,
        entity_type: str,
        fields: tuple[str, ...],
        dates: tuple[str, ...] = (),
    ) -> None:
        self._model_path = model_path
        self._entity_type = entity_type
        self._fields = fields
        self._dates = dates

    def _model(self) -> Any:
        from app.modules.patients_clinical import models

        return getattr(models, self._model_path)

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        model = self._model()
        values: dict[str, Any] = {
            f: payload.get(f) for f in self._fields if payload.get(f) is not None
        }
        for f in self._dates:
            if f in values:
                values[f] = _d(values[f]) if not f.endswith("_at") else _dt(values[f])
        for f in _ENTRY_COLUMNS:
            if payload.get(f):
                values[f] = _dt(payload[f])
        if payload.get("retraction_reason"):
            values["retraction_reason"] = payload["retraction_reason"]
        row = model(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            recorded_by_professional_id=await _profile(ctx, payload.get("professional_uuid")),
            **values,
        )
        if payload.get("created_at"):
            row.created_at = _dt(payload["created_at"])
        ctx.db.add(row)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=model.__tablename__,
            dienteazul_id=row.id,
        )
        return row.id


class MedicalContextMapper:
    """The patient's standing medical context: one per patient, upserted."""

    FIELDS = (
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

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.patients_clinical.models import MedicalContext

        if await ctx.resolver.get(entity_type, canonical_uuid) is not None:
            return None
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        context = (
            await ctx.db.execute(
                select(MedicalContext).where(MedicalContext.patient_id == patient_id)
            )
        ).scalar_one_or_none()
        if context is None:
            context = MedicalContext(patient_id=patient_id, clinic_id=ctx.clinic_id)
            ctx.db.add(context)
        for f in self.FIELDS:
            if f in payload and payload[f] is not None:
                setattr(context, f, _d(payload[f]) if f == "last_inr_date" else payload[f])
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="patients_clinical_medical_context",
            dienteazul_id=patient_id,
        )
        return patient_id


# --- Odontogram ------------------------------------------------------------


async def _tooth(ctx: MapperContext, patient_id: UUID, tooth_number: int) -> Any:
    from app.modules.odontogram.models import ToothRecord

    record = (
        await ctx.db.execute(
            select(ToothRecord).where(
                ToothRecord.clinic_id == ctx.clinic_id,
                ToothRecord.patient_id == patient_id,
                ToothRecord.tooth_number == tooth_number,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        record = ToothRecord(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            tooth_number=tooth_number,
            tooth_type="permanent" if 11 <= tooth_number <= 48 else "deciduous",
            general_condition="healthy",
            surfaces={},
        )
        ctx.db.add(record)
        await ctx.db.flush()
    return record


class ToothRecordMapper:
    """A tooth's state on the odontogram, as the source last left it."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        record = await _tooth(ctx, patient_id, int(payload["tooth_number"]))
        for f in (
            "tooth_type",
            "general_condition",
            "surfaces",
            "notes",
            "is_displaced",
            "is_rotated",
            "displacement_notes",
        ):
            if payload.get(f) is not None:
                setattr(record, f, payload[f])
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="tooth_records",
            dienteazul_id=record.id,
        )
        return record.id


class ClinicalTreatmentMapper:
    """A treatment on the odontogram — performed, planned or existing — with
    its teeth and surfaces. Its plan and budget are not part of it."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.odontogram.models import Treatment, TreatmentTooth

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        catalog_uuid = payload.get("catalog_item_uuid")
        catalog_item_id = (
            await ctx.resolver.get("treatment_catalog_item", str(catalog_uuid))
            if catalog_uuid
            else None
        )
        price = payload.get("price_snapshot")
        treatment = Treatment(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            clinical_type=payload["clinical_type"],
            scope=payload.get("scope") or "tooth",
            arch=payload.get("arch"),
            catalog_item_id=catalog_item_id,
            status=payload.get("status") or "performed",
            recorded_at=_dt(payload.get("recorded_at")) or datetime.now().astimezone(),
            performed_at=_dt(payload.get("performed_at")),
            performed_by=await _account(ctx, payload.get("professional_uuid")),
            price_snapshot=Decimal(str(price)) if price is not None else None,
            duration_snapshot=payload.get("duration_snapshot"),
            vat_rate_snapshot=payload.get("vat_rate_snapshot"),
            notes=payload.get("notes"),
            source_module="migration_import",
        )
        ctx.db.add(treatment)
        await ctx.db.flush()
        for tooth in payload.get("teeth") or []:
            record = await _tooth(ctx, patient_id, int(tooth["tooth_number"]))
            ctx.db.add(
                TreatmentTooth(
                    treatment_id=treatment.id,
                    tooth_record_id=record.id,
                    tooth_number=int(tooth["tooth_number"]),
                    role=tooth.get("role"),
                    surfaces=tooth.get("surfaces"),
                )
            )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="treatments",
            dienteazul_id=treatment.id,
        )
        return treatment.id


# --- Budgets, payments and the patient's account ---------------------------
#
# Budgets travel with their lines and signatures; payments with how they
# were allocated and refunded; the account's charges (``earned_entry``)
# with the treatment they bill. Treatments come in before budgets, so a
# line points at its treatment and the treatment back at its line, as in
# the source. The patient-facing link of a budget is not carried: its
# token is new here, and its access code (a hash) stays behind.

_ORPHAN_TREATMENT = UUID("00000000-0000-0000-0000-000000000000")


class _LaterLinks:
    """Links to a row of the same type that has not come in yet.

    Rows of one type are read in id order, not in the order they were
    written, so a credit note can arrive before its invoice and a budget's
    version before its parent. The link waits here and is set when the
    other row lands. Keyed by job: one import never links into another
    (another clinic's, possibly)."""

    def __init__(self) -> None:
        self._waiting: dict[tuple[UUID, str], list[UUID]] = {}

    def wait(self, ctx: MapperContext, target_uuid: str, row_id: UUID) -> None:
        self._waiting.setdefault((ctx.job_id, target_uuid), []).append(row_id)

    async def arrived(
        self, ctx: MapperContext, model: Any, column: str, target_uuid: str, target_id: UUID
    ) -> None:
        for row_id in self._waiting.pop((ctx.job_id, target_uuid), []):
            row = await ctx.db.get(model, row_id)
            if row is not None:
                setattr(row, column, target_id)


def _money(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


async def _warn_native(
    ctx: MapperContext, entity_type: str, source_id: str, code: str, message: str
) -> None:
    ctx.db.add(
        ImportWarning(
            job_id=ctx.job_id,
            entity_type=entity_type,
            source_id=source_id,
            severity="warn",
            code=f"{entity_type}.{code}",
            message=message,
        )
    )


class TreatmentBudgetMapper:
    def __init__(self) -> None:
        self._parents = _LaterLinks()

    BUDGET_FIELDS = (
        "status",
        "global_discount_type",
        "internal_notes",
        "patient_notes",
        "accepted_via",
        "rejection_reason",
        "rejection_note",
        "plan_number_snapshot",
        "plan_status_snapshot",
    )
    MONEY = (
        "global_discount_value",
        "subtotal",
        "total_discount",
        "total_tax",
        "total",
        "insurance_estimate",
    )

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.budget.models import Budget, BudgetItem, BudgetSignature
        from app.modules.odontogram.models import Treatment

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None

        # A number the clinic already uses keeps its digits and says where
        # it came from.
        number, version = payload["budget_number"], int(payload.get("version") or 1)
        taken = await ctx.db.execute(
            select(Budget.id).where(
                Budget.clinic_id == ctx.clinic_id,
                Budget.budget_number == number,
                Budget.version == version,
            )
        )
        if taken.scalar_one_or_none() is not None:
            renamed = f"IMP-{number}"[:50]
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "number_taken",
                f"El número {number} ya existe en la clínica; se importa como {renamed}.",
            )
            number = renamed

        parent_uuid = payload.get("parent_budget_uuid")
        parent_id = await ctx.resolver.get(entity_type, str(parent_uuid)) if parent_uuid else None
        budget = Budget(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            budget_number=number,
            version=version,
            parent_budget_id=parent_id,
            valid_from=_d(payload.get("valid_from")) or date.today(),
            valid_until=_d(payload.get("valid_until")),
            created_by=ctx.created_by,
            assigned_professional_id=await _profile(ctx, payload.get("professional_uuid")),
            **{f: payload[f] for f in self.BUDGET_FIELDS if payload.get(f) is not None},
            **{f: _money(payload[f]) for f in self.MONEY if payload.get(f) is not None},
        )
        if payload.get("created_at"):
            budget.created_at = _dt(payload["created_at"])
        ctx.db.add(budget)
        await ctx.db.flush()

        for line in payload.get("items") or []:
            catalog_uuid = line.get("catalog_item_uuid")
            catalog_item_id = (
                await ctx.resolver.get("treatment_catalog_item", str(catalog_uuid))
                if catalog_uuid
                else None
            )
            if catalog_item_id is None:
                await _warn_native(
                    ctx,
                    entity_type,
                    source_id,
                    "line_without_catalog",
                    f"Línea sin tratamiento del catálogo importado; no se incluye ({line.get('notes') or ''}).",
                )
                continue
            treatment_uuid = line.get("treatment_uuid")
            treatment_id = (
                await ctx.resolver.get("clinical_treatment", str(treatment_uuid))
                if treatment_uuid
                else None
            )
            item = BudgetItem(
                clinic_id=ctx.clinic_id,
                budget_id=budget.id,
                catalog_item_id=catalog_item_id,
                unit_price=_money(line["unit_price"]),
                quantity=int(line.get("quantity") or 1),
                discount_type=line.get("discount_type"),
                discount_value=_money(line.get("discount_value")),
                vat_rate=float(line.get("vat_rate") or 0),
                line_subtotal=_money(line["line_subtotal"]),
                line_discount=_money(line.get("line_discount")) or Decimal(0),
                line_tax=_money(line.get("line_tax")) or Decimal(0),
                line_total=_money(line["line_total"]),
                tooth_number=line.get("tooth_number"),
                surfaces=line.get("surfaces"),
                treatment_id=treatment_id,
                invoiced_quantity=int(line.get("invoiced_quantity") or 0),
                display_order=int(line.get("display_order") or 0),
                notes=line.get("notes"),
            )
            ctx.db.add(item)
            await ctx.db.flush()
            # An invoice line points at the budget line it bills.
            if line.get("uuid"):
                await ctx.resolver.set(
                    entity_type="treatment_budget_item",
                    canonical_uuid=str(line["uuid"]),
                    source_system=source_system,
                    dienteazul_table="budget_items",
                    dienteazul_id=item.id,
                )
            if treatment_id is not None:
                treatment = await ctx.db.get(Treatment, treatment_id)
                if treatment is not None and treatment.budget_item_id is None:
                    treatment.budget_item_id = item.id

        for sign in payload.get("signatures") or []:
            ctx.db.add(
                BudgetSignature(
                    clinic_id=ctx.clinic_id,
                    budget_id=budget.id,
                    signed_at=_dt(sign.get("signed_at")),
                    **{k: v for k, v in sign.items() if k != "signed_at"},
                )
            )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="budgets",
            dienteazul_id=budget.id,
        )
        if parent_uuid and parent_id is None:
            self._parents.wait(ctx, str(parent_uuid), budget.id)
        await self._parents.arrived(ctx, Budget, "parent_budget_id", canonical_uuid, budget.id)
        await ctx.db.flush()
        return budget.id


class PatientPaymentMapper:
    """A payment, with how it was allocated and what of it was refunded."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.payments.models import Payment, PaymentAllocation, Refund

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        payment = Payment(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            amount=_money(payload["amount"]),
            currency=payload.get("currency") or "EUR",
            method=payload.get("method") or "other",
            payment_date=_d(payload.get("payment_date")) or date.today(),
            reference=payload.get("reference"),
            notes=payload.get("notes"),
            recorded_by=ctx.created_by,
        )
        if payload.get("created_at"):
            payment.created_at = _dt(payload["created_at"])
        ctx.db.add(payment)
        await ctx.db.flush()

        for share in payload.get("allocations") or []:
            budget_id = None
            target = share.get("target_type") or "on_account"
            if target == "budget":
                budget_uuid = share.get("budget_uuid")
                budget_id = (
                    await ctx.resolver.get("treatment_budget", str(budget_uuid))
                    if budget_uuid
                    else None
                )
                if budget_id is None:
                    # The budget did not come along: the money stays the
                    # patient's, on account.
                    target = "on_account"
            ctx.db.add(
                PaymentAllocation(
                    clinic_id=ctx.clinic_id,
                    payment_id=payment.id,
                    target_type=target,
                    budget_id=budget_id,
                    amount=_money(share["amount"]),
                    created_by=ctx.created_by,
                )
            )
        for refund in payload.get("refunds") or []:
            ctx.db.add(
                Refund(
                    clinic_id=ctx.clinic_id,
                    payment_id=payment.id,
                    amount=_money(refund["amount"]),
                    method=refund.get("method") or payment.method,
                    reason_code=refund.get("reason_code") or "other",
                    reason_note=refund.get("reason_note"),
                    refunded_at=_dt(refund.get("refunded_at")) or datetime.now().astimezone(),
                    refunded_by=ctx.created_by,
                )
            )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="payments",
            dienteazul_id=payment.id,
        )
        return payment.id


class EarnedEntryMapper:
    """A charge on the patient's account: what a treatment earned."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.payments.models import PatientEarnedEntry

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        treatment_uuid = payload.get("treatment_uuid")
        treatment_id = (
            await ctx.resolver.get("clinical_treatment", str(treatment_uuid))
            if treatment_uuid
            else None
        )
        catalog_uuid = payload.get("catalog_item_uuid")
        session = payload.get("source_session_id")
        entry = PatientEarnedEntry(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            treatment_id=treatment_id or _ORPHAN_TREATMENT,
            catalog_item_id=(
                await ctx.resolver.get("treatment_catalog_item", str(catalog_uuid))
                if catalog_uuid
                else None
            ),
            # Unique with the treatment; the source's own keeps it so.
            source_session_id=UUID(session) if session else UUID(canonical_uuid),
            description=payload.get("description"),
            amount=_money(payload["amount"]),
            performed_at=_dt(payload.get("performed_at")) or datetime.now().astimezone(),
            professional_id=await _profile(ctx, payload.get("professional_uuid")),
            source_event="migration_import:earned",
        )
        ctx.db.add(entry)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="patient_earned_entries",
            dienteazul_id=entry.id,
        )
        return entry.id


# --- Invoices and treatment plans -------------------------------------------
#
# An invoice comes in as a historical document: its number as issued, no
# series, so the target clinic's own numbering is untouched. Its fiscal
# fingerprint (hash, chain, compliance data) is copied only when the
# person opted in and Veri*Factu runs here — as for Gesdén's invoices.

_INVOICE_LEGAL = ("compliance_data", "document_hash", "previous_hash")


class PatientInvoiceMapper:
    def __init__(self) -> None:
        self._credited = _LaterLinks()

    FIELDS = (
        "status",
        "payment_term_days",
        "billing_name",
        "billing_tax_id",
        "billing_address",
        "billing_email",
        "internal_notes",
        "public_notes",
    )
    MONEY = ("subtotal", "total_discount", "total_tax", "total")

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.billing.models import Invoice, InvoiceItem, InvoicePayment

        from .fiscal_document import _verifactu_active

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None

        number = payload.get("invoice_number")
        if number:
            taken = await ctx.db.execute(
                select(Invoice.id).where(
                    Invoice.clinic_id == ctx.clinic_id, Invoice.invoice_number == number
                )
            )
            if taken.scalar_one_or_none() is not None:
                renamed = f"IMP-{number}"[:50]
                await _warn_native(
                    ctx,
                    entity_type,
                    source_id,
                    "number_taken",
                    f"La factura {number} ya existe en la clínica; se importa como {renamed}.",
                )
                number = renamed

        budget_uuid = payload.get("budget_uuid")
        credited_uuid = payload.get("credit_note_for_uuid")
        credited_id = (
            await ctx.resolver.get(entity_type, str(credited_uuid)) if credited_uuid else None
        )
        invoice = Invoice(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            invoice_number=number,
            budget_id=(
                await ctx.resolver.get("treatment_budget", str(budget_uuid))
                if budget_uuid
                else None
            ),
            credit_note_for_id=credited_id,
            issue_date=_d(payload.get("issue_date")),
            due_date=_d(payload.get("due_date")),
            created_by=ctx.created_by,
            # Its PDF is drawn again here, with this clinic's letterhead.
            pdf_stale=True,
            **{f: payload[f] for f in self.FIELDS if payload.get(f) is not None},
            **{f: _money(payload[f]) for f in self.MONEY if payload.get(f) is not None},
        )
        if _verifactu_active(ctx):
            for field in _INVOICE_LEGAL:
                if payload.get(field) is not None:
                    setattr(invoice, field, payload[field])
        elif any(payload.get(field) for field in _INVOICE_LEGAL):
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "fiscal_data_skipped",
                "Datos fiscales (huella Veri*Factu) no copiados: no se activó la opción "
                "fiscal o el módulo Veri*Factu no está activo.",
            )
        if payload.get("created_at"):
            invoice.created_at = _dt(payload["created_at"])
        ctx.db.add(invoice)
        await ctx.db.flush()

        for line in payload.get("items") or []:
            catalog_uuid = line.get("catalog_item_uuid")
            budget_item_uuid = line.get("budget_item_uuid")
            ctx.db.add(
                InvoiceItem(
                    clinic_id=ctx.clinic_id,
                    invoice_id=invoice.id,
                    budget_item_id=(
                        await ctx.resolver.get("treatment_budget_item", str(budget_item_uuid))
                        if budget_item_uuid
                        else None
                    ),
                    catalog_item_id=(
                        await ctx.resolver.get("treatment_catalog_item", str(catalog_uuid))
                        if catalog_uuid
                        else None
                    ),
                    description=line.get("description") or "",
                    internal_code=line.get("internal_code"),
                    unit_price=_money(line["unit_price"]),
                    quantity=int(line.get("quantity") or 1),
                    discount_type=line.get("discount_type"),
                    discount_value=_money(line.get("discount_value")),
                    vat_rate=float(line.get("vat_rate") or 0),
                    vat_exempt_reason=line.get("vat_exempt_reason"),
                    line_subtotal=_money(line["line_subtotal"]),
                    line_discount=_money(line.get("line_discount")) or Decimal(0),
                    line_tax=_money(line.get("line_tax")) or Decimal(0),
                    line_total=_money(line["line_total"]),
                    tooth_number=line.get("tooth_number"),
                    surfaces=line.get("surfaces"),
                    display_order=int(line.get("display_order") or 0),
                )
            )
        for applied in payload.get("payments") or []:
            payment_id = await ctx.resolver.get("patient_payment", str(applied["payment_uuid"]))
            if payment_id is None:
                await _warn_native(
                    ctx,
                    entity_type,
                    source_id,
                    "payment_missing",
                    "Un pago aplicado a la factura no se importó; la factura queda sin él.",
                )
                continue
            ctx.db.add(
                InvoicePayment(
                    clinic_id=ctx.clinic_id,
                    invoice_id=invoice.id,
                    payment_id=payment_id,
                    amount=_money(applied["amount"]),
                    created_by=ctx.created_by,
                )
            )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="invoices",
            dienteazul_id=invoice.id,
        )
        if credited_uuid and credited_id is None:
            self._credited.wait(ctx, str(credited_uuid), invoice.id)
        await self._credited.arrived(ctx, Invoice, "credit_note_for_id", canonical_uuid, invoice.id)
        await ctx.db.flush()
        return invoice.id


class TreatmentPlanMapper:
    """A plan with its treatments in order, their phases and sessions."""

    FIELDS = (
        "title",
        "status",
        "closure_reason",
        "closure_note",
        "diagnosis_notes",
        "prognosis",
        "prognosis_notes",
        "internal_notes",
    )

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.treatment_plan.models import (
            PlannedTreatmentItem,
            PlannedTreatmentItemSession,
            TreatmentPlan,
        )

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None

        number = payload["plan_number"]
        taken = await ctx.db.execute(
            select(TreatmentPlan.id).where(
                TreatmentPlan.clinic_id == ctx.clinic_id, TreatmentPlan.plan_number == number
            )
        )
        if taken.scalar_one_or_none() is not None:
            renamed = f"IMP-{number}"[:50]
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "number_taken",
                f"El plan {number} ya existe en la clínica; se importa como {renamed}.",
            )
            number = renamed

        budget_uuid = payload.get("budget_uuid")
        plan = TreatmentPlan(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            plan_number=number,
            budget_id=(
                await ctx.resolver.get("treatment_budget", str(budget_uuid))
                if budget_uuid
                else None
            ),
            assigned_professional_id=await _profile(ctx, payload.get("professional_uuid")),
            created_by=ctx.created_by,
            closed_at=_dt(payload.get("closed_at")),
            confirmed_at=_dt(payload.get("confirmed_at")),
            **{f: payload[f] for f in self.FIELDS if payload.get(f) is not None},
        )
        if payload.get("created_at"):
            plan.created_at = _dt(payload["created_at"])
        ctx.db.add(plan)
        await ctx.db.flush()

        for entry in payload.get("items") or []:
            treatment_id = await ctx.resolver.get(
                "clinical_treatment", str(entry["treatment_uuid"])
            )
            if treatment_id is None:
                await _warn_native(
                    ctx,
                    entity_type,
                    source_id,
                    "treatment_missing",
                    "Un tratamiento del plan no se importó; el plan queda sin él.",
                )
                continue
            item = PlannedTreatmentItem(
                clinic_id=ctx.clinic_id,
                treatment_plan_id=plan.id,
                treatment_id=treatment_id,
                phase=entry.get("phase"),
                sequence_order=int(entry.get("sequence_order") or 0),
                status=entry.get("status") or "pending",
                completed_without_appointment=bool(entry.get("completed_without_appointment")),
                completed_at=_dt(entry.get("completed_at")),
                completed_by=await _account(ctx, entry.get("completed_by_uuid")),
                assigned_professional_id=await _profile(ctx, entry.get("professional_uuid")),
                notes=entry.get("notes"),
            )
            ctx.db.add(item)
            await ctx.db.flush()
            # A prescription points at the plan line it was written from.
            if entry.get("uuid"):
                await ctx.resolver.set(
                    entity_type="treatment_plan_item",
                    canonical_uuid=str(entry["uuid"]),
                    source_system=source_system,
                    dienteazul_table="planned_treatment_items",
                    dienteazul_id=item.id,
                )
            for session in entry.get("sessions") or []:
                ctx.db.add(
                    PlannedTreatmentItemSession(
                        plan_item_id=item.id,
                        sequence=int(session["sequence"]),
                        label=session.get("label"),
                        amount=_money(session.get("amount")) or Decimal(0),
                        status=session.get("status") or "pending",
                        completed_at=_dt(session.get("completed_at")),
                        completed_by=await _account(ctx, session.get("completed_by_uuid")),
                        notes=session.get("notes"),
                    )
                )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="treatment_plans",
            dienteazul_id=plan.id,
        )
        return plan.id


# --- Clinical notes and consents ---------------------------------------------

#: A note's owner type → the entity type its owner was imported as.
_NOTE_OWNERS = {
    "patient": "patient",
    "treatment": "clinical_treatment",
    "plan": "treatment_plan",
    "appointment": "appointment",
}


class ClinicalNoteMapper:
    """A note, with the bodies it superseded and why — amendments are part
    of the record (ADR 0032) — hung from what it was written about."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.clinical_notes.models import ClinicalNote, ClinicalNoteVersion

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        owner_type = payload["owner_type"]
        owner_id = await ctx.resolver.get(_NOTE_OWNERS[owner_type], str(payload["owner_uuid"]))
        if owner_id is None:
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "owner_missing",
                f"Nota omitida: lo que acompaña ({owner_type}) no se importó.",
            )
            return None
        professional_uuid = payload.get("professional_uuid")
        note = ClinicalNote(
            clinic_id=ctx.clinic_id,
            note_type=payload["note_type"],
            owner_type=owner_type,
            owner_id=owner_id,
            tooth_number=payload.get("tooth_number"),
            body=payload["body"],
            vitals=payload.get("vitals"),
            author_id=await _account(ctx, professional_uuid) or ctx.created_by,
            authored_by_professional_id=await _profile(ctx, professional_uuid),
            version=int(payload.get("version") or 1),
            amended_at=_dt(payload.get("amended_at")),
            deleted_at=_dt(payload.get("deleted_at")),
        )
        if payload.get("created_at"):
            note.created_at = _dt(payload["created_at"])
            note.updated_at = note.created_at
        ctx.db.add(note)
        await ctx.db.flush()
        for old in payload.get("versions") or []:
            ctx.db.add(
                ClinicalNoteVersion(
                    clinic_id=ctx.clinic_id,
                    note_id=note.id,
                    version=int(old["version"]),
                    body=old["body"],
                    superseded_at=_dt(old.get("superseded_at")) or datetime.now().astimezone(),
                    superseded_by_user_id=await _account(ctx, old.get("professional_uuid"))
                    or ctx.created_by,
                    superseded_by_professional_id=await _profile(ctx, old.get("professional_uuid")),
                    amendment_reason=old.get("amendment_reason"),
                )
            )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="clinical_notes",
            dienteazul_id=note.id,
        )
        return note.id


class ConsentTemplateMapper:
    """A consent template of the source clinic, as a template of this one."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.consents.models import ConsentTemplate

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        template = ConsentTemplate(
            clinic_id=ctx.clinic_id,
            kind=payload["kind"],
            title=payload["title"],
            body=payload["body"],
            version=int(payload.get("version") or 1),
            is_active=bool(payload.get("is_active", True)),
            created_by=ctx.created_by,
        )
        ctx.db.add(template)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=ConsentTemplate.__tablename__,
            dienteazul_id=template.id,
        )
        return template.id


class PatientConsentMapper:
    """A consent letter as it was signed, declined or revoked. Who explained
    it is kept as the letter named them; a paper signature points at its
    scan, imported as a document — or, exported without documents, at
    nothing, and says so."""

    FIELDS = (
        "kind",
        "status",
        "title",
        "body",
        "template_version",
        "procedure_label",
        "explained_by_name",
        "explained_by_license",
        "signed_by_name",
        "signer_capacity",
        "signature_method",
        "regulation",
        "status_note",
    )

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.consents.models import Consent

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        signature = payload.get("signature_data")
        if signature and signature.get("document_id"):
            # A paper signature is its scan: the document it became here.
            scan = await _scan(ctx, entity_type, source_id, signature["document_id"])
            signature = {"document_id": str(scan)} if scan else None
        template_uuid = payload.get("template_uuid")
        plan_uuid = payload.get("plan_uuid")
        consent = Consent(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            template_id=(
                await ctx.resolver.get("consent_template", str(template_uuid))
                if template_uuid
                else None
            ),
            plan_id=await ctx.resolver.get("treatment_plan", str(plan_uuid)) if plan_uuid else None,
            explained_by_professional_id=await _profile(ctx, payload.get("professional_uuid")),
            signed_at=_dt(payload.get("signed_at")),
            signature_data=signature,
            declined_at=_dt(payload.get("declined_at")),
            revoked_at=_dt(payload.get("revoked_at")),
            **{f: payload[f] for f in self.FIELDS if payload.get(f) is not None},
        )
        if payload.get("created_at"):
            consent.created_at = _dt(payload["created_at"])
        ctx.db.add(consent)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=Consent.__tablename__,
            dienteazul_id=consent.id,
        )
        return consent.id


# --- Documents and health questionnaires -----------------------------------
#
# A Diente Azul export embeds each file in the ``.dpm`` (``_blobs``). The
# row naming it carries its sha256, which is hashed with the rest of the
# file, so bytes that do not match are refused. Each file goes through the
# Media module's own ``create_document`` — storage path, thumbnails,
# classification — as an upload would.


class StoredDocumentMapper:
    def __init__(self) -> None:
        self._pairs = _LaterLinks()

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        import hashlib

        from app.modules.media.models import Document
        from app.modules.media.service import DocumentService

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        data = ctx.handle.blob(canonical_uuid) if ctx.handle is not None else None
        if data is None:
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "file_missing",
                f"Documento «{payload.get('title')}» sin su archivo en el .dpm.",
            )
            return None
        if hashlib.sha256(data).hexdigest() != payload.get("sha256"):
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "file_altered",
                f"Documento «{payload.get('title')}»: el archivo no coincide con su huella; no se importa.",
            )
            return None
        document = await DocumentService.create_document(
            db=ctx.db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.created_by,
            file_data=data,
            original_filename=payload.get("original_filename")
            or payload.get("title")
            or "documento",
            mime_type=payload.get("mime_type") or "application/octet-stream",
            document_type=payload.get("document_type") or "other",
            title=payload.get("title") or "Documento",
            description=payload.get("description"),
            media_kind=payload.get("media_kind") or "document",
            media_category=payload.get("media_category"),
            media_subtype=payload.get("media_subtype"),
            captured_at=_dt(payload.get("captured_at")),
            tags=payload.get("tags") or None,
        )
        if payload.get("status"):
            document.status = payload["status"]
        if payload.get("created_at"):
            document.created_at = _dt(payload["created_at"])
        pair_uuid = payload.get("paired_document_uuid")
        if pair_uuid:
            pair_id = await ctx.resolver.get(entity_type, str(pair_uuid))
            if pair_id is not None:
                document.paired_document_id = pair_id
            else:
                self._pairs.wait(ctx, str(pair_uuid), document.id)
        await self._pairs.arrived(ctx, Document, "paired_document_id", canonical_uuid, document.id)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table="documents",
            dienteazul_id=document.id,
        )
        return document.id


async def _scan(
    ctx: MapperContext, entity_type: str, source_id: str, document_uuid: Any
) -> UUID | None:
    """The imported document a paper signature's scan became, if it came."""
    if not document_uuid:
        return None
    found = await ctx.resolver.get("stored_document", str(document_uuid))
    if found is None:
        await _warn_native(
            ctx,
            entity_type,
            source_id,
            "scan_not_carried",
            "Firmado en papel: el escaneo no viajó con el archivo; súbelo de nuevo.",
        )
    return found


class HealthQuestionnaireMapper:
    """A health questionnaire as the patient answered and signed it — on
    screen, or on paper with its scan — and the regulation it named."""

    FIELDS = (
        "form_version",
        "chief_complaint",
        "blood_type",
        "declared_allergies",
        "answers",
        "conditions",
        "drugs_detail",
        "other_conditions",
        "signed_by_name",
        "signer_capacity",
        "signature_data",
        "regulation",
        "retraction_reason",
    )

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.patients_clinical.models import HealthQuestionnaire

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        questionnaire = HealthQuestionnaire(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            taken_at=_dt(payload.get("taken_at")) or datetime.now().astimezone(),
            scan_document_id=await _scan(
                ctx, entity_type, source_id, payload.get("scan_document_uuid")
            ),
            signed_at=_dt(payload.get("signed_at")),
            ended_at=_dt(payload.get("ended_at")),
            retracted_at=_dt(payload.get("retracted_at")),
            recorded_by_professional_id=await _profile(ctx, payload.get("professional_uuid")),
            **{f: payload[f] for f in self.FIELDS if payload.get(f) is not None},
        )
        if payload.get("created_at"):
            questionnaire.created_at = _dt(payload["created_at"])
        ctx.db.add(questionnaire)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=HealthQuestionnaire.__tablename__,
            dienteazul_id=questionnaire.id,
        )
        return questionnaire.id


# --- Prescriptions, payment plans and collection contacts --------------------


class PrescriptionMapper:
    """A prescription as it was printed: the doctor's name and licence were
    copied in when it was issued, and stay as they were."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.treatment_plan.models import TreatmentPrescription

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        item_uuid = payload.get("plan_item_uuid")
        prescription = TreatmentPrescription(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            plan_item_id=(
                await ctx.resolver.get("treatment_plan_item", str(item_uuid)) if item_uuid else None
            ),
            treatment_label=payload.get("treatment_label"),
            professional_id=await _profile(ctx, payload.get("professional_uuid")),
            professional_name=payload["professional_name"],
            professional_license=payload.get("professional_license"),
            body=payload["body"],
            issued_by=await _account(ctx, payload.get("issued_by_uuid")),
        )
        if payload.get("created_at"):
            prescription.created_at = _dt(payload["created_at"])
        ctx.db.add(prescription)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=TreatmentPrescription.__tablename__,
            dienteazul_id=prescription.id,
        )
        return prescription.id


class PaymentScheduleMapper:
    """What the clinic and the patient agreed to pay, and when."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.payments.models import PaymentSchedule, PaymentScheduleInstalment

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        budget_uuid = payload.get("budget_uuid")
        schedule = PaymentSchedule(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            budget_id=(
                await ctx.resolver.get("treatment_budget", str(budget_uuid))
                if budget_uuid
                else None
            ),
            status=payload.get("status") or "active",
            notes=payload.get("notes"),
            created_by=ctx.created_by,
        )
        if payload.get("created_at"):
            schedule.created_at = _dt(payload["created_at"])
        ctx.db.add(schedule)
        await ctx.db.flush()
        for instalment in payload.get("instalments") or []:
            ctx.db.add(
                PaymentScheduleInstalment(
                    clinic_id=ctx.clinic_id,
                    schedule_id=schedule.id,
                    sequence=int(instalment["sequence"]),
                    label=instalment.get("label"),
                    due_date=_d(instalment.get("due_date")),
                    amount=_money(instalment["amount"]),
                )
            )
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=PaymentSchedule.__tablename__,
            dienteazul_id=schedule.id,
        )
        return schedule.id


class CollectionContactMapper:
    """Somebody chased the patient about money, on this day, this way."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.payments.models import CollectionContact

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        patient_id = await _patient(ctx, payload, entity_type, source_id)
        if patient_id is None:
            return None
        contact = CollectionContact(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            channel=payload.get("channel") or "other",
            note=payload.get("note"),
            contacted_by=await _account(ctx, payload.get("contacted_by_uuid")) or ctx.created_by,
        )
        # When the patient was chased is the point of the record.
        if payload.get("created_at"):
            contact.created_at = _dt(payload["created_at"])
        ctx.db.add(contact)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=CollectionContact.__tablename__,
            dienteazul_id=contact.id,
        )
        return contact.id


# --- Attachment links and change histories -------------------------------------

#: An attachment's owner type → the entity type its owner was imported as.
_ATTACHMENT_OWNERS = {
    "patient": "patient",
    "treatment": "clinical_treatment",
    "plan": "treatment_plan",
    "plan_item": "treatment_plan_item",
    "appointment": "appointment",
    "clinical_note": "clinical_note",
}


class DocumentAttachmentMapper:
    """A document attached to what it documents: a note, a treatment, a plan
    line… Both ends have to have come; the link is all this adds."""

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        from app.modules.media.models import MediaAttachment

        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        document_id = await ctx.resolver.get("stored_document", str(payload["document_uuid"]))
        owner_entity = _ATTACHMENT_OWNERS.get(payload["owner_type"])
        owner_id = (
            await ctx.resolver.get(owner_entity, str(payload["owner_uuid"]))
            if owner_entity
            else None
        )
        if document_id is None or owner_id is None:
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "end_missing",
                f"Adjunto omitido: el documento o lo que acompaña ({payload['owner_type']}) "
                "no se importó.",
            )
            return None
        attachment = MediaAttachment(
            clinic_id=ctx.clinic_id,
            document_id=document_id,
            owner_type=payload["owner_type"],
            owner_id=owner_id,
            display_order=int(payload.get("display_order") or 0),
        )
        ctx.db.add(attachment)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=MediaAttachment.__tablename__,
            dienteazul_id=attachment.id,
        )
        return attachment.id


class ChangeHistoryMapper:
    """One entry of a budget's, invoice's or plan's change history.

    Who made the change is kept when they came along as a professional;
    otherwise the entry is the importer's, and the source's name for them
    stays in the file's original record. The moment of the change is kept
    either way."""

    def __init__(
        self,
        model: Callable[[], Any],
        parent_entity: str,
        parent_column: str,
        actor_column: str,
        when_column: str,
        fields: tuple[str, ...],
        actor_required: bool,
    ) -> None:
        self._model = model
        self._parent_entity = parent_entity
        self._parent_column = parent_column
        self._actor_column = actor_column
        self._when_column = when_column
        self._fields = fields
        self._actor_required = actor_required

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        existing = await ctx.resolver.get(entity_type, canonical_uuid)
        if existing is not None:
            return existing
        parent_id = await ctx.resolver.get(self._parent_entity, str(payload["parent_uuid"]))
        if parent_id is None:
            await _warn_native(
                ctx,
                entity_type,
                source_id,
                "parent_missing",
                "Entrada de historial omitida: el documento al que pertenece no se importó.",
            )
            return None
        model = self._model()
        actor = await _account(ctx, payload.get("actor_uuid"))
        if actor is None and self._actor_required:
            actor = ctx.created_by
        row = model(
            clinic_id=ctx.clinic_id,
            **{self._parent_column: parent_id, self._actor_column: actor},
            **{f: payload.get(f) for f in self._fields},
        )
        setattr(row, self._when_column, _dt(payload.get("at")) or datetime.now().astimezone())
        ctx.db.add(row)
        await ctx.db.flush()
        await ctx.resolver.set(
            entity_type=entity_type,
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dienteazul_table=model.__tablename__,
            dienteazul_id=row.id,
        )
        return row.id


def _budget_history() -> Any:
    from app.modules.budget.models import BudgetHistory

    return BudgetHistory


def _invoice_history() -> Any:
    from app.modules.billing.models import InvoiceHistory

    return InvoiceHistory


def _plan_history() -> Any:
    from app.modules.treatment_plan.models import TreatmentPlanHistory

    return TreatmentPlanHistory


HISTORIES: dict[str, ChangeHistoryMapper] = {
    "budget_change": ChangeHistoryMapper(
        _budget_history,
        "treatment_budget",
        "budget_id",
        "changed_by",
        "changed_at",
        ("action", "previous_state", "new_state", "notes"),
        actor_required=True,
    ),
    "invoice_change": ChangeHistoryMapper(
        _invoice_history,
        "patient_invoice",
        "invoice_id",
        "changed_by",
        "changed_at",
        ("action", "previous_state", "new_state", "notes"),
        actor_required=True,
    ),
    "plan_change": ChangeHistoryMapper(
        _plan_history,
        "treatment_plan",
        "treatment_plan_id",
        "actor_user_id",
        "created_at",
        ("action", "from_status", "to_status", "payload"),
        actor_required=False,
    ),
}


#: Native entity types and their mappers.
MEDICAL_ENTRIES: dict[str, MedicalEntryMapper] = {
    "allergy": MedicalEntryMapper(
        "Allergy", "allergy", ("name", "type", "severity", "reaction", "notes")
    ),
    "medication": MedicalEntryMapper(
        "Medication",
        "medication",
        ("name", "dosage", "frequency", "start_date", "notes"),
        ("start_date",),
    ),
    "systemic_disease": MedicalEntryMapper(
        "SystemicDisease",
        "systemic_disease",
        ("name", "type", "diagnosis_date", "is_controlled", "is_critical", "medications", "notes"),
        ("diagnosis_date",),
    ),
    "surgical_history": MedicalEntryMapper(
        "SurgicalHistory",
        "surgical_history",
        ("procedure", "surgery_date", "complications", "notes"),
        ("surgery_date",),
    ),
    "family_history": MedicalEntryMapper(
        "FamilyHistory", "family_history", ("condition", "relative", "notes")
    ),
    "asa_assessment": MedicalEntryMapper(
        "AsaAssessment",
        "asa_assessment",
        ("assessed_at", "asa_class", "is_emergency", "rationale"),
        ("assessed_at",),
    ),
}
