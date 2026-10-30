"""What payments offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import CollectedPeriod, PatientDebt, ProducedBy

from .service import LedgerService, PaymentReportsService


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
