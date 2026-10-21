"""Catalog module database models."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

# Supported pricing strategies. See app.modules.catalog.pricing for the computation.
PRICING_STRATEGIES = ("flat", "per_tooth", "per_surface", "per_role")

# Stage of care a treatment belongs to, in the order a plan is usually
# sequenced. Distinct from both category (where a treatment is filed) and
# specialty (who performs it): this is *when*.
#
#   diagnostico    exploration, imaging, study
#   urgencia       pain relief, drainage, emergency pulpectomy
#   preventivo     prophylaxis, sealants, fluoride
#   estabilizacion eliminate disease: endodontics, perio therapy, fillings
#   rehabilitacion restore function: crowns, prosthetics, implants, ortho
#   estetica       elective, non-pathological: whitening, veneers
#   mantenimiento  recall visits, periodic scaling, retainers
#
# The catalog value is a default. What a treatment actually *is* for a given
# patient is decided when it is planned — an extraction can be an emergency
# or a step in a planned rehabilitation — so the plan records its own.
TREATMENT_PHASES = (
    "diagnostico",
    "urgencia",
    "preventivo",
    "estabilizacion",
    "rehabilitacion",
    "estetica",
    "mantenimiento",
)

# The teeth a treatment can be done on. Most suit any tooth; some only a
# primary one (a pulpotomy with formocresol, a Hall crown) and some only a
# permanent one (an implant, a veneer). The odontogram offers a treatment
# only where it fits and refuses it on a tooth of the other dentition.
TREATMENT_DENTITIONS = ("both", "deciduous", "permanent")


def dentition_fits(dentition: str, tooth_number: int) -> bool:
    """Whether a treatment of this dentition can be done on the tooth (FDI:
    quadrants 5–8 are primary teeth)."""
    if dentition == "both":
        return True
    return (tooth_number // 10 >= 5) == (dentition == "deciduous")


if TYPE_CHECKING:
    from app.core.auth.models import Clinic


class VatType(Base, TimestampMixin):
    """VAT type configuration for treatments.

    Centralizes VAT definitions so treatments reference a VAT type by ID
    instead of storing type/rate separately. Prevents inconsistent combinations.
    """

    __tablename__ = "vat_types"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    # Localized names (JSONB for multi-language support)
    names: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"es": "Exento", "en": "Exempt"}

    # VAT rate percentage (0-100)
    rate: Mapped[float] = mapped_column(Float, default=0.0)

    # Default flag - only one per clinic should be default
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # System-seeded, cannot delete

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    catalog_items: Mapped[list["TreatmentCatalogItem"]] = relationship(
        back_populates="vat_type_rel"
    )

    __table_args__ = (
        Index("idx_vat_types_clinic", "clinic_id"),
        Index("idx_vat_types_default", "clinic_id", "is_default"),
    )


# Many-to-many between catalog items and specialties. A treatment may be
# performed under more than one discipline (a simple extraction belongs to
# both "Cirugía Oral" and general practice), so this is an association table
# rather than a column on the item. Both sides cascade on delete: the link
# is meaningless without either end.
catalog_item_specialties = Table(
    "catalog_item_specialties",
    Base.metadata,
    Column(
        "catalog_item_id",
        UUID(as_uuid=True),
        ForeignKey("treatment_catalog_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "specialty_id",
        UUID(as_uuid=True),
        ForeignKey("specialties.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("idx_catalog_item_specialties_specialty", "specialty_id"),
)


class Specialty(Base, TimestampMixin):
    """Dental specialty used to classify treatments and dentists.

    Independent from ``TreatmentCategory``: a category groups treatments
    by clinical area for catalog browsing, while a specialty tracks which
    professional discipline a treatment belongs to (e.g. a "Cirugía"
    category item like a third-molar extraction maps to the "Cirugía Oral
    y Maxilofacial" specialty). A treatment may have zero or more
    specialties, linked through ``catalog_item_specialties``.
    """

    __tablename__ = "specialties"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    # Stable identifier for seeded specialties, mirroring TreatmentCategory.key.
    # Seeding matches on this, so renaming "Ortodoncia" in the UI does not make
    # the next seed run create a second one. NULL for clinic-created rows.
    key: Mapped[str | None] = mapped_column(String(50), default=None)

    # Localized names (JSONB for multi-language support)
    names: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"es": "Cirugía Oral", "en": "..."}

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    catalog_items: Mapped[list["TreatmentCatalogItem"]] = relationship(
        secondary=catalog_item_specialties,
        back_populates="specialties",
    )

    __table_args__ = (
        Index("idx_specialties_clinic", "clinic_id"),
        # Partial: clinic-created specialties have no key and must not collide.
        Index(
            "uq_specialty_clinic_key",
            "clinic_id",
            "key",
            unique=True,
            postgresql_where=text("key IS NOT NULL"),
        ),
    )


class TreatmentCategory(Base, TimestampMixin):
    """Hierarchical category for organizing treatments.

    Categories form a tree structure for grouping related treatments.
    Examples: Diagnóstico, Restauradora, Cirugía, Endodoncia, Ortodoncia
    """

    __tablename__ = "treatment_categories"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    # Hierarchy
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("treatment_categories.id"), index=True, default=None
    )

    # Identification
    key: Mapped[str] = mapped_column(String(50))  # e.g., "diagnostico", "restauradora"

    # Localized content (JSONB for multi-language support)
    names: Mapped[dict] = mapped_column(
        JSONB, default=dict
    )  # {"es": "Diagnóstico", "en": "Diagnostic"}
    descriptions: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Display
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    icon: Mapped[str | None] = mapped_column(String(50))  # Icon name/class

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # System-seeded, cannot delete

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    parent: Mapped["TreatmentCategory | None"] = relationship(
        remote_side="TreatmentCategory.id", foreign_keys=[parent_id]
    )
    items: Mapped[list["TreatmentCatalogItem"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("clinic_id", "key", name="uq_category_clinic_key"),
        Index("idx_treatment_categories_clinic", "clinic_id"),
        Index("idx_treatment_categories_parent", "parent_id"),
    )


class TreatmentCatalogItem(Base, TimestampMixin):
    """Core treatment definition in the catalog.

    Represents a single treatment type that can be:
    - Applied to teeth in the odontogram
    - Added to budgets/invoices
    - Associated with appointments

    MVP includes single default price. Phase 2 adds multiple price lists.
    """

    __tablename__ = "treatment_catalog_items"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("treatment_categories.id"), index=True)

    # Identification
    internal_code: Mapped[str] = mapped_column(String(50))  # e.g., "CORONA-01", "ENDO-01"

    # Localized content
    names: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"es": "Corona", "en": "Crown"}
    descriptions: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Pricing (MVP: single default price)
    default_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # For margin calculation

    # Scheduling
    default_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    requires_appointment: Mapped[bool] = mapped_column(Boolean, default=True)

    # Tax configuration - references VatType
    vat_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("vat_types.id"), index=True, default=None
    )

    # Pricing strategy (how to compute a Treatment's price_snapshot from this item).
    # flat: default_price as-is.
    # per_tooth: default_price * teeth.length.
    # per_surface: tiered lookup in surface_prices by surface count, else default_price
    #              * sum(surfaces.length across teeth) (legacy linear fallback).
    # per_role: pricing_config[role] per tooth (for bridges: pillar vs pontic).
    pricing_strategy: Mapped[str] = mapped_column(String(20), default="flat")
    # Extra pricing parameters. For per_role: {"pillar": 500, "pontic": 400}.
    pricing_config: Mapped[dict | None] = mapped_column(JSONB, default=None)
    # Tiered prices by surface count for per_surface strategy. Keys: "1".."5" as
    # strings (JSONB requires string keys); values: price in default currency.
    # Missing tier resolves to the highest populated tier <= n, or default_price.
    surface_prices: Mapped[dict | None] = mapped_column(JSONB, default=None)

    # Default stage of care (see TREATMENT_PHASES). Overridable per plan item.
    default_phase: Mapped[str | None] = mapped_column(String(20), default=None, index=True)

    # Treatment characteristics.
    # treatment_scope aligns with Treatment.scope enum:
    #   tooth / multi_tooth / global_mouth / global_arch
    treatment_scope: Mapped[str] = mapped_column(String(20), default="tooth")
    is_diagnostic: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_surfaces: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which teeth it can be done on (see TREATMENT_DENTITIONS).
    dentition: Mapped[str] = mapped_column(String(20), default="both", server_default="both")

    # Billing configuration
    billing_mode: Mapped[str] = mapped_column(
        String(20), default="on_completion"
    )  # on_completion, on_acceptance, manual

    # Material reference (placeholder for future inventory module)
    material_notes: Mapped[str | None] = mapped_column(Text)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Whether the treatment is listed on the clinical /treatments page.
    # Distinct from `is_active`: an active treatment is one the clinic still
    # offers and can bill, while this only curates the browsing list — a
    # clinic showing its 40 usual treatments keeps the rest active for
    # budgets, odontogram and history. Defaults to visible so the page keeps
    # showing everything until someone deliberately narrows it.
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # System-seeded item
    # Switched off because its discipline was disabled, not because the
    # clinic retired it: enabling the discipline again brings it back, and a
    # treatment the clinic deactivated by hand is left alone.
    disabled_by_specialty: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    category: Mapped["TreatmentCategory"] = relationship(back_populates="items")
    vat_type_rel: Mapped["VatType | None"] = relationship(back_populates="catalog_items")
    odontogram_mapping: Mapped["TreatmentOdontogramMapping | None"] = relationship(
        back_populates="catalog_item", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list["CatalogItemSession"]] = relationship(
        back_populates="catalog_item",
        cascade="all, delete-orphan",
        order_by="CatalogItemSession.sequence",
    )
    specialties: Mapped[list["Specialty"]] = relationship(
        secondary=catalog_item_specialties,
        back_populates="catalog_items",
        order_by="Specialty.created_at",
    )

    __table_args__ = (
        UniqueConstraint("clinic_id", "internal_code", name="uq_catalog_item_clinic_code"),
        CheckConstraint(
            "dentition IN ('both', 'deciduous', 'permanent')",
            name="ck_catalog_items_dentition",
        ),
        Index("idx_catalog_items_clinic", "clinic_id"),
        Index("idx_catalog_items_category", "category_id"),
        Index("idx_catalog_items_active", "clinic_id", "is_active"),
        Index("idx_catalog_items_vat_type", "vat_type_id"),
    )


class CatalogItemSession(Base, TimestampMixin):
    """Session template for catalog items billed in stages.

    Defines the named steps of a multi-session treatment (e.g. Crown:
    "Toma de medidas" 200€ + "Colocación" 600€). When a catalog item
    is added to a treatment plan, the template is snapshotted into
    ``PlannedTreatmentItemSession`` rows owned by the plan; the
    template can evolve without affecting past instances.
    """

    __tablename__ = "catalog_item_sessions"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    catalog_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatment_catalog_items.id", ondelete="CASCADE"), index=True
    )

    sequence: Mapped[int] = mapped_column(Integer)
    # Localized session label: {"es": "Toma de medidas", "en": "Impressions"}
    labels: Mapped[dict] = mapped_column(JSONB, default=dict)
    default_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # Relationships
    catalog_item: Mapped["TreatmentCatalogItem"] = relationship(back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("catalog_item_id", "sequence", name="uq_catalog_session_item_sequence"),
        Index("idx_catalog_sessions_item", "catalog_item_id"),
    )


class TreatmentOdontogramMapping(Base, TimestampMixin):
    """Bridge between catalog items and odontogram visualization.

    Maps a catalog item to an existing odontogram treatment type,
    preserving the visualization rules from the constants file.
    """

    __tablename__ = "treatment_odontogram_mappings"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    catalog_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("treatment_catalog_items.id", ondelete="CASCADE"), unique=True
    )

    # Odontogram integration: the clinical type that drives visualization.
    # Maps to Treatment.clinical_type (bridge, crown, filling_composite, ...).
    odontogram_treatment_type: Mapped[str] = mapped_column(String(30))

    # Visualization layers. Each entry renders on top of the previous.
    # Example:
    # [
    #   {"layer": "cenital_pattern", "pattern": "diagonal_stripes", "color": "#F59E0B"},
    #   {"layer": "lateral_icon",    "icon": "implant",            "color": "#10B981"}
    # ]
    # Supported layers:
    #   - pulp_fill:      {"color": str, "extent"?: "partial_1_2"|"partial_2_3"|"full"|"overfill"}
    #   - occlusal_surface: {"color": str, "kind"?: "solid_fill"|"dot"|"outline"}
    #   - lateral_icon:    {"icon": str, "color"?: str}
    #   - cenital_pattern: {"pattern": str, "color": str}
    visualization_rules: Mapped[list] = mapped_column(JSONB, default=list)
    # Free-form extras (rarely needed; layer-level config lives inside visualization_rules).
    visualization_config: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Clinical category for TreatmentBar grouping
    clinical_category: Mapped[str] = mapped_column(
        String(20)
    )  # diagnostico, restauradora, cirugia, endodoncia, ortodoncia

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    catalog_item: Mapped["TreatmentCatalogItem"] = relationship(back_populates="odontogram_mapping")

    __table_args__ = (
        Index("idx_odontogram_mapping_clinic", "clinic_id"),
        Index("idx_odontogram_mapping_type", "odontogram_treatment_type"),
    )
