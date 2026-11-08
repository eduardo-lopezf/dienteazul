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
from datetime import date, datetime
from decimal import Decimal
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
class AppointmentEntry:
    """One appointment, flattened to what a calendar shows of it.

    No row and no id of another module's: a consumer that renders the
    agenda somewhere else — an iCalendar feed, a printed day sheet —
    needs the hands of the clock and the words on the card, nothing more.
    Plain data all the way down, so the owner can one day answer this
    from another container (see ``core-apps-separable-containers``).

    ``start_time`` / ``end_time`` are the clinic's wall clock, and the
    offset they carry is a storage artifact: read the hands, then
    localize them to the clinic's zone. ``patient_name`` is absent when
    the Patients App is off, exactly as it is absent from the API.
    """

    id: UUID
    start_time: datetime
    end_time: datetime
    status: str
    updated_at: datetime
    title: str | None = None
    treatment_type: str | None = None
    cabinet: str | None = None
    patient_name: str | None = None
    professional_name: str | None = None
    treatment_names: tuple[str, ...] = ()


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

    async def window(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        *,
        since: datetime,
        until: datetime,
        professional_id: UUID | None = None,
    ) -> list[AppointmentEntry]:
        """The appointments starting in ``[since, until]``, oldest first.

        Cancelled ones are left out: they are not on anybody's calendar.
        ``professional_id`` narrows it to one professional's day; ``None``
        is the whole clinic. Not paginated — a caller rendering a
        document has no second page to ask for.
        """


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


@dataclass(frozen=True, slots=True)
class CollectedPeriod:
    """What a clinic took in over a period, and what it is owed today.

    The collection axis and nothing else: no field here is, or can be
    derived into, the difference between what was invoiced and what was
    collected (ADR 0010). A consumer that wants the invoice axis reads
    billing's own report.
    """

    currency: str
    collected: Decimal
    refunded: Decimal
    net_collected: Decimal
    payment_count: int
    #: Point in time, not the period: what is owed as of now.
    receivable_today: Decimal


@dataclass(frozen=True, slots=True)
class ProducedBy:
    """Treatment executed in the period, attributed to one professional."""

    professional_name: str | None
    total: Decimal
    count: int


@dataclass(frozen=True, slots=True)
class PatientDebt:
    """One patient's outstanding balance, and how old the worst of it is.

    ``age_days`` is measured from the earliest charge the money has not
    reached, not from the patient's oldest charge: a patient who is up to
    date except for last week is not a 90-day debtor.
    """

    patient_id: UUID
    amount: Decimal
    age_days: int


class CollectionReport(Protocol):
    """The collection figures a clinic-wide summary puts on one page."""

    async def collected_in_period(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        currency: str,
        timezone: str,
        date_from: date,
        date_to: date,
    ) -> CollectedPeriod:
        """Collected, refunded and still owed, for this period."""

    async def produced_by_professional(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        timezone: str,
        date_from: date,
        date_to: date,
    ) -> list[ProducedBy]:
        """Who executed the treatment the period earned."""

    async def patients_owing(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        minimum: Decimal,
    ) -> list[PatientDebt]:
        """Who owes at least ``minimum``, oldest debt first."""


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


@dataclass(frozen=True, slots=True)
class CatalogItemBrief:
    """Enough of a catalogue treatment to name it outside the catalog.

    ``names`` is the localized JSONB as stored; the consumer collapses it
    to whatever locale it is rendering, as the catalog's own tools do.
    """

    id: UUID
    internal_code: str
    names: dict[str, str]


class TreatmentCatalogue(Protocol):
    """The clinic's treatments, to whoever needs to point at one.

    Added for the inventory's materials-per-treatment list: it stores a
    ``catalog_item_id`` with no foreign key, so it needs a way to read
    the names behind those ids and to offer a picker — without importing
    the catalog (ADR 0039). ``None`` from :func:`provider` means the
    Treatments App is off, and the consumer carries on with the ids it
    already has.
    """

    async def briefs(
        self, db: AsyncSession, clinic_id: UUID, item_ids: Collection[UUID]
    ) -> dict[UUID, CatalogItemBrief]:
        """Keyed by id. Ids that are not this clinic's are left out."""

    async def list_active(self, db: AsyncSession, clinic_id: UUID) -> list[CatalogItemBrief]:
        """Every treatment the clinic currently offers."""


@dataclass(frozen=True, slots=True)
class MaterialCostLine:
    """What one treatment type cost in material over a period."""

    #: ``None`` groups everything consumed against a planned treatment
    #: whose catalogue item could not be resolved — the Treatments App
    #: may be off, or the item may have been free-hand.
    catalog_item_id: UUID | None
    #: How many planned treatments contributed.
    treatments: int
    cost: Decimal
    #: Movements in this line whose material had no price on file. A
    #: cost is only as complete as this is zero, and a consumer that
    #: hides it turns "nobody priced the gloves" into "gloves are free".
    unpriced: int = 0


class MaterialCost(Protocol):
    """What the material a clinic used actually cost.

    The inventory's first outward contract. It is read by `reports`,
    which must never import this module: a clinic can switch the
    Inventario App off, and Productividad has to keep working without
    the figure rather than break (ADR 0037, ADR 0039).

    The figures come from the stock ledger's own ``cost_per_base_unit``,
    stamped on each movement when it happened — not from today's price
    (ADR 0065).
    """

    async def by_treatment(
        self, db: AsyncSession, clinic_id: UUID, date_from: date, date_to: date
    ) -> list[MaterialCostLine]:
        """Material consumed against treatments, grouped by treatment type."""

    async def consumed_total(
        self, db: AsyncSession, clinic_id: UUID, date_from: date, date_to: date
    ) -> Decimal:
        """Everything that left the shelf in the period, at what it cost —
        treatments, write-offs and hand-recorded use alike."""


@dataclass(frozen=True, slots=True)
class CommissionTerms:
    """What the clinic pays one professional, treatment by treatment.

    ``default_percent`` covers every treatment without a percentage of its
    own in ``by_catalog_item``. Either may be missing: a professional paid
    only on implants has no default, and :meth:`percent_for` then answers
    ``None`` for anything else — nothing agreed, never a confident zero.
    """

    #: ``"collected"`` (what the patient paid for the work) or
    #: ``"earned"`` (the work performed, priced).
    basis: str
    default_percent: Decimal | None
    by_catalog_item: Mapping[UUID, Decimal] = field(default_factory=dict)

    def percent_for(self, catalog_item_id: UUID | None) -> Decimal | None:
        if catalog_item_id is not None and catalog_item_id in self.by_catalog_item:
            return self.by_catalog_item[catalog_item_id]
        return self.default_percent


class CommissionRates(Protocol):
    """The percentages agreed with each professional.

    Supplied by `commissions` and read by `liquidations`, which settles on
    them. ``None`` from :func:`provider`, or :meth:`in_use` false for the
    clinic, means it keeps no per-treatment rates and the reader falls
    back to its own setting.
    """

    async def in_use(self, db: AsyncSession, clinic_id: UUID) -> bool:
        """Whether the clinic has switched these rates on (ADR 0066).

        `commissions` is an optional module of its App: it runs for the
        deployment and is off for each clinic until switched on.
        """

    async def terms(
        self, db: AsyncSession, clinic_id: UUID, professional_id: UUID
    ) -> CommissionTerms | None:
        """``None`` when nothing has been agreed with this professional."""


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
