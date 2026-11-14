"""Plans a clinic signs its patients up to, their fees and what they give."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import contracts
from app.core.auth.models import Clinic
from app.core.contracts import (
    CatalogItemBrief,
    MemberDiscount,
    MembershipFees,
    TreatmentCatalogue,
)
from app.core.events import EventType, event_bus
from app.core.plugins.apps import optional_modules_on
from app.modules.patients.models import Patient

from .models import (
    MembershipBenefitUsage,
    MembershipPeriod,
    MembershipPlan,
    MembershipPlanBenefit,
    PatientMembership,
)

#: Days after a paid period ends during which its benefits still apply,
#: so a fee paid a few days late does not leave the patient uncovered.
GRACE_DAYS = 7

HUNDRED = Decimal("100")


class MembershipError(ValueError):
    """A refusal the caller can fix. The message maps to an error code."""


async def switched_on(db: AsyncSession, clinic_id: UUID) -> bool:
    """Whether the clinic has this module on (ADR 0066): an optional module
    of the Patients App, off until its administrator switches it on."""
    clinic = await db.scalar(select(Clinic).where(Clinic.id == clinic_id))
    if clinic is None:
        return False
    return "memberships" in optional_modules_on(clinic.modules, clinic.account_tier)


# --- Dates ----------------------------------------------------------------


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_end(starts_on: date, period: str) -> date:
    """Last day a fee paid from ``starts_on`` covers."""
    return _add_months(starts_on, 12 if period == "annual" else 1) - timedelta(days=1)


def cycle_start(started_on: date, on: date) -> date:
    """The start of the membership year ``on`` falls in.

    Included services count per membership year, however often the fee
    is paid: "two cleanings" on a monthly plan is two a year, not two a
    month.
    """
    years = on.year - started_on.year
    start = _add_months(started_on, 12 * years)
    if start > on:
        start = _add_months(started_on, 12 * (years - 1))
    return start


def today() -> date:
    return datetime.now(UTC).date()


# --- Terms ----------------------------------------------------------------


def plan_terms(plan: MembershipPlan) -> dict:
    """The plan as a paid period keeps it: editing it later changes nothing
    already paid for."""
    return {
        "plan_id": str(plan.id),
        "plan_name": plan.name,
        "fee": str(plan.fee),
        "period": plan.period,
        "general_discount_percent": (
            str(plan.general_discount_percent)
            if plan.general_discount_percent is not None
            else None
        ),
        "benefits": [
            {
                "catalog_item_id": str(b.catalog_item_id),
                "kind": b.kind,
                "quantity": b.quantity,
                "discount_percent": (
                    str(b.discount_percent) if b.discount_percent is not None else None
                ),
            }
            for b in plan.benefits
        ],
    }


def discount_from_terms(
    terms: dict, catalog_item_id: UUID, used_in_cycle: int
) -> MemberDiscount | None:
    """What ``terms`` take off one treatment, with ``used_in_cycle`` of its
    included units already used this membership year."""
    plan_name = terms["plan_name"]
    benefit = next(
        (b for b in terms["benefits"] if b["catalog_item_id"] == str(catalog_item_id)), None
    )
    if benefit is not None and benefit["kind"] == "included":
        if used_in_cycle < benefit["quantity"]:
            return MemberDiscount(percent=HUNDRED, included=True, plan_name=plan_name)
    elif benefit is not None:
        return MemberDiscount(
            percent=Decimal(benefit["discount_percent"]), included=False, plan_name=plan_name
        )
    general = terms.get("general_discount_percent")
    if general is not None and Decimal(general) > 0:
        return MemberDiscount(percent=Decimal(general), included=False, plan_name=plan_name)
    return None


# --- Membership state -----------------------------------------------------


def covering_period(membership: PatientMembership, on: date) -> MembershipPeriod | None:
    """The paid period whose benefits apply on ``on``.

    An active membership keeps them for :data:`GRACE_DAYS` after the last
    paid day; a cancelled one only to the last paid day.
    """
    grace = timedelta(days=GRACE_DAYS if membership.status == "active" else 0)
    for period in sorted(membership.periods, key=lambda p: p.starts_on, reverse=True):
        if period.status != "paid":
            continue
        if period.starts_on <= on <= period.ends_on + grace:
            return period
    return None


def paid_through(membership: PatientMembership) -> date | None:
    ends = [p.ends_on for p in membership.periods if p.status == "paid"]
    return max(ends) if ends else None


def state_on(membership: PatientMembership, on: date) -> str:
    """``active`` (benefits apply), ``expired`` (fee overdue) or ``cancelled``."""
    if covering_period(membership, on) is not None:
        return "active"
    return "cancelled" if membership.status == "cancelled" else "expired"


@dataclass(frozen=True, slots=True)
class FeePayment:
    method: str
    payment_date: date
    reference: str | None = None


# --- Plans ----------------------------------------------------------------


async def treatments(
    db: AsyncSession, clinic_id: UUID, ids: set[UUID] | None = None
) -> dict[UUID, CatalogItemBrief]:
    """Catalogue treatments by id: those in ``ids``, or every active one.
    Empty while the Treatments App is off."""
    catalogue = contracts.provider(TreatmentCatalogue)
    if catalogue is None:
        return {}
    if ids is None:
        return {b.id: b for b in await catalogue.list_active(db, clinic_id)}
    if not ids:
        return {}
    return dict(await catalogue.briefs(db, clinic_id, ids))


class PlanService:
    @staticmethod
    async def list(
        db: AsyncSession, clinic_id: UUID, include_archived: bool = False
    ) -> list[MembershipPlan]:
        query = (
            select(MembershipPlan)
            .options(selectinload(MembershipPlan.benefits))
            .where(MembershipPlan.clinic_id == clinic_id)
            .order_by(MembershipPlan.name)
        )
        if not include_archived:
            query = query.where(MembershipPlan.status == "active")
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, plan_id: UUID) -> MembershipPlan:
        plan = await db.scalar(
            select(MembershipPlan)
            .options(selectinload(MembershipPlan.benefits))
            .where(MembershipPlan.id == plan_id, MembershipPlan.clinic_id == clinic_id)
            .execution_options(populate_existing=True)
        )
        if plan is None:
            raise MembershipError("That plan is not in this clinic.")
        return plan

    @staticmethod
    async def _check_benefits(
        db: AsyncSession, clinic_id: UUID, benefits: list[dict], kept: set[UUID]
    ) -> None:
        ids = [b["catalog_item_id"] for b in benefits]
        if len(ids) != len(set(ids)):
            raise MembershipError("A treatment can only appear once in a plan.")
        new = set(ids) - kept
        if not new:
            return
        if contracts.provider(TreatmentCatalogue) is None:
            raise MembershipError("Benefits need the Treatments app.")
        known = await treatments(db, clinic_id, new)
        if new - known.keys():
            raise MembershipError("That treatment is not in this clinic's catalogue.")

    @staticmethod
    def _set_fields(plan: MembershipPlan, clinic_id: UUID, data: dict) -> None:
        plan.name = data["name"].strip()
        plan.description = data.get("description")
        plan.fee = data["fee"]
        plan.period = data["period"]
        plan.general_discount_percent = data.get("general_discount_percent")
        plan.benefits = [
            MembershipPlanBenefit(
                clinic_id=clinic_id,
                catalog_item_id=b["catalog_item_id"],
                kind=b["kind"],
                quantity=b.get("quantity") if b["kind"] == "included" else None,
                discount_percent=b.get("discount_percent") if b["kind"] == "discount" else None,
            )
            for b in data.get("benefits") or []
        ]

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, data: dict) -> MembershipPlan:
        await PlanService._check_benefits(db, clinic_id, data.get("benefits") or [], set())
        plan = MembershipPlan(clinic_id=clinic_id, status="active", benefits=[])
        PlanService._set_fields(plan, clinic_id, data)
        db.add(plan)
        await db.flush()
        return await PlanService.get(db, clinic_id, plan.id)

    @staticmethod
    async def replace(
        db: AsyncSession, clinic_id: UUID, plan_id: UUID, data: dict
    ) -> MembershipPlan:
        """Edit the whole plan. Periods already paid keep their own terms."""
        plan = await PlanService.get(db, clinic_id, plan_id)
        kept = {b.catalog_item_id for b in plan.benefits}
        await PlanService._check_benefits(db, clinic_id, data.get("benefits") or [], kept)
        plan.benefits.clear()
        await db.flush()
        PlanService._set_fields(plan, clinic_id, data)
        await db.flush()
        return await PlanService.get(db, clinic_id, plan.id)

    @staticmethod
    async def set_status(
        db: AsyncSession, clinic_id: UUID, plan_id: UUID, status: str
    ) -> MembershipPlan:
        """Archive (no new sign-ups or renewals on it) or restore a plan."""
        plan = await PlanService.get(db, clinic_id, plan_id)
        plan.status = status
        await db.flush()
        return plan


# --- Memberships ----------------------------------------------------------


def _membership_query(clinic_id: UUID):
    return (
        select(PatientMembership)
        .options(
            selectinload(PatientMembership.periods),
            selectinload(PatientMembership.plan).selectinload(MembershipPlan.benefits),
        )
        .where(PatientMembership.clinic_id == clinic_id)
        .execution_options(populate_existing=True)
    )


class MembershipService:
    @staticmethod
    async def for_patient(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> PatientMembership | None:
        """The patient's active membership or, failing that, the last one."""
        result = await db.execute(
            _membership_query(clinic_id)
            .where(PatientMembership.patient_id == patient_id)
            .order_by(
                (PatientMembership.status == "active").desc(),
                PatientMembership.started_on.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, membership_id: UUID) -> PatientMembership:
        membership = await db.scalar(
            _membership_query(clinic_id).where(PatientMembership.id == membership_id)
        )
        if membership is None:
            raise MembershipError("That membership is not in this clinic.")
        return membership

    @staticmethod
    async def used_in_cycle(
        db: AsyncSession, membership: PatientMembership, on: date
    ) -> dict[UUID, int]:
        """Included units used this membership year, by treatment of the catalogue."""
        rows = await db.execute(
            select(MembershipBenefitUsage.catalog_item_id, func.count())
            .where(
                MembershipBenefitUsage.clinic_id == membership.clinic_id,
                MembershipBenefitUsage.membership_id == membership.id,
                MembershipBenefitUsage.cycle_start == cycle_start(membership.started_on, on),
            )
            .group_by(MembershipBenefitUsage.catalog_item_id)
        )
        return {item_id: count for item_id, count in rows.all()}

    @staticmethod
    async def _active_plan(db: AsyncSession, clinic_id: UUID, plan_id: UUID) -> MembershipPlan:
        plan = await PlanService.get(db, clinic_id, plan_id)
        if plan.status != "active":
            raise MembershipError("That plan is archived.")
        return plan

    @staticmethod
    async def enroll(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        *,
        plan_id: UUID,
        starts_on: date,
        payment: FeePayment,
        user_id: UUID,
    ) -> PatientMembership:
        """Sign the patient up and collect the first fee."""
        patient = await db.scalar(
            select(Patient.id).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
        )
        if patient is None:
            raise MembershipError("That patient is not in this clinic.")
        existing = await db.scalar(
            select(PatientMembership.id).where(
                PatientMembership.clinic_id == clinic_id,
                PatientMembership.patient_id == patient_id,
                PatientMembership.status == "active",
            )
        )
        if existing is not None:
            raise MembershipError("The patient already has an active membership.")
        plan = await MembershipService._active_plan(db, clinic_id, plan_id)

        membership = PatientMembership(
            clinic_id=clinic_id,
            patient_id=patient_id,
            plan_id=plan.id,
            status="active",
            started_on=starts_on,
        )
        db.add(membership)
        await db.flush()
        period = await MembershipService._add_period(
            db, membership, plan, starts_on, payment, user_id
        )
        event_bus.publish_after_commit(
            db,
            EventType.MEMBERSHIP_ENROLLED,
            {
                "clinic_id": str(clinic_id),
                "membership_id": str(membership.id),
                "patient_id": str(patient_id),
                "plan_id": str(plan.id),
                "starts_on": starts_on.isoformat(),
            },
        )
        _publish_period_paid(db, membership, period)
        return await MembershipService.get(db, clinic_id, membership.id)

    @staticmethod
    async def renew(
        db: AsyncSession,
        clinic_id: UUID,
        membership_id: UUID,
        *,
        payment: FeePayment,
        user_id: UUID,
    ) -> PatientMembership:
        """Collect the next fee. Follows on from the last paid day; a
        membership that lapsed past its grace starts again on the day paid."""
        membership = await MembershipService.get(db, clinic_id, membership_id)
        if membership.status != "active":
            raise MembershipError("That membership is cancelled.")
        plan = await MembershipService._active_plan(db, clinic_id, membership.plan_id)
        last = paid_through(membership)
        if last is None or last + timedelta(days=GRACE_DAYS) < payment.payment_date:
            starts_on = payment.payment_date
        else:
            starts_on = last + timedelta(days=1)
        period = await MembershipService._add_period(
            db, membership, plan, starts_on, payment, user_id
        )
        _publish_period_paid(db, membership, period)
        return await MembershipService.get(db, clinic_id, membership.id)

    @staticmethod
    async def _add_period(
        db: AsyncSession,
        membership: PatientMembership,
        plan: MembershipPlan,
        starts_on: date,
        payment: FeePayment,
        user_id: UUID,
    ) -> MembershipPeriod:
        ends_on = period_end(starts_on, plan.period)
        period = MembershipPeriod(
            clinic_id=membership.clinic_id,
            membership_id=membership.id,
            starts_on=starts_on,
            ends_on=ends_on,
            amount=plan.fee,
            refunded_amount=Decimal("0"),
            status="paid",
            terms=plan_terms(plan),
        )
        db.add(period)
        await db.flush()

        fees = contracts.provider(MembershipFees)
        if fees is not None and plan.fee > 0:
            period.payment_id = await fees.record(
                db,
                membership.clinic_id,
                patient_id=membership.patient_id,
                period_id=period.id,
                amount=plan.fee,
                method=payment.method,
                payment_date=payment.payment_date,
                recorded_by=user_id,
                description=(f"Membresía {plan.name} ({starts_on:%d/%m/%Y} – {ends_on:%d/%m/%Y})")[
                    :160
                ],
                reference=payment.reference,
            )
            await db.flush()
        return period

    @staticmethod
    async def change_plan(
        db: AsyncSession, clinic_id: UUID, membership_id: UUID, plan_id: UUID
    ) -> PatientMembership:
        """Charge the next periods on another plan. The paid ones keep theirs."""
        membership = await MembershipService.get(db, clinic_id, membership_id)
        if membership.status != "active":
            raise MembershipError("That membership is cancelled.")
        plan = await MembershipService._active_plan(db, clinic_id, plan_id)
        membership.plan_id = plan.id
        await db.flush()
        return await MembershipService.get(db, clinic_id, membership.id)

    @staticmethod
    async def cancel(db: AsyncSession, clinic_id: UUID, membership_id: UUID) -> PatientMembership:
        """Stop renewing. Benefits stay until the last paid day."""
        membership = await MembershipService.get(db, clinic_id, membership_id)
        if membership.status != "active":
            raise MembershipError("That membership is cancelled.")
        membership.status = "cancelled"
        membership.cancelled_at = datetime.now(UTC)
        await db.flush()
        event_bus.publish_after_commit(
            db,
            EventType.MEMBERSHIP_CANCELLED,
            {
                "clinic_id": str(clinic_id),
                "membership_id": str(membership.id),
                "patient_id": str(membership.patient_id),
                "paid_through": (
                    paid_through(membership).isoformat() if paid_through(membership) else None
                ),
            },
        )
        return await MembershipService.get(db, clinic_id, membership.id)

    @staticmethod
    async def fee_refunded(
        db: AsyncSession, clinic_id: UUID, payment_id: UUID, amount: Decimal
    ) -> MembershipPeriod | None:
        """A fee's payment was refunded. Refunded in full, the period it paid
        no longer covers anything."""
        period = await db.scalar(
            select(MembershipPeriod).where(
                MembershipPeriod.clinic_id == clinic_id,
                MembershipPeriod.payment_id == payment_id,
            )
        )
        if period is None:
            return None
        period.refunded_amount = period.refunded_amount + amount
        if period.refunded_amount >= period.amount:
            period.status = "refunded"
        await db.flush()
        return period


def _publish_period_paid(
    db: AsyncSession, membership: PatientMembership, period: MembershipPeriod
) -> None:
    event_bus.publish_after_commit(
        db,
        EventType.MEMBERSHIP_PERIOD_PAID,
        {
            "clinic_id": str(membership.clinic_id),
            "membership_id": str(membership.id),
            "period_id": str(period.id),
            "patient_id": str(membership.patient_id),
            "amount": str(period.amount),
            "starts_on": period.starts_on.isoformat(),
            "ends_on": period.ends_on.isoformat(),
            "payment_id": str(period.payment_id) if period.payment_id else None,
        },
    )


# --- Benefits (the ``MemberBenefits`` contract) ---------------------------


class BenefitService:
    @staticmethod
    async def _in_force(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, on: date
    ) -> tuple[PatientMembership, MembershipPeriod] | None:
        if not await switched_on(db, clinic_id):
            return None
        membership = await MembershipService.for_patient(db, clinic_id, patient_id)
        if membership is None:
            return None
        period = covering_period(membership, on)
        return (membership, period) if period is not None else None

    @staticmethod
    async def discount_for(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID, catalog_item_id: UUID, on: date
    ) -> MemberDiscount | None:
        found = await BenefitService._in_force(db, clinic_id, patient_id, on)
        if found is None:
            return None
        membership, period = found
        used = await MembershipService.used_in_cycle(db, membership, on)
        return discount_from_terms(period.terms, catalog_item_id, used.get(catalog_item_id, 0))

    @staticmethod
    async def apply(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        catalog_item_id: UUID,
        treatment_id: UUID,
        on: date,
    ) -> MemberDiscount | None:
        already = await db.scalar(
            select(MembershipBenefitUsage).where(
                MembershipBenefitUsage.clinic_id == clinic_id,
                MembershipBenefitUsage.treatment_id == treatment_id,
            )
        )
        if already is not None:
            # Another session of the same treatment: the unit is already its.
            membership = await MembershipService.get(db, clinic_id, already.membership_id)
            return MemberDiscount(percent=HUNDRED, included=True, plan_name=membership.plan.name)

        found = await BenefitService._in_force(db, clinic_id, patient_id, on)
        if found is None:
            return None
        membership, period = found
        used = await MembershipService.used_in_cycle(db, membership, on)
        discount = discount_from_terms(period.terms, catalog_item_id, used.get(catalog_item_id, 0))
        if discount is not None and discount.included:
            await db.execute(
                pg_insert(MembershipBenefitUsage)
                .values(
                    clinic_id=clinic_id,
                    membership_id=membership.id,
                    catalog_item_id=catalog_item_id,
                    treatment_id=treatment_id,
                    cycle_start=cycle_start(membership.started_on, on),
                    used_on=on,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="uq_membership_usage_treatment")
            )
        return discount

    @staticmethod
    async def release(db: AsyncSession, clinic_id: UUID, treatment_id: UUID) -> None:
        await db.execute(
            delete(MembershipBenefitUsage).where(
                MembershipBenefitUsage.clinic_id == clinic_id,
                MembershipBenefitUsage.treatment_id == treatment_id,
            )
        )
