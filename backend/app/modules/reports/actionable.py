"""Lists a person can work through, not figures to look at.

A report says "1.057,50 pendiente de cobro". That is true and nobody can
do anything with it. These answer the next question — *which patients,
and what do I do about them* — and each row is a name with a phone
number and one obvious next action.

Three lists, chosen because each is money or care that is already
agreed and only needs somebody to pick up the phone:

* **Debe y no vuelve** — owes above a threshold and has no future
  appointment. The debt a clinic actually loses.
* **Aceptado sin agendar** — the patient said yes to a budget and never
  got a date. Work already sold.
* **Sin visita** — no appointment in N months. The recall list for
  people nobody chased.

**Boundaries.** The debt arrives through the `CollectionReport` contract
(ADR 0039) so this module still imports nothing of `payments`. Agenda,
budget and patient rows are read directly, as this module's other
services already do — those are in `manifest.integrates`. A list whose
App is off returns empty rather than failing (ADR 0037): the clinic
cannot act on what it cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import CollectionReport, provider

from .integrations import running

#: A list is a queue somebody works through, not a database export.
MAX_ROWS = 200


@dataclass(frozen=True, slots=True)
class ActionableRow:
    """One person to contact, and why.

    ``reason`` carries the list's own figure — the amount owed, the
    budget total, the months since the last visit — so a screen or a CSV
    can show why this row is here without asking a second question.
    """

    patient_id: UUID
    patient_name: str
    phone: str | None
    email: str | None
    amount: Decimal | None
    days: int | None
    detail: str | None = None


async def _patients_by_id(db: AsyncSession, ids: list[UUID]) -> dict[UUID, object]:
    """Names and contact details for the rows, when Patients is running."""
    if not ids or not running("patients"):
        return {}
    from app.modules.patients.models import Patient

    rows = (await db.execute(select(Patient).where(Patient.id.in_(ids)))).scalars()
    return {row.id: row for row in rows}


def _label(patient) -> tuple[str, str | None, str | None]:
    if patient is None:
        # Patients off, or a row whose patient was anonymised: the figure
        # is still true, so the row stays and says so.
        return ("—", None, None)
    return (
        f"{patient.last_name}, {patient.first_name}".strip(", "),
        getattr(patient, "phone", None),
        getattr(patient, "email", None),
    )


async def _patient_ids_with_future_appointments(db: AsyncSession, clinic_id: UUID) -> set[UUID]:
    """Everyone already booked. Nobody on these lists should be chased twice."""
    if not running("agenda"):
        return set()
    from app.modules.agenda.models import Appointment

    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Appointment.patient_id).where(
                Appointment.clinic_id == clinic_id,
                Appointment.start_time >= now,
                Appointment.status.in_(["scheduled", "confirmed"]),
                Appointment.patient_id.is_not(None),
            )
        )
    ).scalars()
    return {row for row in rows if row is not None}


async def owes_and_not_coming_back(
    db: AsyncSession, clinic_id: UUID, minimum: Decimal
) -> list[ActionableRow]:
    """Owes at least ``minimum`` and has no future appointment."""
    report = provider(CollectionReport)
    if report is None:
        return []

    debts = await report.patients_owing(db, clinic_id, minimum)
    booked = await _patient_ids_with_future_appointments(db, clinic_id)
    pending = [debt for debt in debts if debt.patient_id not in booked][:MAX_ROWS]

    patients = await _patients_by_id(db, [debt.patient_id for debt in pending])
    rows = []
    for debt in pending:
        name, phone, email = _label(patients.get(debt.patient_id))
        rows.append(
            ActionableRow(
                patient_id=debt.patient_id,
                patient_name=name,
                phone=phone,
                email=email,
                amount=debt.amount,
                days=debt.age_days,
            )
        )
    return rows


async def accepted_but_not_booked(db: AsyncSession, clinic_id: UUID) -> list[ActionableRow]:
    """Said yes to a budget and never got a date. Work already sold."""
    if not running("budget"):
        return []
    from app.modules.budget.models import Budget

    booked = await _patient_ids_with_future_appointments(db, clinic_id)

    accepted = (
        await db.execute(
            select(Budget)
            .where(
                Budget.clinic_id == clinic_id,
                Budget.status == "accepted",
                Budget.deleted_at.is_(None),
            )
            .order_by(Budget.updated_at.desc())
            .limit(MAX_ROWS * 2)
        )
    ).scalars()

    seen: set[UUID] = set()
    pending = []
    for budget in accepted:
        if budget.patient_id in booked or budget.patient_id in seen:
            continue
        seen.add(budget.patient_id)
        pending.append(budget)
        if len(pending) == MAX_ROWS:
            break

    patients = await _patients_by_id(db, [budget.patient_id for budget in pending])
    rows = []
    for budget in pending:
        name, phone, email = _label(patients.get(budget.patient_id))
        rows.append(
            ActionableRow(
                patient_id=budget.patient_id,
                patient_name=name,
                phone=phone,
                email=email,
                amount=budget.total,
                days=None,
                detail=budget.budget_number,
            )
        )
    return rows


async def no_visit_in_months(db: AsyncSession, clinic_id: UUID, months: int) -> list[ActionableRow]:
    """Nobody has seen them in ``months``, and nothing is booked.

    Counted from the last appointment that actually happened: a patient
    whose only recent appointment was cancelled has not been seen.
    """
    if not running("agenda") or not running("patients"):
        return []
    from app.modules.agenda.models import Appointment

    cutoff = datetime.now(UTC) - timedelta(days=30 * months)
    booked = await _patient_ids_with_future_appointments(db, clinic_id)

    last_seen = (
        await db.execute(
            select(
                Appointment.patient_id,
                func.max(Appointment.start_time).label("last_visit"),
            )
            .where(
                Appointment.clinic_id == clinic_id,
                Appointment.status == "completed",
                Appointment.patient_id.is_not(None),
            )
            .group_by(Appointment.patient_id)
        )
    ).all()

    stale = [row for row in last_seen if row.last_visit < cutoff and row.patient_id not in booked]
    stale.sort(key=lambda row: row.last_visit)
    stale = stale[:MAX_ROWS]

    patients = await _patients_by_id(db, [row.patient_id for row in stale])
    now = datetime.now(UTC)
    rows = []
    for row in stale:
        name, phone, email = _label(patients.get(row.patient_id))
        rows.append(
            ActionableRow(
                patient_id=row.patient_id,
                patient_name=name,
                phone=phone,
                email=email,
                amount=None,
                days=(now - row.last_visit).days,
            )
        )
    return rows
