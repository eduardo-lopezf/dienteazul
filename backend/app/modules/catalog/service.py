"""Catalog module service layer - business logic."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.utils.search import fold

from .models import (
    CatalogItemSession,
    Specialty,
    TreatmentCatalogItem,
    TreatmentCategory,
    TreatmentOdontogramMapping,
    VatType,
    catalog_item_specialties,
)
from .reference import BY_CODE

# Rounding tolerance when comparing session sum vs. item total.
SESSION_SUM_TOLERANCE = Decimal("0.01")

# Largest page `/items` will serve. The router validates against it and the
# service clamps to it, so the two can no longer drift: `/items` advertised
# `le=500` while the service clamped to 100 and the envelope echoed back the
# 500 that was asked for, so a caller that asked for everything got a fifth of
# what it asked for and no way to tell. The admin catalog screen asked for
# 500, drew 100 of the clinic's 136 treatments, and headed them with the
# number 136.
MAX_PAGE_SIZE = 100


class SessionTemplateError(ValueError):
    """Raised when a session template fails validation (sum mismatch, etc.)."""


class UnknownCatalogItemError(ValueError):
    """Raised when a referenced catalog item is missing from this clinic."""


class DuplicateSpecialtyError(ValueError):
    """Raised when a clinic already has a specialty under that name or key.

    Carries the offending row so the caller can say *which* one, and whether
    it is merely deactivated — that is the difference between "you already
    have this" and "you already have this, switch it back on".
    """

    def __init__(self, existing: "Specialty") -> None:
        self.existing = existing
        super().__init__("Specialty already exists")


def validate_session_template(
    item_total: Decimal | None,
    sessions: list[dict] | None,
) -> None:
    """Validate that session amounts sum to the item's total.

    ``sessions`` is a list of dicts with at least a ``default_price`` (or
    ``amount``) key. When the list is empty or None this is a no-op
    (single-session item). When ``item_total`` is None and sessions are
    provided we raise — sessions require a known total to validate
    against.
    """

    if not sessions:
        return
    if item_total is None:
        raise SessionTemplateError("Cannot define sessions when the item has no default_price")
    key = "default_price" if "default_price" in sessions[0] else "amount"
    total = sum((Decimal(str(s[key])) for s in sessions), Decimal("0"))
    if abs(total - Decimal(str(item_total))) > SESSION_SUM_TOLERANCE:
        raise SessionTemplateError(
            f"Sum of session prices ({total}) must equal item total ({item_total})"
        )


# Default VAT types to seed for new clinics
DEFAULT_VAT_TYPES = [
    {
        "names": {"es": "Exento", "en": "Exempt"},
        "rate": 0.0,
        "is_default": True,
        "is_system": True,
    },
    {
        "names": {"es": "Reducido (10%)", "en": "Reduced (10%)"},
        "rate": 10.0,
        "is_default": False,
        "is_system": True,
    },
    {
        "names": {"es": "General (21%)", "en": "Standard (21%)"},
        "rate": 21.0,
        "is_default": False,
        "is_system": True,
    },
]


class VatTypeService:
    """Service for VAT type operations."""

    @staticmethod
    async def list_vat_types(
        db: AsyncSession,
        clinic_id: UUID,
        include_inactive: bool = False,
    ) -> list[VatType]:
        """List all VAT types for a clinic."""
        query = select(VatType).where(VatType.clinic_id == clinic_id)

        if not include_inactive:
            query = query.where(VatType.is_active.is_(True))

        query = query.order_by(VatType.rate, VatType.created_at)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_vat_type(
        db: AsyncSession,
        clinic_id: UUID,
        vat_type_id: UUID,
    ) -> VatType | None:
        """Get a VAT type by ID."""
        result = await db.execute(
            select(VatType).where(
                VatType.id == vat_type_id,
                VatType.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_default_vat_type(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> VatType | None:
        """Get the default VAT type for a clinic."""
        result = await db.execute(
            select(VatType).where(
                VatType.clinic_id == clinic_id,
                VatType.is_default.is_(True),
                VatType.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_vat_type(
        db: AsyncSession,
        clinic_id: UUID,
        data: dict,
    ) -> VatType:
        """Create a new VAT type."""
        # If setting as default, unset existing default
        if data.get("is_default"):
            await VatTypeService._unset_default(db, clinic_id)

        vat_type = VatType(clinic_id=clinic_id, **data)
        db.add(vat_type)
        await db.flush()
        return vat_type

    @staticmethod
    async def update_vat_type(
        db: AsyncSession,
        clinic_id: UUID,
        vat_type: VatType,
        data: dict,
    ) -> VatType:
        """Update a VAT type."""
        # If setting as default, unset existing default first
        if data.get("is_default") and not vat_type.is_default:
            await VatTypeService._unset_default(db, clinic_id)

        for key, value in data.items():
            if value is not None:
                setattr(vat_type, key, value)

        await db.flush()
        return vat_type

    @staticmethod
    async def delete_vat_type(
        db: AsyncSession,
        vat_type: VatType,
    ) -> None:
        """Soft-delete a VAT type (set inactive)."""
        vat_type.is_active = False
        await db.flush()

    @staticmethod
    async def ensure_default_vat_types(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> list[VatType]:
        """Ensure default VAT types exist for a clinic. Creates them if missing."""
        existing = await VatTypeService.list_vat_types(db, clinic_id, include_inactive=True)

        if existing:
            return existing

        # Create default VAT types
        created = []
        for vat_config in DEFAULT_VAT_TYPES:
            vat_type = VatType(clinic_id=clinic_id, **vat_config)
            db.add(vat_type)
            created.append(vat_type)

        await db.flush()
        return created

    @staticmethod
    async def _unset_default(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> None:
        """Unset the current default VAT type for a clinic."""
        result = await db.execute(
            select(VatType).where(
                VatType.clinic_id == clinic_id,
                VatType.is_default.is_(True),
            )
        )
        current_default = result.scalar_one_or_none()
        if current_default:
            current_default.is_default = False


class SpecialtyService:
    """Service for specialty operations."""

    @staticmethod
    async def list_specialties(
        db: AsyncSession,
        clinic_id: UUID,
        include_inactive: bool = False,
    ) -> list[Specialty]:
        """List all specialties for a clinic."""
        query = select(Specialty).where(Specialty.clinic_id == clinic_id)

        if not include_inactive:
            query = query.where(Specialty.is_active.is_(True))

        query = query.order_by(Specialty.created_at)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_specialty(
        db: AsyncSession,
        clinic_id: UUID,
        specialty_id: UUID,
    ) -> Specialty | None:
        """Get a specialty by ID."""
        result = await db.execute(
            select(Specialty).where(
                Specialty.id == specialty_id,
                Specialty.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _name_variants(names: dict[str, str] | None) -> set[str]:
        """Comparable forms of a specialty's names: folded, cased down, trimmed.

        Compared across every language the row carries, because the names of
        one specialty in two languages are still that one specialty: a clinic
        working in English must not end up with "Endodontics" beside the
        seeded row that already answers to it.
        """
        return {
            fold(value).casefold().strip()
            for value in (names or {}).values()
            if value and value.strip()
        }

    @staticmethod
    async def find_equivalent(
        db: AsyncSession,
        clinic_id: UUID,
        names: dict[str, str] | None,
        key: str | None = None,
        exclude_id: UUID | None = None,
    ) -> Specialty | None:
        """The clinic's specialty that already means this, active or not.

        Deactivated ones count. They keep their treatment assignments, so
        creating a second row under the same name splits a discipline in two
        and the older half becomes invisible — `is_active` hides the row, not
        its links.
        """
        wanted = SpecialtyService._name_variants(names)
        result = await db.execute(select(Specialty).where(Specialty.clinic_id == clinic_id))
        for candidate in result.scalars().all():
            if exclude_id and candidate.id == exclude_id:
                continue
            if key and candidate.key == key:
                return candidate
            if wanted & SpecialtyService._name_variants(candidate.names):
                return candidate
        return None

    @staticmethod
    async def create_specialty(
        db: AsyncSession,
        clinic_id: UUID,
        data: dict,
    ) -> Specialty:
        """Create a new specialty, refusing one the clinic already has.

        The field was free text with no check of any kind, and the form's own
        placeholder read "Ej: Cirugía Oral y Maxilofacial" — the exact name of
        a seeded specialty sitting in the list above it. A second row costs
        more than a tidy list: professionals are tagged with one and treatments
        with the other, and the "only what my team does" filter then matches
        nothing, with nothing on screen to explain why.
        """
        existing = await SpecialtyService.find_equivalent(
            db, clinic_id, data.get("names"), data.get("key")
        )
        if existing:
            raise DuplicateSpecialtyError(existing)

        specialty = Specialty(clinic_id=clinic_id, **data)
        db.add(specialty)
        await db.flush()
        return specialty

    @staticmethod
    async def update_specialty(
        db: AsyncSession,
        specialty: Specialty,
        data: dict,
    ) -> Specialty:
        """Update a specialty. Renaming onto another one is refused too.

        Otherwise the rule only guards the front door: create "Ortodoncia B",
        rename it to "Ortodoncia", and the clinic has the split it was spared
        a moment earlier.
        """
        if data.get("names") is not None:
            existing = await SpecialtyService.find_equivalent(
                db,
                specialty.clinic_id,
                data["names"],
                exclude_id=specialty.id,
            )
            if existing:
                raise DuplicateSpecialtyError(existing)

        for key, value in data.items():
            if value is not None:
                setattr(specialty, key, value)

        await db.flush()
        return specialty

    @staticmethod
    async def suggestions(db: AsyncSession, clinic_id: UUID) -> list[dict]:
        """Recognised disciplines the clinic does not have yet.

        Seeded specialties are not offered again, and neither is one the
        clinic already created by hand under the same name.
        """
        from .seed import SUGGESTED_SPECIALTIES

        result = await db.execute(select(Specialty).where(Specialty.clinic_id == clinic_id))
        owned = list(result.scalars().all())
        owned_keys = {s.key for s in owned if s.key}
        owned_names: set[str] = set()
        for s in owned:
            owned_names |= SpecialtyService._name_variants(s.names)

        return [
            suggestion
            for suggestion in SUGGESTED_SPECIALTIES
            if suggestion["key"] not in owned_keys
            and not (SpecialtyService._name_variants(suggestion["names"]) & owned_names)
        ]

    @staticmethod
    async def delete_specialty(
        db: AsyncSession,
        specialty: Specialty,
    ) -> None:
        """Soft-delete a specialty (set inactive)."""
        specialty.is_active = False
        await db.flush()

    @staticmethod
    async def list_items(
        db: AsyncSession,
        clinic_id: UUID,
        specialty_id: UUID,
    ) -> list[TreatmentCatalogItem]:
        """List the live catalog items assigned to a specialty."""
        result = await db.execute(
            select(TreatmentCatalogItem)
            .join(
                catalog_item_specialties,
                catalog_item_specialties.c.catalog_item_id == TreatmentCatalogItem.id,
            )
            .where(
                catalog_item_specialties.c.specialty_id == specialty_id,
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.deleted_at.is_(None),
            )
            .order_by(TreatmentCatalogItem.internal_code)
        )
        return list(result.scalars().all())

    @staticmethod
    async def set_items(
        db: AsyncSession,
        clinic_id: UUID,
        specialty: Specialty,
        item_ids: list[UUID],
    ) -> list[TreatmentCatalogItem]:
        """Replace the set of catalog items assigned to a specialty.

        ``item_ids`` is authoritative — items missing from it lose the
        assignment. Ids that do not resolve to a live item of this clinic
        are rejected so a stale client cannot link another tenant's rows.
        """
        items: list[TreatmentCatalogItem] = []
        unique_ids = list(dict.fromkeys(item_ids))

        if unique_ids:
            result = await db.execute(
                select(TreatmentCatalogItem).where(
                    TreatmentCatalogItem.id.in_(unique_ids),
                    TreatmentCatalogItem.clinic_id == clinic_id,
                    TreatmentCatalogItem.deleted_at.is_(None),
                )
            )
            items = list(result.scalars().all())

            if len(items) != len(unique_ids):
                raise UnknownCatalogItemError("One or more catalog items were not found")

        await db.refresh(specialty, ["catalog_items"])
        specialty.catalog_items = items
        await db.flush()

        items.sort(key=lambda item: item.internal_code)
        return items


class CategoryService:
    """Service for treatment category operations."""

    @staticmethod
    async def list_categories(
        db: AsyncSession,
        clinic_id: UUID,
        include_inactive: bool = False,
    ) -> list[TreatmentCategory]:
        """List all categories for a clinic."""
        query = select(TreatmentCategory).where(TreatmentCategory.clinic_id == clinic_id)

        if not include_inactive:
            query = query.where(TreatmentCategory.is_active.is_(True))

        query = query.order_by(TreatmentCategory.display_order, TreatmentCategory.key)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_category_tree(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> list[TreatmentCategory]:
        """Get categories as a tree structure (top-level categories only).

        Children are loaded via relationship.
        """
        query = (
            select(TreatmentCategory)
            .where(
                TreatmentCategory.clinic_id == clinic_id,
                TreatmentCategory.parent_id.is_(None),
                TreatmentCategory.is_active.is_(True),
            )
            .order_by(TreatmentCategory.display_order)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_category(
        db: AsyncSession,
        clinic_id: UUID,
        category_id: UUID,
        include_inactive: bool = False,
    ) -> TreatmentCategory | None:
        """Get a category by ID."""
        query = select(TreatmentCategory).where(
            TreatmentCategory.id == category_id,
            TreatmentCategory.clinic_id == clinic_id,
        )
        if not include_inactive:
            query = query.where(TreatmentCategory.is_active.is_(True))
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_category_by_key(
        db: AsyncSession,
        clinic_id: UUID,
        key: str,
    ) -> TreatmentCategory | None:
        """Get a category by its key."""
        result = await db.execute(
            select(TreatmentCategory).where(
                TreatmentCategory.clinic_id == clinic_id,
                TreatmentCategory.key == key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_category(
        db: AsyncSession,
        clinic_id: UUID,
        data: dict,
    ) -> TreatmentCategory:
        """Create a new category."""
        category = TreatmentCategory(clinic_id=clinic_id, **data)
        db.add(category)
        await db.flush()
        return category

    @staticmethod
    async def update_category(
        db: AsyncSession,
        category: TreatmentCategory,
        data: dict,
    ) -> TreatmentCategory:
        """Update a category."""
        for key, value in data.items():
            if value is not None:
                setattr(category, key, value)
        await db.flush()
        return category

    @staticmethod
    async def delete_category(
        db: AsyncSession,
        category: TreatmentCategory,
        soft: bool = True,
    ) -> None:
        """Delete a category (soft delete by default)."""
        if soft:
            category.is_active = False
            await db.flush()
        else:
            await db.delete(category)
            await db.flush()


class CatalogService:
    """Service for catalog item operations."""

    @staticmethod
    async def list_items(
        db: AsyncSession,
        clinic_id: UUID,
        page: int = 1,
        page_size: int = 20,
        category_id: UUID | None = None,
        is_active: bool | None = True,
        treatment_scope: str | None = None,
        has_odontogram_mapping: bool | None = None,
        search_query: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[TreatmentCatalogItem], int]:
        """List catalog items with filtering and pagination.

        ``include_deleted`` is the way back from a deletion: the row survives
        (history references it), but nothing lists it, so without this an
        admin who removed a treatment by mistake could not find it to restore.
        """
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        offset = (page - 1) * page_size

        conditions = [TreatmentCatalogItem.clinic_id == clinic_id]
        if include_deleted:
            # A deleted item is inactive by construction, so leaving the
            # default ``is_active=True`` filter on would make the flag return
            # nothing — the one case it exists for.
            is_active = None
        else:
            conditions.append(TreatmentCatalogItem.deleted_at.is_(None))

        if is_active is not None:
            conditions.append(TreatmentCatalogItem.is_active == is_active)

        if category_id:
            conditions.append(TreatmentCatalogItem.category_id == category_id)

        if treatment_scope:
            conditions.append(TreatmentCatalogItem.treatment_scope == treatment_scope)

        if has_odontogram_mapping is not None:
            if has_odontogram_mapping:
                conditions.append(TreatmentCatalogItem.odontogram_mapping.has())
            else:
                conditions.append(~TreatmentCatalogItem.odontogram_mapping.has())

        if search_query:
            # Search in internal_code and names (JSONB)
            from sqlalchemy.dialects.postgresql import TEXT

            search_pattern = f"%{search_query}%"
            conditions.append(
                or_(
                    TreatmentCatalogItem.internal_code.ilike(search_pattern),
                    # Cast JSONB to text for searching
                    func.cast(TreatmentCatalogItem.names, TEXT).ilike(search_pattern),
                )
            )

        total = (
            await db.execute(select(func.count(TreatmentCatalogItem.id)).where(*conditions))
        ).scalar() or 0

        query = (
            select(TreatmentCatalogItem)
            .where(*conditions)
            .options(
                joinedload(TreatmentCatalogItem.category),
                joinedload(TreatmentCatalogItem.odontogram_mapping),
                joinedload(TreatmentCatalogItem.vat_type_rel),
                selectinload(TreatmentCatalogItem.sessions),
                selectinload(TreatmentCatalogItem.specialties),
            )
            .order_by(
                TreatmentCatalogItem.category_id,
                TreatmentCatalogItem.internal_code,
            )
            .offset(offset)
            .limit(page_size)
        )

        result = await db.execute(query)
        items = result.unique().scalars().all()

        return list(items), total

    @staticmethod
    async def get_item(
        db: AsyncSession,
        clinic_id: UUID,
        item_id: UUID,
        include_deleted: bool = False,
    ) -> TreatmentCatalogItem | None:
        """Get a catalog item by ID with related data.

        ``include_deleted`` is what makes a deletion reversible: the update
        endpoint has to be able to load a removed item in order to reactivate
        it. Every other caller wants the live catalog and leaves it false.
        """
        conditions = [
            TreatmentCatalogItem.id == item_id,
            TreatmentCatalogItem.clinic_id == clinic_id,
        ]
        if not include_deleted:
            conditions.append(TreatmentCatalogItem.deleted_at.is_(None))

        result = await db.execute(
            select(TreatmentCatalogItem)
            .where(*conditions)
            .options(
                joinedload(TreatmentCatalogItem.category),
                joinedload(TreatmentCatalogItem.odontogram_mapping),
                joinedload(TreatmentCatalogItem.vat_type_rel),
                selectinload(TreatmentCatalogItem.sessions),
                selectinload(TreatmentCatalogItem.specialties),
            )
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_item_by_code(
        db: AsyncSession,
        clinic_id: UUID,
        internal_code: str,
    ) -> TreatmentCatalogItem | None:
        """Get a catalog item by its internal code."""
        result = await db.execute(
            select(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.internal_code == internal_code,
                TreatmentCatalogItem.deleted_at.is_(None),
            )
            .options(
                joinedload(TreatmentCatalogItem.category),
                joinedload(TreatmentCatalogItem.odontogram_mapping),
                joinedload(TreatmentCatalogItem.vat_type_rel),
                selectinload(TreatmentCatalogItem.sessions),
                selectinload(TreatmentCatalogItem.specialties),
            )
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def _resolve_specialties(
        db: AsyncSession, clinic_id: UUID, specialty_ids: list[UUID]
    ) -> list[Specialty]:
        """Load the clinic's specialties for the given ids.

        Filtering by ``clinic_id`` is what stops an item from being linked to
        another tenant's specialty through a guessed id.
        """
        if not specialty_ids:
            return []
        result = await db.execute(
            select(Specialty).where(
                Specialty.clinic_id == clinic_id,
                Specialty.id.in_(specialty_ids),
            )
        )
        found = list(result.scalars().all())
        missing = set(specialty_ids) - {s.id for s in found}
        if missing:
            raise ValueError(f"Unknown specialty: {sorted(str(m) for m in missing)[0]}")
        return found

    @staticmethod
    async def create_item(
        db: AsyncSession,
        clinic_id: UUID,
        data: dict,
    ) -> TreatmentCatalogItem:
        """Create a new catalog item."""
        # Extract relations to handle separately
        odontogram_data = data.pop("odontogram_mapping", None)
        sessions_data = data.pop("sessions", None)
        specialty_ids = data.pop("specialty_ids", None)

        # Validate session template against the item total
        validate_session_template(data.get("default_price"), sessions_data)

        # If no vat_type_id provided, use clinic default
        if not data.get("vat_type_id"):
            default_vat = await VatTypeService.get_default_vat_type(db, clinic_id)
            if default_vat:
                data["vat_type_id"] = default_vat.id

        item = TreatmentCatalogItem(clinic_id=clinic_id, **data)
        if specialty_ids is not None:
            item.specialties = await CatalogService._resolve_specialties(
                db, clinic_id, specialty_ids
            )
        db.add(item)
        await db.flush()

        if odontogram_data:
            mapping = TreatmentOdontogramMapping(
                clinic_id=clinic_id,
                catalog_item_id=item.id,
                **odontogram_data,
            )
            db.add(mapping)

        if sessions_data:
            for idx, session_data in enumerate(sessions_data, start=1):
                db.add(
                    CatalogItemSession(
                        catalog_item_id=item.id,
                        sequence=session_data.get("sequence") or idx,
                        labels=session_data.get("labels") or {},
                        default_price=Decimal(str(session_data["default_price"])),
                    )
                )

        await db.flush()
        return item

    @staticmethod
    async def update_item(
        db: AsyncSession,
        clinic_id: UUID,
        item: TreatmentCatalogItem,
        data: dict,
    ) -> TreatmentCatalogItem:
        """Update a catalog item.

        ``sessions`` semantics: omitted key = leave template untouched;
        present key (list or empty list) = replace template atomically.
        """
        odontogram_data = data.pop("odontogram_mapping", None)
        sessions_data = data.pop("sessions", "__not_provided__")
        specialty_ids = data.pop("specialty_ids", None)

        # Determine effective total for sessions validation
        new_total = data.get("default_price")
        effective_total = new_total if new_total is not None else item.default_price
        if sessions_data != "__not_provided__":
            validate_session_template(effective_total, sessions_data)
        elif new_total is not None and item.sessions:
            # A price on its own, on an item billed in stages. The rule is that
            # the stages add up to the total, and it was only ever checked when
            # a template came with the write — so moving a crown from 750 to
            # 800 left "Toma de medidas 250 + Colocación 500" behind it, an
            # invalid state the form cannot even draw. Checked here because the
            # caller need not know an item has a template: the price cell in
            # the catalog list does not.
            validate_session_template(
                effective_total,
                [{"default_price": session.default_price} for session in item.sessions],
            )

        for key, value in data.items():
            if value is not None:
                setattr(item, key, value)

        # Reactivating a deleted item restores it. The deletion is a soft one
        # precisely so this is possible: the row never went away, only the
        # listings did, and an admin who removed a treatment by mistake needs
        # a way back that does not involve the database.
        if data.get("is_active") is True and item.deleted_at is not None:
            item.deleted_at = None

        if specialty_ids is not None:
            item.specialties = await CatalogService._resolve_specialties(
                db, clinic_id, specialty_ids
            )

        if odontogram_data:
            if item.odontogram_mapping:
                for key, value in odontogram_data.items():
                    setattr(item.odontogram_mapping, key, value)
            else:
                mapping = TreatmentOdontogramMapping(
                    clinic_id=clinic_id,
                    catalog_item_id=item.id,
                    **odontogram_data,
                )
                db.add(mapping)

        if sessions_data != "__not_provided__":
            # Clear via relationship so `delete-orphan` cascade removes
            # the old rows during flush; raw DELETE would leave the
            # ORM session's collection cache stale.
            item.sessions.clear()
            await db.flush()
            for idx, session_data in enumerate(sessions_data or [], start=1):
                item.sessions.append(
                    CatalogItemSession(
                        sequence=session_data.get("sequence") or idx,
                        labels=session_data.get("labels") or {},
                        default_price=Decimal(str(session_data["default_price"])),
                    )
                )

        await db.flush()
        return item

    @staticmethod
    async def delete_item(
        db: AsyncSession,
        item: TreatmentCatalogItem,
        hard: bool = False,
    ) -> None:
        """Delete a catalog item (soft delete by default).

        Soft on purpose: treatments already performed, budget lines and plan
        templates all point at this row. Hard-deleting it would take the
        history with it, so the row stays and drops out of every listing.
        """
        if hard:
            await db.delete(item)
        else:
            from datetime import UTC, datetime

            item.deleted_at = datetime.now(UTC)
            item.is_active = False

        await db.flush()

    @staticmethod
    async def search_items(
        db: AsyncSession,
        clinic_id: UUID,
        query: str,
        limit: int = 20,
    ) -> list[TreatmentCatalogItem]:
        """Search catalog items by name or code.

        Same two rules as the patient search (`app.core.utils.search`), and
        for the same reason: staff type "reconstruccion" and "raspado
        alisado", and a plain ILIKE on the whole string answers neither.
        Accents are folded on both sides, and every word must match
        *something* — the code or the name — in any order.
        """
        from sqlalchemy.dialects.postgresql import TEXT

        from app.core.utils.search import FOLD_FROM, FOLD_TO, search_tokens

        tokens = search_tokens(query)
        if not tokens:
            return []

        folded_code = func.translate(TreatmentCatalogItem.internal_code, FOLD_FROM, FOLD_TO)
        folded_names = func.translate(
            func.cast(TreatmentCatalogItem.names, TEXT), FOLD_FROM, FOLD_TO
        )

        result = await db.execute(
            select(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.is_active.is_(True),
                TreatmentCatalogItem.deleted_at.is_(None),
                *[
                    or_(
                        folded_code.ilike(f"%{token}%"),
                        folded_names.ilike(f"%{token}%"),
                    )
                    for token in tokens
                ],
            )
            .options(
                joinedload(TreatmentCatalogItem.category),
                joinedload(TreatmentCatalogItem.vat_type_rel),
            )
            .limit(limit)
        )
        return list(result.unique().scalars().all())

    @staticmethod
    async def primary_specialties(
        db: AsyncSession, clinic_id: UUID, items: list[TreatmentCatalogItem]
    ) -> dict[UUID, Specialty]:
        """The one discipline each treatment is shown under.

        A treatment may belong to several. It is filed under the one whose
        reference file holds it (ADR 0048) when the clinic has that one
        enabled, otherwise under the first enabled one it was given. A
        treatment with no enabled discipline is absent from the result.
        """
        if not items:
            return {}
        rows = await db.execute(
            select(catalog_item_specialties.c.catalog_item_id, Specialty)
            .join(Specialty, Specialty.id == catalog_item_specialties.c.specialty_id)
            .where(
                Specialty.clinic_id == clinic_id,
                Specialty.is_active.is_(True),
                catalog_item_specialties.c.catalog_item_id.in_([item.id for item in items]),
            )
            .order_by(Specialty.created_at, Specialty.id)
        )
        linked: dict[UUID, list[Specialty]] = {}
        for item_id, specialty in rows.all():
            linked.setdefault(item_id, []).append(specialty)

        primary: dict[UUID, Specialty] = {}
        for item in items:
            candidates = linked.get(item.id)
            if not candidates:
                continue
            reference = BY_CODE.get(item.internal_code)
            owner = reference[0] if reference else None
            primary[item.id] = next((s for s in candidates if s.key == owner), candidates[0])
        return primary

    @staticmethod
    async def get_popular_items(
        db: AsyncSession,
        clinic_id: UUID,
        limit: int = 8,
    ) -> list[TreatmentCatalogItem]:
        """Get popular catalog items by usage count in budgets and invoices.

        Usage counts come from sibling modules (``budget_items``,
        ``invoice_items``) that depend on catalog — not the other way
        round. To avoid pulling their ORM models into the foundational
        catalog module (which would invert the DAG and block uninstall
        of billing/budget) we read their tables through a raw
        ``UNION ALL`` SQL fragment. Table names are the only contract;
        a rename in either module must be coordinated here (same
        coupling as the previous import, now expressed as a SQL
        string and free of cross-module Python imports).
        """
        usage_rows = (
            await db.execute(
                text(
                    """
                    SELECT catalog_item_id, COUNT(*) AS n
                    FROM (
                        SELECT catalog_item_id FROM budget_items
                        WHERE clinic_id = :clinic_id
                          AND catalog_item_id IS NOT NULL
                        UNION ALL
                        SELECT catalog_item_id FROM invoice_items
                        WHERE clinic_id = :clinic_id
                          AND catalog_item_id IS NOT NULL
                    ) AS usage
                    GROUP BY catalog_item_id
                    ORDER BY n DESC
                    LIMIT :limit
                    """
                ),
                {"clinic_id": clinic_id, "limit": limit},
            )
        ).all()

        ranked_ids: list[UUID] = [row.catalog_item_id for row in usage_rows]

        if not ranked_ids:
            # Cold-start clinic with no budgets/invoices yet — fall
            # back to the most recently created active items so the UI
            # still has something to render.
            result = await db.execute(
                select(TreatmentCatalogItem)
                .where(
                    TreatmentCatalogItem.clinic_id == clinic_id,
                    TreatmentCatalogItem.is_active.is_(True),
                    TreatmentCatalogItem.deleted_at.is_(None),
                )
                .options(
                    joinedload(TreatmentCatalogItem.category),
                    joinedload(TreatmentCatalogItem.vat_type_rel),
                )
                .order_by(TreatmentCatalogItem.created_at.desc())
                .limit(limit)
            )
            return list(result.unique().scalars().all())

        result = await db.execute(
            select(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.id.in_(ranked_ids),
                TreatmentCatalogItem.is_active.is_(True),
                TreatmentCatalogItem.deleted_at.is_(None),
            )
            .options(
                joinedload(TreatmentCatalogItem.category),
                joinedload(TreatmentCatalogItem.vat_type_rel),
            )
        )
        items_by_id = {item.id: item for item in result.unique().scalars().all()}
        # Preserve the count-ordered ranking from the raw query.
        return [items_by_id[i] for i in ranked_ids if i in items_by_id]

    @staticmethod
    async def get_recent_items(
        db: AsyncSession,
        clinic_id: UUID,
        limit: int = 8,
    ) -> list[TreatmentCatalogItem]:
        """The treatments this clinic reached for most recently.

        Recency, not frequency — `get_popular_items` already answers "most
        used", and the two diverge exactly where it matters: a clinic that
        stopped doing amalgams last year still has them at the top of a
        frequency list. What a dentist wants offered before they type is what
        they were doing this week.

        Read from ``treatments`` (the chart), because that is the row every
        planned or performed treatment creates, whichever surface recorded
        it. Same raw-SQL arrangement — and the same caveat — as
        ``get_popular_items``: the table name is the only contract, so a
        rename in `odontogram` must be coordinated here. `odontogram` is
        `removable=False`, so the table is always there.
        """
        rows = (
            await db.execute(
                text(
                    """
                    SELECT catalog_item_id, MAX(recorded_at) AS last_used
                    FROM treatments
                    WHERE clinic_id = :clinic_id
                      AND catalog_item_id IS NOT NULL
                      AND deleted_at IS NULL
                    GROUP BY catalog_item_id
                    ORDER BY last_used DESC
                    LIMIT :limit
                    """
                ),
                {"clinic_id": clinic_id, "limit": limit},
            )
        ).all()

        ranked_ids: list[UUID] = [row.catalog_item_id for row in rows]

        loaders = (
            joinedload(TreatmentCatalogItem.category),
            joinedload(TreatmentCatalogItem.vat_type_rel),
        )

        if not ranked_ids:
            # A clinic that has never charted anything still needs something
            # under the search box, or the first plan starts on a blank panel.
            result = await db.execute(
                select(TreatmentCatalogItem)
                .where(
                    TreatmentCatalogItem.clinic_id == clinic_id,
                    TreatmentCatalogItem.is_active.is_(True),
                    TreatmentCatalogItem.deleted_at.is_(None),
                )
                .options(*loaders)
                .order_by(TreatmentCatalogItem.created_at.desc())
                .limit(limit)
            )
            return list(result.unique().scalars().all())

        result = await db.execute(
            select(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.id.in_(ranked_ids),
                TreatmentCatalogItem.is_active.is_(True),
                TreatmentCatalogItem.deleted_at.is_(None),
            )
            .options(*loaders)
        )
        items_by_id = {item.id: item for item in result.unique().scalars().all()}
        # Preserve the recency ranking from the raw query.
        return [items_by_id[i] for i in ranked_ids if i in items_by_id]


class OdontogramCatalogService:
    """Service for odontogram-catalog integration."""

    @staticmethod
    async def get_odontogram_treatments(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> list[dict]:
        """Get catalog items with odontogram mappings for the TreatmentBar.

        Returns a list of treatments grouped by clinical category.
        """
        result = await db.execute(
            select(TreatmentCatalogItem)
            .where(
                TreatmentCatalogItem.clinic_id == clinic_id,
                TreatmentCatalogItem.is_active.is_(True),
                TreatmentCatalogItem.deleted_at.is_(None),
            )
            .options(
                joinedload(TreatmentCatalogItem.category),
                joinedload(TreatmentCatalogItem.odontogram_mapping),
            )
        )

        items = result.unique().scalars().all()

        # Filter items with odontogram mapping and transform
        treatments = []
        for item in items:
            if item.odontogram_mapping:
                treatments.append(
                    {
                        "id": str(item.id),
                        "internal_code": item.internal_code,
                        "names": item.names,
                        "default_price": float(item.default_price) if item.default_price else None,
                        "treatment_scope": item.treatment_scope,
                        "requires_surfaces": item.requires_surfaces,
                        "is_diagnostic": item.is_diagnostic,
                        "dentition": item.dentition,
                        "pricing_strategy": item.pricing_strategy or "flat",
                        "pricing_config": item.pricing_config,
                        "surface_prices": item.surface_prices,
                        "odontogram_treatment_type": item.odontogram_mapping.odontogram_treatment_type,
                        "visualization_rules": item.odontogram_mapping.visualization_rules,
                        "visualization_config": item.odontogram_mapping.visualization_config,
                        "clinical_category": item.odontogram_mapping.clinical_category,
                        "category_key": item.category.key if item.category else None,
                        "category_names": item.category.names if item.category else {},
                    }
                )

        return treatments

    @staticmethod
    async def get_treatments_by_category(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> dict[str, list[dict]]:
        """Get odontogram treatments grouped by clinical category."""
        treatments = await OdontogramCatalogService.get_odontogram_treatments(db, clinic_id)

        # Group by clinical category
        grouped: dict[str, list[dict]] = {}
        for treatment in treatments:
            category = treatment["clinical_category"]
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(treatment)

        return grouped
