"""What payments offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.contracts import CollectedPeriod, PatientDebt, ProducedBy

from .models import PatientEarnedEntry
from .service import LedgerService, PaymentReportsService
from .workflow import MEMBERSHIP_FEE, record_payment


class PaymentsCollections:
    async def plan_has_collections(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        budget_ids: Collection[UUID],
        treatment_ids: Collection[UUID],
    ) -> bool:
        return await LedgerService.plan_has_collections(
            db, clinic_id, patient_id, list(budget_ids), list(treatment_ids)
        )


collections = PaymentsCollections()


class PaymentsCollectionReport:
    """The collection figures for a clinic-wide summary (ADR 0039).

    Plain data out: the consumer never sees this module's schemas, and
    the two fields that would cross the off-books boundary — anything
    invoiced — simply have nowhere to live in the contract.
    """

    async def collected_in_period(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        date_from: date,
        date_to: date,
    ) -> CollectedPeriod:
        summary = await PaymentReportsService.summary(
            db, clinic_id, currency, date_from, date_to, timezone
        )
        return CollectedPeriod(
            currency=summary.currency,
            collected=summary.total_collected,
            refunded=summary.total_refunded,
            net_collected=summary.net_collected,
            payment_count=summary.payment_count,
            receivable_today=summary.clinic_receivable_total,
        )

    async def produced_by_professional(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        timezone: str,
        date_from: date,
        date_to: date,
    ) -> list[ProducedBy]:
        rows = await PaymentReportsService.by_professional(
            db, clinic_id, date_from, date_to, timezone
        )
        return [
            ProducedBy(
                professional_name=row.professional_name,
                total=row.total_earned,
                count=row.count,
            )
            for row in rows
        ]

    async def patients_owing(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        minimum: Decimal,
    ) -> list[PatientDebt]:
        rows = await LedgerService.receivables(db, clinic_id)
        return [
            PatientDebt(
                patient_id=row["patient_id"],
                amount=row["receivable"],
                age_days=row["age_days"],
            )
            for row in rows
            if row["receivable"] >= minimum
        ]


collection_report = PaymentsCollectionReport()


class PaymentsMembershipFees:
    """Membership fees as payments of the patient (``MembershipFees``).

    The payment is allocated to ``membership`` and the period is booked as
    earned for the same amount: the fee shows in collections, the cash
    drawer and reports, and neither reads as credit nor cuts what the
    patient owes for treatments.
    """

    async def record(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        *,
        patient_id: UUID,
        period_id: UUID,
        amount: Decimal,
        method: str,
        payment_date: date,
        recorded_by: UUID,
        description: str,
        reference: str | None = None,
    ) -> UUID:
        currency = await db.scalar(select(Clinic.currency).where(Clinic.id == clinic_id))
        payment = await record_payment(
            db,
            clinic_id=clinic_id,
            currency=currency or "MXN",
            patient_id=patient_id,
            amount=amount,
            method=method,
            payment_date=payment_date,
            recorded_by=recorded_by,
            allocations=[{"target_type": "membership", "target_id": period_id, "amount": amount}],
            reference=reference,
            notes=description,
        )
        db.add(
            PatientEarnedEntry(
                clinic_id=clinic_id,
                patient_id=patient_id,
                treatment_id=period_id,
                description=description,
                amount=amount,
                performed_at=datetime.now(UTC),
                source_event=MEMBERSHIP_FEE,
            )
        )
        await db.flush()
        return payment.id


membership_fees = PaymentsMembershipFees()
