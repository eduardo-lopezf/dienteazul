"""Payments module database models."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.budget.models import Budget
    from app.modules.patients.models import Patient


# Allowed payment methods (kept as plain list — schemas validate via Literal).
PAYMENT_METHODS = ["cash", "card", "bank_transfer", "direct_debit", "insurance", "other"]

# Allocation targets that don't require a foreign key (``on_account``)
# vs targets backed by another row (``budget``).
ALLOCATION_TARGET_TYPES = ["budget", "on_account"]

# Closed list of refund reason codes. UI shows localized labels; this is
# the storage form. ``other`` allows free-text reason_note for the long
# tail.
REFUND_REASON_CODES = [
    "duplicate",
    "overpaid",
    "treatment_cancelled",
    "dispute",
    "other",
]


class Payment(Base, TimestampMixin):
    """A patient cash-in event.

    The amount is gross. Reductions happen via ``Refund`` rows. A
    payment must be fully covered by ``PaymentAllocation`` rows whose
    amounts sum to ``Payment.amount`` (invariant enforced in the
    service layer).
    """

    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))  # snapshot of Clinic.currency
    method: Mapped[str] = mapped_column(String(30))
    payment_date: Mapped[date] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(100), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    recorded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    # Relationships
    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    patient: Mapped["Patient"] = relationship()
    recorder: Mapped["User"] = relationship(foreign_keys=[recorded_by])
    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
        order_by="PaymentAllocation.created_at",
    )
    refunds: Mapped[list["Refund"]] = relationship(
        back_populates="payment",
        order_by="Refund.refunded_at.desc()",
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        Index("idx_payments_clinic_patient", "clinic_id", "patient_id"),
        Index("idx_payments_clinic_date", "clinic_id", "payment_date"),
        Index("idx_payments_clinic_method", "clinic_id", "method"),
    )


class PaymentAllocation(Base, TimestampMixin):
    """How a payment is distributed across targets.

    Targets in v1:
    - ``budget``    — line is bound to a specific accepted budget. Used
      for anticipos and partial cobros on treatments-in-progress.
    - ``on_account``— patient credit balance with no specific budget.
      Reassignable later when an invoice is issued.

    Allocations to a specific Invoice live in the billing module's
    ``invoice_payments`` table — that link sits on the billing side so
    payments does not have to depend on billing.
    """

    __tablename__ = "payment_allocations"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )

    target_type: Mapped[str] = mapped_column(String(20))
    # FK to budgets is nullable — null when target_type == 'on_account'.
    # Stored as ``budget_id`` (not ``target_id``) so the database can
    # enforce referential integrity directly. The CHECK below couples
    # the two columns so callers can't silently corrupt state.
    budget_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("budgets.id", ondelete="RESTRICT"), nullable=True, default=None, index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    # Relationships
    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    payment: Mapped["Payment"] = relationship(back_populates="allocations")
    budget: Mapped["Budget | None"] = relationship()
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_alloc_amount_positive"),
        CheckConstraint(
            "(target_type = 'budget' AND budget_id IS NOT NULL) "
            "OR (target_type = 'on_account' AND budget_id IS NULL)",
            name="ck_alloc_target_consistency",
        ),
        Index("idx_alloc_payment", "payment_id"),
        Index("idx_alloc_clinic_budget", "clinic_id", "budget_id"),
    )

    @property
    def target_id(self) -> UUID | None:
        """Public accessor over the heterogeneous target reference."""
        if self.target_type == "budget":
            return self.budget_id
        return None


class Refund(Base, TimestampMixin):
    """Partial or full reversal of a payment.

    A full reversal is just ``Refund(amount=payment.amount)`` — there is
    no separate ``is_voided`` flag. ``Σ Refund.amount per payment`` must
    stay ``≤ Payment.amount`` (invariant enforced in the service).
    """

    __tablename__ = "refunds"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(30))  # may differ from original payment method
    reason_code: Mapped[str] = mapped_column(String(30))
    reason_note: Mapped[str | None] = mapped_column(Text, default=None)

    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refunded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    # Relationships
    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    payment: Mapped["Payment"] = relationship(back_populates="refunds")
    refunder: Mapped["User"] = relationship(foreign_keys=[refunded_by])

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refund_amount_positive"),
        Index("idx_refund_payment", "payment_id"),
        Index("idx_refund_clinic_date", "clinic_id", "refunded_at"),
    )


class PatientEarnedEntry(Base, TimestampMixin):
    """Denormalized ledger of treatments performed on a patient.

    Populated by event handlers reacting to
    ``odontogram.treatment.performed`` and
    ``treatment_plan.treatment_completed``. The unique ``treatment_id``
    constraint makes the upsert idempotent regardless of which event
    fires first — the two paths converge on the same row.

    No FK to ``treatments`` or ``catalog_items`` — payments must not
    depend on those modules. Values are snapshots from the event
    payload.
    """

    __tablename__ = "patient_earned_entries"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)

    treatment_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True))  # no FK on purpose
    catalog_item_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    # When set, this entry is one session of a multi-session treatment.
    # Idempotency key becomes (treatment_id, source_session_id); leaving
    # NULL preserves the single-session legacy behaviour.
    source_session_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, index=True
    )
    # Optional human-readable label captured from the session (e.g.
    # "Toma de medidas"). Snapshotted so the timeline can render
    # without re-querying treatment_plan.
    description: Mapped[str | None] = mapped_column(String(160), default=None)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    professional_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    source_event: Mapped[str] = mapped_column(String(50))

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    patient: Mapped["Patient"] = relationship()

    __table_args__ = (
        # Note: amount may be negative. Gesdén stores credit-note style
        # corrections (``Nota Económica``) as negative ``TtosMed.Importe``
        # rows that the migration importer needs to land so the patient
        # ledger reconciles with the source. Event-driven publishers
        # still emit positive amounts in normal flow.
        UniqueConstraint("treatment_id", "source_session_id", name="uq_earned_treatment_session"),
        Index("idx_earned_clinic_patient", "clinic_id", "patient_id"),
        Index("idx_earned_clinic_performed", "clinic_id", "performed_at"),
    )


class PaymentHistory(Base):
    """Audit log for payment lifecycle changes."""

    __tablename__ = "payment_history"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )

    action: Mapped[str] = mapped_column(String(30))  # created|allocated|reallocated|refunded
    changed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    previous_state: Mapped[dict | None] = mapped_column(JSONB, default=None)
    new_state: Mapped[dict | None] = mapped_column(JSONB, default=None)

    notes: Mapped[str | None] = mapped_column(Text, default=None)

    clinic: Mapped["Clinic"] = relationship()
    payment: Mapped["Payment"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        Index("idx_payment_history_payment", "payment_id"),
        Index("idx_payment_history_clinic_changed", "clinic_id", "changed_at"),
    )


class PaymentSchedule(Base, TimestampMixin):
    """What the clinic and the patient agreed to pay, and when.

    The earned ledger answers "what is owed for work already done". That is
    the right question for a filling and the wrong one for a 19.000 €
    orthognathic case, where the money is agreed up front — a deposit at
    signing, an instalment before surgery, the rest afterwards — and collected
    long before most of the work exists.

    A schedule is **intent**, not a debt of its own. It never adds to what the
    patient owes: both views settle against the same payments, and adding them
    together would double the amount. Read one or the other, never the sum.

    Attached to a budget when there is one — the budget is the document the
    patient accepted (ADR 0006) — and always to a patient, because a schedule
    outlives the budget it came from.
    """

    __tablename__ = "payment_schedules"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    budget_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("budgets.id"), index=True, default=None
    )

    # active | cancelled. Never deleted: an agreement that was superseded is
    # part of what happened, and reception is asked about it later.
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    patient: Mapped["Patient"] = relationship()
    instalments: Mapped[list["PaymentScheduleInstalment"]] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="PaymentScheduleInstalment.sequence",
    )

    __table_args__ = (
        Index("idx_payment_schedules_clinic_patient", "clinic_id", "patient_id"),
        Index("idx_payment_schedules_budget", "budget_id"),
    )


class PaymentScheduleInstalment(Base, TimestampMixin):
    """One agreed payment: how much, when, and what it is for.

    ``amount`` is what was agreed, and it never changes once money has been
    settled against it — the same rule the session snapshot follows. Whether
    it is paid is **derived**, not stored: payments settle the instalments in
    order, exactly as they settle earned charges, so there is no status to
    fall out of sync with the ledger.
    """

    __tablename__ = "payment_schedule_instalments"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    schedule_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_schedules.id", ondelete="CASCADE"), index=True
    )

    sequence: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(120))
    # Nullable: "before surgery" is a real milestone with no date yet.
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    schedule: Mapped["PaymentSchedule"] = relationship(back_populates="instalments")

    __table_args__ = (
        UniqueConstraint("schedule_id", "sequence", name="uq_schedule_instalment_sequence"),
        Index("idx_schedule_instalments_schedule", "schedule_id"),
    )


#: How the clinic reached the patient. Same vocabulary as the treatment
#: plan's contact log — reception does not have two ways of saying "I
#: called them", and neither should the two screens they use.
CONTACT_CHANNELS = ["call", "whatsapp", "email", "in_person", "other"]


class CollectionContact(Base, TimestampMixin):
    """Somebody chased this patient about money, on this day, this way.

    The receivables queue works without it — who owes what, oldest first —
    right up to the moment two people work it on the same morning and the
    patient is called twice before lunch. A queue with no memory of being
    worked is a queue that gets worked badly.

    Deliberately **not** attached to a treatment plan, unlike the pipeline's
    own contact log. What is owed is the patient's, not a plan's: it can
    span several plans, and it can come from work that never belonged to
    one. The conversation is with the person.

    Nothing here changes the money. A contact is a note about an attempt,
    and if the attempt worked there is a `Payment` to show for it.
    """

    __tablename__ = "collection_contacts"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)

    channel: Mapped[str] = mapped_column(String(20))
    # Free text, optional. "No coge el teléfono" is worth more in March than
    # the channel is, but forcing it would make the quick log a form.
    note: Mapped[str | None] = mapped_column(Text, default=None)

    contacted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        # The queue's question: when was each of these patients last chased.
        Index("idx_collection_contacts_clinic_patient", "clinic_id", "patient_id", "created_at"),
    )
