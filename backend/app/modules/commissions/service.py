"""What each professional is paid, as a percentage, treatment by treatment."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import contracts
from app.core.auth.models import Clinic
from app.core.contracts import CatalogItemBrief, CommissionTerms, TreatmentCatalogue
from app.core.plugins.apps import optional_modules_on
from app.core.privacy.tiers import INDIVIDUAL_TIERS
from app.modules.professionals.models import Professional

from .models import CommissionAgreement, CommissionRate


class CommissionError(ValueError):
    """A refusal the caller can fix. The message maps to an error code."""


def require_clinic_tier(account_tier: str) -> None:
    """Commissions are a clinic's: an individual practice pays nobody a share."""
    if account_tier in INDIVIDUAL_TIERS:
        raise CommissionError("Commissions are only available to clinics.")


async def switched_on(db: AsyncSession, clinic_id: UUID) -> bool:
    """Whether the clinic has this module on (ADR 0066): an optional module
    of the Professionals App, off until its administrator switches it on."""
    clinic = await db.scalar(select(Clinic).where(Clinic.id == clinic_id))
    if clinic is None:
        return False
    return "commissions" in optional_modules_on(clinic.modules, clinic.account_tier)


class CommissionService:
    @staticmethod
    async def get(
        db: AsyncSession, clinic_id: UUID, professional_id: UUID
    ) -> CommissionAgreement | None:
        result = await db.execute(
            select(CommissionAgreement)
            .options(selectinload(CommissionAgreement.rates))
            .where(
                CommissionAgreement.clinic_id == clinic_id,
                CommissionAgreement.professional_id == professional_id,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def replace(
        db: AsyncSession, clinic_id: UUID, professional_id: UUID, data: dict
    ) -> CommissionAgreement | None:
        """Set the whole agreement at once, as the screen edits it.

        With no general percentage and no treatment rates there is nothing
        agreed, and the row goes: an empty agreement would read as "agreed
        at nothing".
        """
        professional = await db.scalar(
            select(Professional.id).where(
                Professional.id == professional_id,
                Professional.clinic_id == clinic_id,
            )
        )
        if professional is None:
            raise CommissionError("That professional is not in this clinic.")

        rates: dict[UUID, Decimal] = {}
        for rate in data.get("rates") or []:
            if rate["catalog_item_id"] in rates:
                raise CommissionError("A treatment can only carry one percentage.")
            rates[rate["catalog_item_id"]] = rate["percent"]

        existing = await CommissionService.get(db, clinic_id, professional_id)
        kept = {r.catalog_item_id for r in existing.rates} if existing else set()
        await _check_treatments(db, clinic_id, set(rates) - kept)

        default_percent: Decimal | None = data.get("default_percent")
        if default_percent is None and not rates:
            if existing is not None:
                await db.delete(existing)
                await db.flush()
            return None

        agreement = existing or CommissionAgreement(
            clinic_id=clinic_id, professional_id=professional_id, rates=[]
        )
        agreement.basis = data.get("basis") or "collected"
        agreement.default_percent = default_percent
        agreement.notes = (data.get("notes") or "").strip() or None

        current = {r.catalog_item_id: r for r in agreement.rates}
        agreement.rates = [
            _rate(current.get(item_id), clinic_id, item_id, percent)
            for item_id, percent in rates.items()
        ]
        if existing is None:
            db.add(agreement)
        await db.flush()
        return await CommissionService.get(db, clinic_id, professional_id)

    @staticmethod
    async def treatments(
        db: AsyncSession, clinic_id: UUID, item_ids: set[UUID] | None = None
    ) -> dict[UUID, CatalogItemBrief]:
        """The catalogue's treatments, keyed by id; empty with the Treatments App off."""
        catalogue = contracts.provider(TreatmentCatalogue)
        if catalogue is None:
            return {}
        if item_ids is None:
            return {b.id: b for b in await catalogue.list_active(db, clinic_id)}
        return await catalogue.briefs(db, clinic_id, item_ids) if item_ids else {}

    @staticmethod
    async def terms(
        db: AsyncSession, clinic_id: UUID, professional_id: UUID
    ) -> CommissionTerms | None:
        agreement = await CommissionService.get(db, clinic_id, professional_id)
        if agreement is None:
            return None
        return CommissionTerms(
            basis=agreement.basis,
            default_percent=agreement.default_percent,
            by_catalog_item={r.catalog_item_id: r.percent for r in agreement.rates},
        )


async def adopt_liquidation_percentages(db: AsyncSession, clinic_id: UUID) -> int:
    """Carry each percentage already agreed in `liquidations` over to here.

    Once a clinic switches this module on it is its only source of
    percentages, so a clinic that had settled at 40 % would otherwise find
    "nothing agreed" the moment it does. Only professionals with no agreement here
    yet are copied, so running it twice changes nothing.

    Read by SQL, not by import: `liquidations` is another App and may never
    have been installed, in which case its table is missing and there is
    nothing to adopt. Returns how many agreements it created.
    """
    if await db.scalar(text("SELECT to_regclass('public.professional_commissions')")) is None:
        return 0
    rows = await db.execute(
        text(
            """
            SELECT pc.clinic_id, pc.professional_id, pc.basis, pc.percent, pc.notes
            FROM professional_commissions pc
            WHERE pc.clinic_id = :clinic_id
            AND NOT EXISTS (
                SELECT 1 FROM commission_agreements a
                WHERE a.clinic_id = pc.clinic_id AND a.professional_id = pc.professional_id
            )
            """
        ),
        {"clinic_id": clinic_id},
    )
    adopted = [
        CommissionAgreement(
            clinic_id=row.clinic_id,
            professional_id=row.professional_id,
            basis=row.basis,
            default_percent=row.percent,
            notes=row.notes,
        )
        for row in rows
    ]
    db.add_all(adopted)
    await db.flush()
    return len(adopted)


def _rate(
    current: CommissionRate | None, clinic_id: UUID, item_id: UUID, percent: Decimal
) -> CommissionRate:
    if current is not None:
        current.percent = percent
        return current
    return CommissionRate(clinic_id=clinic_id, catalog_item_id=item_id, percent=percent)


async def _check_treatments(db: AsyncSession, clinic_id: UUID, new_ids: set[UUID]) -> None:
    """A new rate must name a treatment of this clinic's catalogue.

    With the Treatments App off nothing can be checked, so no new rate is
    taken; the ones already agreed are kept as they are (ADR 0037).
    """
    if not new_ids:
        return
    if contracts.provider(TreatmentCatalogue) is None:
        raise CommissionError("Treatment rates need the Treatments app.")
    found = await CommissionService.treatments(db, clinic_id, new_ids)
    if set(found) != new_ids:
        raise CommissionError("That treatment is not in this clinic's catalogue.")
