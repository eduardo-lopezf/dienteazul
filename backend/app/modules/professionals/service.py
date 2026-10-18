"""Business logic for clinic professional profiles."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import TEXT
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.contracts import ProfessionalWorkload, providers
from app.core.privacy.tiers import INDIVIDUAL_TIERS
from app.modules.catalog.models import Specialty

from .models import Professional, professional_specialties


class UnknownUserLinkError(ValueError):
    """The account named cannot be linked: it has no access to this clinic."""


class UserLinkTakenError(ValueError):
    """The account named is already the account of another professional here."""


class UnknownSpecialtyError(ValueError):
    """Raised when a specialty does not belong to this clinic."""


class ProfessionalService:
    @staticmethod
    async def list(
        db: AsyncSession,
        clinic_id: UUID,
        *,
        search: str | None = None,
        professional_type: str | None = None,
        include_inactive: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Professional], int]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        conditions = [Professional.clinic_id == clinic_id]

        if not include_inactive:
            conditions.append(Professional.is_active.is_(True))
        if professional_type:
            conditions.append(Professional.professional_type == professional_type)
        if search and search.strip():
            terms = search.split()
            full_name = func.concat(Professional.first_name, " ", Professional.last_name)
            conditions.append(
                and_(
                    *(
                        or_(
                            Professional.first_name.ilike(f"%{term}%"),
                            Professional.last_name.ilike(f"%{term}%"),
                            full_name.ilike(f"%{term}%"),
                            # Specialty is a catalog row now; match any locale
                            # of its name so search behaves as it did when the
                            # column held the text itself.
                            Professional.id.in_(
                                select(professional_specialties.c.professional_id)
                                .join(
                                    Specialty,
                                    Specialty.id == professional_specialties.c.specialty_id,
                                )
                                .where(
                                    Specialty.clinic_id == clinic_id,
                                    func.cast(Specialty.names, TEXT).ilike(f"%{term}%"),
                                )
                            ),
                            Professional.license_number.ilike(f"%{term}%"),
                        )
                        for term in terms
                    )
                )
            )

        total = (
            await db.execute(select(func.count(Professional.id)).where(*conditions))
        ).scalar() or 0
        result = await db.execute(
            select(Professional)
            .where(*conditions)
            .order_by(Professional.last_name, Professional.first_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    @staticmethod
    async def get(db: AsyncSession, clinic_id: UUID, professional_id: UUID) -> Professional | None:
        result = await db.execute(
            select(Professional).where(
                Professional.id == professional_id,
                Professional.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def resolve_specialties(
        db: AsyncSession, clinic_id: UUID, specialty_ids: list[UUID] | None
    ) -> list[Specialty]:
        """Load the specialties, rejecting any that belong to another clinic.

        Without this a caller could link a profile to another tenant's
        specialty row, since the FK alone only checks the id exists.
        """
        if not specialty_ids:
            return []

        unique_ids = list(dict.fromkeys(specialty_ids))
        result = await db.execute(
            select(Specialty).where(
                Specialty.id.in_(unique_ids),
                Specialty.clinic_id == clinic_id,
            )
        )
        found = list(result.scalars().all())
        if len(found) != len(unique_ids):
            raise UnknownSpecialtyError("One or more specialties were not found")
        return found

    @staticmethod
    async def validate_user_link(
        db: AsyncSession,
        clinic_id: UUID,
        user_id: UUID | None,
        professional_id: UUID | None = None,
    ) -> None:
        """Refuse a link to an account that does not belong here, or is taken.

        Two failures, both of which would corrupt attribution rather than
        merely annoy someone:

        - An account with no membership in this clinic. Linking it would let a
          clinic name an outsider as the author of its clinical entries.
        - An account already linked to another professional of the same clinic.
          One account is one person; two professionals sharing it makes
          "who is responsible for this entry" unanswerable, which is the whole
          point of the column.
        """
        if user_id is None:
            return

        membership = await db.execute(
            select(ClinicMembership.id).where(
                ClinicMembership.user_id == user_id,
                ClinicMembership.clinic_id == clinic_id,
            )
        )
        if membership.scalar_one_or_none() is None:
            raise UnknownUserLinkError("That account has no access to this clinic")

        query = select(Professional.id).where(
            Professional.clinic_id == clinic_id,
            Professional.user_id == user_id,
        )
        if professional_id is not None:
            query = query.where(Professional.id != professional_id)
        taken = await db.execute(query)
        if taken.scalar_one_or_none() is not None:
            raise UserLinkTakenError("That account is already linked to another professional")

    @staticmethod
    async def create(db: AsyncSession, clinic_id: UUID, data: dict) -> Professional:
        specialties = await ProfessionalService.resolve_specialties(
            db, clinic_id, data.pop("specialty_ids", None)
        )
        await ProfessionalService.validate_user_link(db, clinic_id, data.get("user_id"))
        professional = Professional(clinic_id=clinic_id, **data)
        professional.specialties = specialties
        db.add(professional)
        await db.flush()
        return professional

    @staticmethod
    async def update(db: AsyncSession, professional: Professional, data: dict) -> Professional:
        if "specialty_ids" in data:
            professional.specialties = await ProfessionalService.resolve_specialties(
                db, professional.clinic_id, data.pop("specialty_ids")
            )
        if "user_id" in data:
            await ProfessionalService.validate_user_link(
                db, professional.clinic_id, data["user_id"], professional.id
            )
        for field, value in data.items():
            setattr(professional, field, value)
        await db.flush()
        return professional

    @staticmethod
    async def for_user(db: AsyncSession, clinic_id: UUID, user_id: UUID | None) -> UUID | None:
        """The professional this account *is* in this clinic, if any.

        How a clinical entry comes to name who is responsible for it. Returns
        None for an account with no profile — a receptionist typing what the
        patient dictated — and that is the honest answer, not a gap to fill
        with a guess (ADR 0032).

        Inactive profiles still answer: someone who has left the clinic wrote
        what they wrote, and a record that stops naming them the day their
        profile is deactivated is worse than one that names nobody.
        """
        if user_id is None:
            return None
        result = await db.execute(
            select(Professional.id).where(
                Professional.clinic_id == clinic_id,
                Professional.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def emails_with_system_access(
        db: AsyncSession, clinic_id: UUID, emails: list[str | None]
    ) -> set[str]:
        """Lowercased emails (of the ones given) that belong to a user with
        a membership in this clinic — i.e. "has system access here"."""
        normalized = {email.lower() for email in emails if email}
        if not normalized:
            return set()
        result = await db.execute(
            select(func.lower(User.email))
            .join(ClinicMembership, ClinicMembership.user_id == User.id)
            .where(
                ClinicMembership.clinic_id == clinic_id,
                func.lower(User.email).in_(normalized),
            )
        )
        return set(result.scalars().all())


class HolderProfileService:
    """The profile of the professional who *is* an individual practice.

    Under an individual tier (``INDIVIDUAL_TIERS``) the account holder is
    the practice's professional: patients, treatments and appointments are
    assigned to them, so they need a directory profile from the first day,
    and the clinic has no directory screen to make one from.

    The link to the account is stated by construction — the holder of the
    practice is the professional of the practice — not inferred from an
    e-mail (ADR 0032).
    """

    @staticmethod
    async def ensure(db: AsyncSession, clinic_id: UUID) -> Professional | None:
        """The holder's profile, made if missing. ``None`` for a clinic tier.

        Idempotent. An existing profile not linked to any account is left
        alone and a linked one is made beside it: telling which unlinked
        profile is the holder would be a guess.
        """
        clinic = await db.get(Clinic, clinic_id)
        if clinic is None or clinic.account_tier not in INDIVIDUAL_TIERS:
            return None
        holder = await db.scalar(
            select(User)
            .join(ClinicMembership, ClinicMembership.user_id == User.id)
            .where(ClinicMembership.clinic_id == clinic_id, ClinicMembership.role == "admin")
            .order_by(ClinicMembership.created_at, User.id)
            .limit(1)
        )
        if holder is None:
            return None
        existing = await db.scalar(
            select(Professional).where(
                Professional.clinic_id == clinic_id, Professional.user_id == holder.id
            )
        )
        if existing is not None:
            return existing
        profile = Professional(
            clinic_id=clinic_id,
            user_id=holder.id,
            first_name=holder.first_name or "",
            last_name=holder.last_name or "",
            email=holder.email,
            license_number=holder.professional_id,
            professional_type="dentist",
        )
        db.add(profile)
        await db.flush()
        return profile


class WorkloadService:
    """What each professional has assigned, from every App that assigns it."""

    @staticmethod
    async def for_clinic(
        db: AsyncSession, clinic_id: UUID, professional_ids: list[UUID] | None = None
    ) -> list[tuple[UUID, int, dict[str, int]]]:
        """``(professional_id, patients, counts)`` per professional.

        The clinic's active professionals unless ``professional_ids`` says
        which; always scoped by ``clinic_id``.
        """
        query = select(Professional.id).where(Professional.clinic_id == clinic_id)
        if professional_ids is not None:
            query = query.where(Professional.id.in_(professional_ids))
        else:
            query = query.where(Professional.is_active.is_(True))
        ids = list((await db.execute(query)).scalars().all())

        patients: dict[UUID, set[UUID]] = {pid: set() for pid in ids}
        counts: dict[UUID, dict[str, int]] = {pid: {} for pid in ids}
        for workload in providers(ProfessionalWorkload):
            for pid, activity in (await workload.activity(db, clinic_id, ids)).items():
                if pid not in patients:
                    continue
                patients[pid] |= activity.patient_ids
                counts[pid].update(activity.counts)
        return [(pid, len(patients[pid]), counts[pid]) for pid in ids]
