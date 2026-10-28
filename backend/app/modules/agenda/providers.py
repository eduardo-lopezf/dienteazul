"""What agenda offers other modules without being imported (ADR 0039)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AppointmentEntry, ProfessionalActivity, VisitNote

from .models import Appointment, AppointmentTreatment
from .presenter import present


class AgendaAppointmentBook:
    async def patients_of(
        self, db: AsyncSession, clinic_id: UUID, appointment_ids: Collection[UUID]
    ) -> dict[UUID, UUID | None]:
        if not appointment_ids:
            return {}
        result = await db.execute(
            select(Appointment.id, Appointment.patient_id).where(
                Appointment.clinic_id == clinic_id, Appointment.id.in_(appointment_ids)
            )
        )
        return {row.id: row.patient_id for row in result.all()}

    async def ids_for_patient(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> list[UUID]:
        result = await db.execute(
            select(Appointment.id).where(
                Appointment.clinic_id == clinic_id, Appointment.patient_id == patient_id
            )
        )
        return list(result.scalars().all())

    async def window(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        *,
        since: datetime,
        until: datetime,
        professional_id: UUID | None = None,
    ) -> list[AppointmentEntry]:
        """Flatten a window of the agenda for whoever renders it elsewhere.

        Built on :func:`presenter.present`, so a consumer sees exactly
        what the API shows — a patient whose App is off is missing from
        the brief here too (ADR 0037) — and no name is resolved twice.
        """
        query = (
            select(Appointment)
            .options(selectinload(Appointment.treatments))
            .where(
                Appointment.clinic_id == clinic_id,
                Appointment.start_time >= since,
                Appointment.start_time <= until,
                Appointment.status != "cancelled",
            )
            .order_by(Appointment.start_time)
        )
        if professional_id is not None:
            query = query.where(Appointment.professional_id == professional_id)
        rows = list((await db.execute(query)).scalars().all())

        entries = []
        for appointment in await present(db, clinic_id, rows):
            patient = appointment.patient
            professional = appointment.professional
            entries.append(
                AppointmentEntry(
                    id=appointment.id,
                    start_time=appointment.start_time,
                    end_time=appointment.end_time,
                    status=appointment.status,
                    updated_at=appointment.updated_at or appointment.created_at,
                    title=appointment.title,
                    treatment_type=appointment.treatment_type,
                    cabinet=appointment.cabinet,
                    patient_name=(
                        f"{patient.first_name} {patient.last_name}".strip() if patient else None
                    ),
                    professional_name=(
                        f"{professional.first_name} {professional.last_name}".strip()
                        if professional
                        else None
                    ),
                    treatment_names=tuple(
                        name
                        for link in appointment.treatments
                        # ``names`` is per locale; the clinic's UI is Spanish,
                        # and any other locale beats showing nothing.
                        if (name := link.names.get("es") or next(iter(link.names.values()), None))
                    ),
                )
            )
        return entries

    async def visit_notes(
        self, db: AsyncSession, clinic_id: UUID, planned_item_ids: Collection[UUID]
    ) -> list[VisitNote]:
        if not planned_item_ids:
            return []
        result = await db.execute(
            select(AppointmentTreatment, Appointment)
            .join(Appointment, AppointmentTreatment.appointment_id == Appointment.id)
            .where(
                AppointmentTreatment.planned_treatment_item_id.in_(planned_item_ids),
                AppointmentTreatment.notes.is_not(None),
                AppointmentTreatment.notes != "",
                Appointment.clinic_id == clinic_id,
            )
        )
        return [
            VisitNote(
                id=visit.id,
                planned_item_id=visit.planned_treatment_item_id,
                body=visit.notes or "",
                professional_id=appointment.professional_id,
                created_at=visit.created_at or appointment.created_at,
            )
            for visit, appointment in result.all()
        ]


#: Still ahead: booked and not yet seen.
_UPCOMING = ("scheduled", "confirmed")


class AgendaWorkload:
    """Each professional's appointments, for their profile (ADR 0039).

    Cancelled ones are not work: they count for nothing, and their patient
    is not one the professional sees.
    """

    async def activity(
        self, db: AsyncSession, clinic_id: UUID, professional_ids: Collection[UUID]
    ) -> dict[UUID, ProfessionalActivity]:
        if not professional_ids:
            return {}
        result = await db.execute(
            select(
                Appointment.professional_id,
                Appointment.patient_id,
                Appointment.status,
                Appointment.start_time,
            ).where(
                Appointment.clinic_id == clinic_id,
                Appointment.professional_id.in_(professional_ids),
                Appointment.status != "cancelled",
            )
        )
        now = datetime.now(UTC)
        patients: dict[UUID, set[UUID]] = defaultdict(set)
        total: dict[UUID, int] = defaultdict(int)
        upcoming: dict[UUID, int] = defaultdict(int)
        for row in result.all():
            total[row.professional_id] += 1
            if row.status in _UPCOMING and row.start_time >= now:
                upcoming[row.professional_id] += 1
            if row.patient_id is not None:
                patients[row.professional_id].add(row.patient_id)
        return {
            professional_id: ProfessionalActivity(
                patient_ids=frozenset(patients[professional_id]),
                counts={
                    "appointments": total[professional_id],
                    "appointments_upcoming": upcoming[professional_id],
                },
            )
            # Every one asked about: no appointments is a zero, not silence.
            for professional_id in professional_ids
        }


appointment_book = AgendaAppointmentBook()
workload = AgendaWorkload()
