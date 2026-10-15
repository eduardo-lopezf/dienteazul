"""Treatment plan module database models.

Note: clinical-notes models live in the ``clinical_notes`` module since
issue #60. The ``clinical_notes`` and ``clinical_note_attachments`` tables
remain in the database, but ownership of the schema/migrations moved.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.core.privacy import PiiKind, pii
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.catalog.models import TreatmentCatalogItem
    from app.modules.odontogram.models import Treatment
    from app.modules.patients.models import Patient


class TreatmentPlan(Base, TimestampMixin):
    """Treatment plan that groups treatments for a patient.

    Orchestrates the patient workflow by linking treatments from the odontogram
    with budgets and appointments. Communicates with other modules via event bus.
    """

    __tablename__ = "treatment_plans"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)

    # Identification
    plan_number: Mapped[str] = mapped_column(String(50))  # PLAN-2024-0001
    title: Mapped[str | None] = mapped_column(String(200))

    # Status workflow: draft → pending → active → completed → archived
    # Terminal non-completed state: closed (with closure_reason). Reactivable
    # back to draft. See ADR 0006 and docs/workflows/plan-budget-flow.md.
    status: Mapped[str] = mapped_column(String(20), default="draft")

    # Closure metadata (set when status becomes ``closed``).
    # Allowed closure_reason values:
    #   rejected_by_patient | expired | cancelled_by_clinic |
    #   patient_abandoned  | other
    closure_reason: Mapped[str | None] = mapped_column(String(50))
    closure_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Confirmation timestamp (set on draft → pending). Used for
    # pipeline analytics and "days waiting" sorting.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Budget integration (one-to-one)
    budget_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("budgets.id"), unique=True, index=True
    )

    # Assignments
    assigned_professional_id: Mapped[UUID | None] = mapped_column(ForeignKey("professionals.id"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    # Clinical notes
    diagnosis_notes: Mapped[str | None] = mapped_column(Text)
    #: How the professional expects it to go: ``favorable``, ``reserved``
    #: or ``unfavorable``, and why. Sits with the diagnosis it follows from.
    prognosis: Mapped[str | None] = mapped_column(String(20))
    prognosis_notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)

    # Soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    patient: Mapped["Patient"] = relationship()
    # Not a relationship: the plan does not load another App's rows. A
    # ``contracts.BudgetBrief`` put here per request by
    # ``TreatmentPlanService`` from the ``PlanBudgets`` contract (ADR 0039),
    # or None when there is no budget or the Budgets App is off.
    budget = None
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    items: Mapped[list["PlannedTreatmentItem"]] = relationship(
        back_populates="treatment_plan",
        cascade="all, delete-orphan",
        order_by="PlannedTreatmentItem.sequence_order",
    )

    __table_args__ = (
        UniqueConstraint("clinic_id", "plan_number", name="uq_treatment_plan_number"),
        Index("idx_treatment_plans_patient", "patient_id"),
        Index("idx_treatment_plans_status", "clinic_id", "status"),
        Index("idx_treatment_plans_budget", "budget_id"),
        # Tab "Cerrados" of the pipeline filters by closed_at desc.
        Index(
            "idx_treatment_plans_clinic_status_closed",
            "clinic_id",
            "status",
            "closed_at",
        ),
    )


class PlannedTreatmentItem(Base, TimestampMixin):
    """Individual treatment within a plan.

    Always references a single Treatment (from the odontogram module). Globalness,
    per-tooth / multi-tooth, pricing and catalog link all live on the Treatment.
    """

    __tablename__ = "planned_treatment_items"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    treatment_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatment_plans.id", ondelete="CASCADE"), index=True
    )

    # Single link to Treatment. Unique: no two items may reference the same Treatment.
    treatment_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatments.id", ondelete="CASCADE"), index=True
    )

    # Stage of care for this item, seeded from the catalog item's
    # `default_phase` but decided here: the same extraction is an emergency
    # for one patient and a planned rehabilitation step for another.
    # Values: app.modules.catalog.models.TREATMENT_PHASES.
    phase: Mapped[str | None] = mapped_column(String(20), default=None, index=True)

    # Ordering and status
    sequence_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending|completed|cancelled

    # Completion tracking
    completed_without_appointment: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    # Doctor responsible for performing this treatment line. Snapshot from the
    # plan's assigned_professional_id at creation time; once set it is
    # independent — changing the plan-level doctor does not cascade here unless
    # the caller passes ``reassign_pending_items=True`` on the plan update.
    assigned_professional_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("professionals.id"), nullable=True, index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    treatment_plan: Mapped["TreatmentPlan"] = relationship(back_populates="items")
    treatment: Mapped["Treatment"] = relationship()
    completer: Mapped["User | None"] = relationship(foreign_keys=[completed_by])
    sessions: Mapped[list["PlannedTreatmentItemSession"]] = relationship(
        back_populates="plan_item",
        cascade="all, delete-orphan",
        order_by="PlannedTreatmentItemSession.sequence",
    )

    __table_args__ = (
        UniqueConstraint("treatment_id", name="uq_planned_item_treatment"),
        Index("idx_planned_items_plan", "treatment_plan_id"),
        Index("idx_planned_items_treatment", "treatment_id"),
        Index("idx_planned_items_status", "treatment_plan_id", "status"),
        Index(
            "idx_planned_items_plan_professional",
            "treatment_plan_id",
            "assigned_professional_id",
        ),
    )


class PlannedTreatmentItemSession(Base, TimestampMixin):
    """One billable / executable step of a ``PlannedTreatmentItem``.

    Snapshotted from ``CatalogItemSession`` at plan-add time. After
    creation the session is independent — editing the catalog template
    does not retro-affect existing plan instances. Once a session is
    marked ``completed`` its label and amount are immutable.
    """

    __tablename__ = "planned_treatment_item_sessions"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    plan_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("planned_treatment_items.id", ondelete="CASCADE"), index=True
    )

    sequence: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending|completed|cancelled

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    plan_item: Mapped["PlannedTreatmentItem"] = relationship(back_populates="sessions")
    completer: Mapped["User | None"] = relationship(foreign_keys=[completed_by])

    __table_args__ = (
        UniqueConstraint("plan_item_id", "sequence", name="uq_plan_item_session_sequence"),
        Index("idx_pti_session_plan_item", "plan_item_id"),
        Index("ix_pti_session_plan_item_status", "plan_item_id", "status"),
    )


class PlanTemplate(Base, TimestampMixin):
    """A reusable shape of a treatment plan.

    Clinical plans are not invented one by one — a practice runs a handful of
    recurring shapes (primera visita, fase higiénica, endo + reconstrucción +
    corona, implante unitario) and rebuilds them by hand every time. A template
    is that shape: an ordered list of catalog items with their stage of care.

    What a template deliberately does **not** carry is teeth. A template that
    fixed tooth 16 would be useless on the next patient; the teeth are supplied
    when the template is applied (see ``PlanTemplateService.apply``).

    Templates are per-clinic. ``key`` is set only on the starter set shipped
    with the module, so re-seeding can match an existing row instead of
    duplicating it; templates a clinic creates itself leave it NULL.
    """

    __tablename__ = "plan_templates"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    # Stable identifier for the shipped starter set; NULL for clinic-authored
    # templates. Re-seeding matches on it, so it must never be reused.
    key: Mapped[str | None] = mapped_column(String(50), default=None)

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    # Soft delete: a template that built existing plans stays referenced in
    # nothing, but hiding beats deleting for something a clinic curates.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    clinic: Mapped["Clinic"] = relationship()
    items: Mapped[list["PlanTemplateItem"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PlanTemplateItem.sequence",
    )

    __table_args__ = (
        UniqueConstraint("clinic_id", "key", name="uq_plan_template_clinic_key"),
        Index("idx_plan_templates_clinic_active", "clinic_id", "is_active"),
    )


class PlanTemplateItem(Base, TimestampMixin):
    """One line of a ``PlanTemplate``: a catalog item and where it sits.

    ``phase`` overrides the catalog item's ``default_phase`` for this template
    only — the same crown is rehabilitation in one shape and an emergency
    provisional in another. NULL means "whatever the catalog says".
    """

    __tablename__ = "plan_template_items"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("plan_templates.id", ondelete="CASCADE"), index=True
    )

    sequence: Mapped[int] = mapped_column(Integer)
    catalog_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatment_catalog_items.id", ondelete="CASCADE"), index=True
    )

    # See app.modules.catalog.models.TREATMENT_PHASES. NULL → catalog default.
    phase: Mapped[str | None] = mapped_column(String(20), default=None)

    # A line the clinic may not offer, or the patient may not need — the
    # orthodontics of an orthognathic case, a genioplasty. Offered ticked when
    # the template is applied, because the author put it there for a reason;
    # one click removes it.
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)

    notes: Mapped[str | None] = mapped_column(Text)

    template: Mapped["PlanTemplate"] = relationship(back_populates="items")
    catalog_item: Mapped["TreatmentCatalogItem"] = relationship()

    __table_args__ = (
        UniqueConstraint("template_id", "sequence", name="uq_plan_template_item_sequence"),
        Index("idx_plan_template_items_template", "template_id"),
    )


class TreatmentPlanHistory(Base):
    """Who changed a plan, what they changed, and when.

    A plan is a contract with the patient and its price moves with it, so
    "the budget says something different from what I remember agreeing"
    has to be answerable. The budget already keeps ``budget_history``;
    this is the plan side of the same idea.

    Append-only by convention: rows are written by the service on every
    transition, item mutation and reassignment, and nothing updates or
    deletes them. ``actor_user_id`` is the account that acted — the
    professional the work is attributed to lives in ``payload`` when it
    is part of what changed, because the two are not the same thing
    (see the module CLAUDE.md on directory profiles vs accounts).
    """

    __tablename__ = "treatment_plan_history"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    treatment_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatment_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Short verb: confirmed | reopened | closed | reactivated | item_added |
    # item_removed | item_completed | reassigned | budget_synced
    action: Mapped[str] = mapped_column(String(40), nullable=False)

    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))

    # Free-shaped detail for the action: the treatment that moved, the
    # professional a plan was handed to, the budget that was cancelled.
    # Read for display only — never branched on.
    payload: Mapped[dict | None] = mapped_column(JSONB)

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_user_id])

    __table_args__ = (Index("idx_tp_history_plan_created", "treatment_plan_id", "created_at"),)


class PlanDismissedFinding(Base, TimestampMixin):
    """A charted finding the dentist decided this plan does not answer.

    The builder seeds its draft lines from the patient's findings, so deleting
    one of those lines is a judgement, not a typo: *I saw the caries on 27 and
    this plan is not for it*. Recorded, or the plan's own proposals list offers
    it straight back and the dentist answers the same question twice.

    **Scoped to the plan, deliberately.** It says nothing about the finding —
    the chart keeps showing the caries until it is treated, and the next plan
    proposes it again. A decision about one plan must not silently become a
    decision to leave a tooth alone forever.
    """

    __tablename__ = "plan_dismissed_findings"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    treatment_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatment_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The odontogram `Treatment` row holding the finding. `odontogram` is in
    # this module's `depends`, so the FK is allowed.
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatments.id", ondelete="CASCADE"), nullable=False
    )
    dismissed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        UniqueConstraint("treatment_plan_id", "finding_id", name="uq_plan_dismissed_finding"),
    )


class TreatmentPrescription(Base, TimestampMixin):
    """A prescription written from one treatment of a plan.

    A printed prescription is a legal document with the doctor's name and
    licence on it, so both are **copied in** when it is issued: a doctor
    renamed or re-licensed later must not change what a patient already
    carried to the pharmacy. Reprinting gives the same doctor block.

    ``plan_item_id`` is ``SET NULL`` rather than ``CASCADE``: removing a
    treatment from a plan is a hard delete, and the prescription written for
    it is clinical history that has to outlive the line. ``treatment_label``
    keeps it readable once the line is gone.
    """

    __tablename__ = "treatment_prescriptions"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    plan_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("planned_treatment_items.id", ondelete="SET NULL"), index=True
    )
    treatment_label: Mapped[str | None] = mapped_column(String(200))
    # `professionals` is in this module's `depends`, so the FK is allowed.
    professional_id: Mapped[UUID | None] = mapped_column(ForeignKey("professionals.id"))
    professional_name: Mapped[str] = mapped_column(String(200), info=pii(PiiKind.NAME))
    professional_license: Mapped[str | None] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
