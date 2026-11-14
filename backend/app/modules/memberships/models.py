"""Memberships module database models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin


class MembershipPlan(Base, TimestampMixin):
    """A plan the clinic offers: a fee per period and what it gives.

    Archived, never deleted: memberships point at it, and each paid period
    keeps its own copy of the terms (``MembershipPeriod.terms``), so
    editing a plan never changes what a patient already paid for.
    """

    __tablename__ = "membership_plans"
    __table_args__ = (
        CheckConstraint("fee >= 0", name="ck_membership_plan_fee_nonneg"),
        CheckConstraint("period IN ('monthly', 'annual')", name="ck_membership_plan_period"),
        CheckConstraint(
            "general_discount_percent >= 0 AND general_discount_percent <= 100",
            name="ck_membership_plan_discount_range",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="ck_membership_plan_status"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    #: ``monthly`` or ``annual``.
    period: Mapped[str] = mapped_column(String(10))
    #: Off every treatment without a benefit of its own. ``None``: none.
    general_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    status: Mapped[str] = mapped_column(String(10), default="active")

    benefits: Mapped[list["MembershipPlanBenefit"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="MembershipPlanBenefit.created_at",
    )


class MembershipPlanBenefit(Base, TimestampMixin):
    """One treatment of the catalogue the plan treats apart.

    ``included``: ``quantity`` units free per membership year. ``discount``:
    its own percentage, instead of the plan's general one.

    ``catalog_item_id`` carries no foreign key: the catalog is another App,
    reached through ``TreatmentCatalogue`` (ADR 0039).
    """

    __tablename__ = "membership_plan_benefits"
    __table_args__ = (
        UniqueConstraint("plan_id", "catalog_item_id", name="uq_membership_benefit_item"),
        CheckConstraint(
            "(kind = 'included' AND quantity >= 1 AND discount_percent IS NULL) "
            "OR (kind = 'discount' AND quantity IS NULL "
            "AND discount_percent >= 0 AND discount_percent <= 100)",
            name="ck_membership_benefit_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("membership_plans.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int | None] = mapped_column(Integer, default=None)
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)

    plan: Mapped[MembershipPlan] = relationship(back_populates="benefits")


class PatientMembership(Base, TimestampMixin):
    """A patient signed up to a plan.

    ``status`` is ``active`` or ``cancelled``; whether it is in force on a
    day is read from its paid periods (``service.state_on``). One active
    membership per patient.
    """

    __tablename__ = "patient_memberships"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'cancelled')", name="ck_patient_membership_status"),
        Index(
            "uq_patient_membership_active",
            "clinic_id",
            "patient_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    # FK allowed: `patients` is in `manifest.depends`.
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    #: The plan the next period is charged on.
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("membership_plans.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="active")
    started_on: Mapped[date] = mapped_column(Date)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    plan: Mapped[MembershipPlan] = relationship()
    periods: Mapped[list["MembershipPeriod"]] = relationship(
        back_populates="membership",
        cascade="all, delete-orphan",
        order_by="MembershipPeriod.starts_on",
    )


class MembershipPeriod(Base, TimestampMixin):
    """One fee paid: the days it covers and the terms it was paid on.

    ``payment_id`` points at the payment in the Budgets and payments App,
    without a foreign key (another App); ``None`` when that App was off.
    A period refunded in full no longer covers anything.
    """

    __tablename__ = "membership_periods"
    __table_args__ = (
        CheckConstraint("ends_on >= starts_on", name="ck_membership_period_range"),
        CheckConstraint("status IN ('paid', 'refunded')", name="ck_membership_period_status"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("patient_memberships.id", ondelete="CASCADE"), index=True
    )
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    payment_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), default=None, index=True)
    status: Mapped[str] = mapped_column(String(10), default="paid")
    #: The plan as it was when this period was paid (``service.plan_terms``).
    terms: Mapped[dict] = mapped_column(JSONB)

    membership: Mapped[PatientMembership] = relationship(back_populates="periods")


class MembershipBenefitUsage(Base, TimestampMixin):
    """An included service used: one per treatment performed.

    ``treatment_id`` (no foreign key: another App) makes consuming
    idempotent across the sessions of one treatment. ``cycle_start`` is
    the membership year it counts against.
    """

    __tablename__ = "membership_benefit_usages"
    __table_args__ = (
        UniqueConstraint("clinic_id", "treatment_id", name="uq_membership_usage_treatment"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("patient_memberships.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    treatment_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    cycle_start: Mapped[date] = mapped_column(Date)
    used_on: Mapped[date] = mapped_column(Date)
