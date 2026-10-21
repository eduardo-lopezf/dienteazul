"""Catalog module Pydantic schemas for API request/response."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Stage of care; mirrors app.modules.catalog.models.TREATMENT_PHASES.
TreatmentPhase = Literal[
    "diagnostico",
    "urgencia",
    "preventivo",
    "estabilizacion",
    "rehabilitacion",
    "estetica",
    "mantenimiento",
]

# Teeth a treatment can be done on; mirrors models.TREATMENT_DENTITIONS.
TreatmentDentition = Literal["both", "deciduous", "permanent"]

# ============================================================================
# VAT Type Schemas
# ============================================================================


class VatTypeCreate(BaseModel):
    """Schema for creating a VAT type."""

    names: dict[str, str] = Field(default_factory=dict)  # {"es": "Nombre", "en": "Name"}
    rate: float = Field(default=0.0, ge=0, le=100)
    is_default: bool = False


class VatTypeUpdate(BaseModel):
    """Schema for updating a VAT type."""

    names: dict[str, str] | None = None
    rate: float | None = Field(default=None, ge=0, le=100)
    is_default: bool | None = None
    is_active: bool | None = None


class VatTypeResponse(BaseModel):
    """Schema for VAT type response."""

    id: UUID
    clinic_id: UUID
    names: dict[str, str]
    rate: float
    is_default: bool
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VatTypeBrief(BaseModel):
    """Brief VAT type info for lists and selects."""

    id: UUID
    names: dict[str, str]
    rate: float
    is_default: bool
    is_active: bool
    is_system: bool

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Specialty Schemas
# ============================================================================


class SpecialtyCreate(BaseModel):
    """Schema for creating a specialty."""

    names: dict[str, str] = Field(default_factory=dict)  # {"es": "Nombre", "en": "Name"}
    # Stable identifier, only when the specialty was picked from the
    # recognised list (`GET /specialties/suggestions`). A client must not mint
    # one: the key is what a later seed run matches on, so an invented value
    # could silently claim a name the product later ships.
    key: str | None = Field(default=None, max_length=50)


class SpecialtySuggestion(BaseModel):
    """A recognised discipline a clinic can add in one click."""

    key: str
    names: dict[str, str]


class SpecialtyPackResponse(BaseModel):
    """A discipline's reference catalogue, and where the clinic stands on it."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    names: dict[str, str]
    enabled: bool
    #: Treatments in the reference catalogue of the discipline.
    reference_count: int
    #: Of those, how many the clinic has, active.
    installed_count: int
    #: Of those, how many the clinic changed — what a restore would overwrite.
    customised_count: int
    #: Reference treatments the clinic lacks: enabling again adds them and
    #: touches nothing else.
    missing_count: int = 0
    specialty_id: UUID | None = None


class PackTreatmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    names: dict[str, str]
    #: The reference price: a starting point, not a tariff.
    reference_price: Decimal | None
    minutes: int | None
    state: str
    customised: bool
    clinic_price: Decimal | None


class PackSubareaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    names: dict[str, str]
    treatments: list[PackTreatmentResponse]


class PackSharedResponse(BaseModel):
    """Treatments another discipline's file holds and shares with this one."""

    specialty_key: str
    names: dict[str, str]
    treatments: list[PackTreatmentResponse]


class SpecialtyPackDetailResponse(SpecialtyPackResponse):
    subareas: list[PackSubareaResponse]
    shared: list[PackSharedResponse]


class SpecialtyUpdate(BaseModel):
    """Schema for updating a specialty."""

    names: dict[str, str] | None = None
    is_active: bool | None = None


class SpecialtyResponse(BaseModel):
    """Schema for specialty response."""

    id: UUID
    clinic_id: UUID
    # Stable identifier of a seeded specialty (``cirugia``, ``endodoncia``…),
    # NULL for clinic-created ones. Exposed so the UI can match a specialty by
    # meaning rather than by its display name, which a clinic may rename.
    key: str | None = None
    names: dict[str, str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpecialtyBrief(BaseModel):
    """Brief specialty info, embedded in catalog item responses."""

    id: UUID
    names: dict[str, str]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SpecialtyItemsUpdate(BaseModel):
    """Schema for replacing the treatments assigned to a specialty.

    The list is authoritative: items missing from it are unassigned.
    """

    item_ids: list[UUID] = Field(default_factory=list)


# ============================================================================
# Category Schemas
# ============================================================================


class CategoryCreate(BaseModel):
    """Schema for creating a treatment category."""

    key: str = Field(min_length=1, max_length=50)
    names: dict[str, str] = Field(default_factory=dict)  # {"es": "Nombre", "en": "Name"}
    descriptions: dict[str, str] | None = None
    parent_id: UUID | None = None
    display_order: int = 0
    icon: str | None = None


class CategoryUpdate(BaseModel):
    """Schema for updating a treatment category."""

    key: str | None = Field(default=None, min_length=1, max_length=50)
    names: dict[str, str] | None = None
    descriptions: dict[str, str] | None = None
    parent_id: UUID | None = None
    display_order: int | None = None
    icon: str | None = None
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    """Schema for treatment category response."""

    id: UUID
    clinic_id: UUID
    parent_id: UUID | None
    key: str
    names: dict[str, str]
    descriptions: dict[str, str] | None
    display_order: int
    icon: str | None
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryTreeResponse(CategoryResponse):
    """Schema for category with nested children (tree structure)."""

    children: list["CategoryTreeResponse"] = []

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Odontogram Mapping Schemas
# ============================================================================


class OdontogramMappingCreate(BaseModel):
    """Schema for creating odontogram mapping (usually part of item creation)."""

    odontogram_treatment_type: str = Field(max_length=30)
    visualization_rules: list[dict] = Field(default_factory=list)
    visualization_config: dict = Field(default_factory=dict)
    clinical_category: str = Field(max_length=20)


class OdontogramMappingResponse(BaseModel):
    """Schema for odontogram mapping response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    odontogram_treatment_type: str
    visualization_rules: list[dict]
    visualization_config: dict
    clinical_category: str


# ============================================================================
# Session Template Schemas
# ============================================================================


class CatalogItemSessionInput(BaseModel):
    """Input shape for a session in the catalog template.

    Used inside CatalogItemCreate/Update.sessions[]. Sequence is assigned
    in array order at the server; client may omit or send a hint.
    """

    sequence: int | None = Field(default=None, ge=1)
    labels: dict[str, str] = Field(default_factory=dict)
    default_price: Decimal = Field(ge=0)


class CatalogItemSessionResponse(BaseModel):
    id: UUID
    sequence: int
    labels: dict[str, str]
    default_price: Decimal

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Catalog Item Schemas
# ============================================================================


class CatalogItemCreate(BaseModel):
    """Schema for creating a catalog item."""

    internal_code: str = Field(min_length=1, max_length=50)
    category_id: UUID
    names: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] | None = None

    # Pricing
    default_price: Decimal | None = Field(default=None, ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)

    # Scheduling
    default_duration_minutes: int | None = Field(default=None, ge=0, le=480)  # Max 8 hours
    requires_appointment: bool = True

    # Tax - references VatType by ID (optional, uses clinic default if not provided)
    vat_type_id: UUID | None = None

    # Pricing strategy (how to compute Treatment.price_snapshot).
    pricing_strategy: Literal["flat", "per_tooth", "per_surface", "per_role"] = "flat"
    pricing_config: dict | None = None
    # Tiered prices by surface count. Keys "1".."5" map to prices. Used when
    # pricing_strategy == "per_surface". See pricing.py for tier resolution.
    surface_prices: dict[str, Decimal] | None = None

    # Stage of care this treatment usually belongs to (see TREATMENT_PHASES).
    default_phase: TreatmentPhase | None = None

    # Treatment characteristics (aligns with Treatment.scope).
    treatment_scope: Literal["tooth", "multi_tooth", "global_mouth", "global_arch"] = "tooth"
    is_diagnostic: bool = False
    requires_surfaces: bool = False
    dentition: TreatmentDentition = "both"

    # Material
    material_notes: str | None = None

    # Listed on the clinical /treatments page (see model docstring).
    is_visible: bool = True

    # Odontogram mapping (optional)
    odontogram_mapping: OdontogramMappingCreate | None = None

    # Session template (optional). Empty list and None both mean single-session.
    sessions: list[CatalogItemSessionInput] | None = None

    # Disciplines that perform this treatment. Assignable from the item so the
    # alta form can ask "who does it" in one step; the specialty-side endpoint
    # (``PUT /specialties/{id}/items``) still exists for bulk reassignment and
    # keeps requiring ``catalog.admin``.
    specialty_ids: list[UUID] | None = None


class CatalogItemUpdate(BaseModel):
    """Schema for updating a catalog item."""

    internal_code: str | None = Field(default=None, min_length=1, max_length=50)
    category_id: UUID | None = None
    names: dict[str, str] | None = None
    descriptions: dict[str, str] | None = None

    # Pricing
    default_price: Decimal | None = Field(default=None, ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)

    # Scheduling
    default_duration_minutes: int | None = Field(default=None, ge=0, le=480)
    requires_appointment: bool | None = None

    # Tax - references VatType by ID
    vat_type_id: UUID | None = None

    # Pricing strategy
    pricing_strategy: Literal["flat", "per_tooth", "per_surface", "per_role"] | None = None
    pricing_config: dict | None = None
    surface_prices: dict[str, Decimal] | None = None

    # Stage of care
    default_phase: TreatmentPhase | None = None

    # Treatment characteristics
    treatment_scope: Literal["tooth", "multi_tooth", "global_mouth", "global_arch"] | None = None
    is_diagnostic: bool | None = None
    requires_surfaces: bool | None = None
    dentition: TreatmentDentition | None = None

    # Material
    material_notes: str | None = None

    # Status
    is_active: bool | None = None
    is_visible: bool | None = None

    # Odontogram mapping
    odontogram_mapping: OdontogramMappingCreate | None = None

    # Session template. When provided (even as empty list) the server
    # atomically replaces the stored template.
    sessions: list[CatalogItemSessionInput] | None = None

    # See CatalogItemCreate.specialty_ids. Omitted = leave assignments alone.
    specialty_ids: list[UUID] | None = None


class CatalogItemResponse(BaseModel):
    """Schema for catalog item response."""

    id: UUID
    clinic_id: UUID
    category_id: UUID
    internal_code: str
    names: dict[str, str]
    descriptions: dict[str, str] | None

    # Pricing
    default_price: Decimal | None
    cost_price: Decimal | None

    # Scheduling
    default_duration_minutes: int | None
    requires_appointment: bool

    # Tax - references VatType
    vat_type_id: UUID | None
    vat_type: VatTypeBrief | None = Field(
        default=None, validation_alias="vat_type_rel"
    )  # Eager loaded

    # Pricing strategy
    pricing_strategy: str
    pricing_config: dict | None
    surface_prices: dict[str, Decimal] | None = None

    # Stage of care
    default_phase: str | None = None

    # Treatment characteristics
    treatment_scope: str
    is_diagnostic: bool
    requires_surfaces: bool
    dentition: str = "both"

    # Material
    material_notes: str | None

    # Status
    is_active: bool
    is_visible: bool = True
    is_system: bool
    deleted_at: datetime | None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Related
    category: CategoryResponse | None = None
    odontogram_mapping: OdontogramMappingResponse | None = None
    sessions: list[CatalogItemSessionResponse] = Field(default_factory=list)
    specialties: list[SpecialtyBrief] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CatalogItemBrief(BaseModel):
    """Brief catalog item info for lists."""

    id: UUID
    internal_code: str
    names: dict[str, str]
    default_price: Decimal | None
    default_duration_minutes: int | None
    is_active: bool
    # What a picker needs to decide before it offers the item: whether it is
    # waiting for a tooth, and whether it is a finding rather than something
    # you can plan.
    treatment_scope: str
    is_diagnostic: bool

    model_config = ConfigDict(from_attributes=True)


class CatalogItemSearchResult(CatalogItemBrief):
    """A search hit, with the discipline it is shown under."""

    #: One discipline, even when the treatment belongs to several
    #: (``CatalogService.primary_specialties``). None when it has none enabled.
    specialty: SpecialtyBrief | None = None


# ============================================================================
# Odontogram Integration Schemas
# ============================================================================


class OdontogramTreatmentResponse(BaseModel):
    """Schema for treatments with odontogram integration.

    Used by the odontogram component to display treatments with proper visualization
    plus pricing hints so the frontend can preview costs before confirming.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    internal_code: str
    names: dict[str, str]
    default_price: Decimal | None
    treatment_scope: str
    requires_surfaces: bool
    is_diagnostic: bool
    #: Which teeth it can be done on: the bar hides it where it cannot be.
    dentition: str = "both"

    # Pricing strategy (for multi-tooth price preview).
    pricing_strategy: str
    pricing_config: dict | None = None
    surface_prices: dict[str, Decimal] | None = None

    # Odontogram specific
    odontogram_treatment_type: str
    visualization_rules: list[dict]
    visualization_config: dict
    clinical_category: str

    # Category info
    category_key: str
    category_names: dict[str, str]


class OdontogramTreatmentsByCategory(BaseModel):
    """Grouped treatments for TreatmentBar display."""

    category_key: str
    category_names: dict[str, str]
    treatments: list[OdontogramTreatmentResponse]


# ============================================================================
# Search/Filter Schemas
# ============================================================================


class CatalogSearchParams(BaseModel):
    """Search parameters for catalog items."""

    query: str | None = None  # Search in names, codes
    category_id: UUID | None = None
    is_active: bool | None = True
    treatment_scope: Literal["tooth", "multi_tooth", "global_mouth", "global_arch"] | None = None
    has_odontogram_mapping: bool | None = None
