"""Contracts one module offers and another consumes without importing it.

A module that links to another's data — an appointment to its patient —
has two ways to reach it. Importing the other module's models is one,
and it welds the two together: neither can be read, tested or moved
without the other. This is the second: the core names what is needed,
the owner supplies it from :meth:`BaseModule.get_providers`, and the
consumer asks :func:`provider` (ADR 0039).

:func:`provider` only sees modules that are running, so asking it is
also how a consumer learns whether the link is available. ``None`` means
the owning App is off; the consumer carries on without it (ADR 0037).

Keep each contract to what a consumer actually calls. Rows never cross:
the dataclasses here are the whole vocabulary.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugins.registry import module_registry

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PersonBrief:
    """Enough of a person to label a reference to them.

    Field names are the owning columns' names, so the PII classification
    on those columns still tokenizes them wherever a brief is serialized
    (ADR 0025).
    """

    id: UUID
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    #: Professionals only: the colegiado number a prescription must show.
    license_number: str | None = None


@dataclass(frozen=True, slots=True)
class TreatmentLink:
    """One caller-owned row that points at a planned treatment."""

    id: UUID
    planned_item_id: UUID
    catalog_item_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PlannedTreatmentBrief:
    """What a planned treatment looks like from outside its plan."""

    planned_item_status: str
    catalog_item_id: UUID | None
    internal_code: str
    names: dict[str, str]
    default_price: float | None
    default_duration_minutes: int | None
    tooth_number: int | None
    surfaces: list[str] | None
    is_global: bool
    plan_id: UUID | None
    plan_number: str | None


@dataclass(frozen=True, slots=True)
class VisitNote:
    """What was written about one planned treatment during a visit."""

    id: UUID
    planned_item_id: UUID
    body: str
    professional_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReferenceSpecialty:
    """A discipline with a reference catalogue a clinic can start with."""

    key: str
    names: dict[str, str]
    #: Every clinic has it; it cannot be left out when choosing.
    required: bool


@dataclass(frozen=True, slots=True)
class BudgetBrief:
    """Enough of a budget to say where a plan's quote stands."""

    id: UUID
    budget_number: str
    status: str
    total: float
    patient_id: UUID


class PatientDirectory(Protocol):
    async def is_bookable(self, db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> bool:
        """The patient belongs to the clinic and is not archived."""

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, patient_ids: Collection[UUID]
    ) -> dict[UUID, PersonBrief]: ...


class ProfessionalDirectory(Protocol):
    async def is_bookable(self, db: AsyncSession, clinic_id: UUID, professional_id: UUID) -> bool:
        """An active directory profile of a type that sees patients."""

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, professional_ids: Collection[UUID]
    ) -> dict[UUID, PersonBrief]: ...

    async def list_bookable(self, db: AsyncSession, clinic_id: UUID) -> list[PersonBrief]: ...

    async def ensure_profile(self, db: AsyncSession, clinic_id: UUID, account_id: UUID) -> None:
        """Give a user account a directory profile under the same id, if
        it has none. Legacy callers still pass account ids."""

    async def profile_for_account(
        self, db: AsyncSession, clinic_id: UUID, account_id: UUID, professional_type: str
    ) -> UUID:
        """The id of the directory profile that stands for a user account
        in this clinic, creating the profile if there is none.

        Raises ``ValueError`` when the account does not exist."""

    async def for_account(
        self, db: AsyncSession, clinic_id: UUID, account_id: UUID | None
    ) -> UUID | None:
        """The directory profile an account *is* in this clinic, if it
        has one. Never creates: clinical attribution names nobody rather
        than guess (ADR 0032)."""


@dataclass(frozen=True, slots=True)
class ProfessionalActivity:
    """What one App says about one professional's work.

    ``patient_ids`` are the patients that App has them seeing, so the
    profile can count each patient once across Apps; ``counts`` are that
    App's own figures under keys it owns (``appointments``,
    ``treatments_pending``, ...).
    """

    patient_ids: frozenset[UUID] = frozenset()
    counts: Mapping[str, int] = field(default_factory=dict)


class ProfessionalWorkload(Protocol):
    """Supplied by every App that assigns work to a professional.

    Unlike the other contracts several modules supply it at once — ask
    :func:`providers`, never :func:`provider`. One that is off says
    nothing, and the profile shows what the rest know.
    """

    async def activity(
        self, db: AsyncSession, clinic_id: UUID, professional_ids: Collection[UUID]
    ) -> dict[UUID, ProfessionalActivity]:
        """An entry for every one of ``professional_ids``, zeros included:
        a missing figure means the App is off, never that nothing is
        assigned."""


class PlannedTreatments(Protocol):
    async def problems(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID, item_ids: Collection[UUID]
    ) -> list[str]:
        """Why these items cannot be scheduled for this patient. Empty when they can."""

    async def catalog_item_ids(
        self, db: AsyncSession, clinic_id: UUID, item_ids: Collection[UUID]
    ) -> dict[UUID, UUID | None]: ...

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, links: Collection[TreatmentLink]
    ) -> dict[UUID, PlannedTreatmentBrief]:
        """Keyed by ``TreatmentLink.id``."""


class AppointmentBook(Protocol):
    async def patients_of(
        self, db: AsyncSession, clinic_id: UUID, appointment_ids: Collection[UUID]
    ) -> dict[UUID, UUID | None]:
        """The patient of each appointment that exists in this clinic.
        An appointment may have none; one that is not found is left out."""

    async def ids_for_patient(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> list[UUID]: ...

    async def visit_notes(
        self, db: AsyncSession, clinic_id: UUID, planned_item_ids: Collection[UUID]
    ) -> list[VisitNote]:
        """The non-empty notes left on these planned treatments in visits."""


class PlanBudgets(Protocol):
    """What a treatment plan may ask about the budgets that price it.

    Questions only (ADR 0042): a plan never creates, cancels or deletes a
    budget through here. It announces what happened to it and ``budget``
    reacts. "The plan's budgets" are those carrying its number, plus the
    one it links to.
    """

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, budget_ids: Collection[UUID]
    ) -> dict[UUID, BudgetBrief]: ...

    async def ids_for_plan(
        self, db: AsyncSession, clinic_id: UUID, plan_number: str | None, budget_id: UUID | None
    ) -> list[UUID]:
        """Every budget the plan produced, cancelled ones included."""

    async def live_for_plan(
        self, db: AsyncSession, clinic_id: UUID, plan_number: str | None
    ) -> list[BudgetBrief]:
        """The plan's budgets that are neither cancelled nor deleted, oldest first."""

    async def priced_treatment_ids(
        self, db: AsyncSession, clinic_id: UUID, plan_number: str | None, budget_id: UUID | None
    ) -> set[UUID]:
        """The treatments a live budget of the plan puts a price on."""


class Collections(Protocol):
    async def plan_has_collections(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        budget_ids: Collection[UUID],
        treatment_ids: Collection[UUID],
    ) -> bool:
        """Whether money the patient paid sits on these budgets or treatments."""


class PlanConsents(Protocol):
    async def lacks_required_consent(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID, plan_id: UUID
    ) -> bool:
        """True when the clinic requires an informed consent for a plan and
        this plan has none signed.

        The rule is the owner's — whether the clinic asks for it, and what
        counts as having it. Whoever asks only obeys: a plan is not
        confirmed while this is true, and a treatment performed while it is
        true is shown as lacking its letter. ``None`` from :func:`provider`
        means consents are not kept here at all, and nothing can be
        required."""


class PlanQuotes(Protocol):
    async def snapshot(self, db: AsyncSession, clinic_id: UUID, plan_id: UUID) -> dict | None:
        """The plan as ``treatment_plan.confirmed`` announces it, plus
        ``plan_status`` and ``budget_id``. ``None`` if there is no such plan."""


@dataclass(frozen=True, slots=True)
class DocumentKindUsage:
    """Disk space the files of one clinical kind take up."""

    #: The owner's own vocabulary: ``xray``, ``photo``, ``document``…
    kind: str
    bytes: int
    count: int


class PatientDocuments(Protocol):
    async def belongs_to(
        self, db: AsyncSession, clinic_id: UUID, patient_id: UUID, document_id: UUID
    ) -> bool:
        """The document is a live file of this patient in this clinic."""

    async def usage_by_kind(self, db: AsyncSession) -> list[DocumentKindUsage]:
        """What the patients' files weigh, by clinical kind, largest first.

        Of the whole database, not of one clinic: it answers for the
        tenant's disk (``app.core.tenancy.usage``), which the clinics
        share. Archived files count — they are still on the disk.
        """


class ReferenceSpecialties(Protocol):
    def available(self) -> list[ReferenceSpecialty]:
        """The disciplines a new clinic can be set up with. Which ones it
        gets is said on ``clinic.created`` (``specialties``); the owner
        installs them."""

    async def enabled(self, db: AsyncSession, clinic_id: UUID) -> list[str]:
        """The keys of the disciplines a clinic has switched on. Changing
        them is said on ``clinic.specialties_set``."""


class WorkingHours(Protocol):
    async def professional_states(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        professional_ids: Collection[UUID],
        at: datetime,
    ) -> dict[UUID, str]:
        """``"on_break"`` or ``"off"`` for professionals not working at
        ``at``. Those who are working are left out."""


def providers(contract: type[T]) -> list[T]:
    """Every running module's implementation of ``contract``.

    For contracts several modules supply together
    (:class:`ProfessionalWorkload`)."""
    found = (module.get_providers().get(contract) for module in module_registry.list_modules())
    return [implementation for implementation in found if implementation is not None]


def provider(contract: type[T]) -> T | None:
    """The running module's implementation of ``contract``, if any."""
    for module in module_registry.list_modules():
        found = module.get_providers().get(contract)
        if found is not None:
            return found
    return None
