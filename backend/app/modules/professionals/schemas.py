"""Request and response schemas for the professionals directory."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Only dentists and hygienists can receive appointments. Collaborators
# remain useful in the directory (labs, suppliers, assistants) but are not
# schedulable resources.
ProfessionalType = Literal["dentist", "hygienist", "collaborator"]


class SpecialtyBrief(BaseModel):
    """The clinic specialty a professional practises, for display.

    Mirrors the catalog's own brief shape; kept local so the schema module
    does not have to import catalog schemas.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    names: dict[str, str]


class ProfessionalCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    professional_type: ProfessionalType = "dentist"
    specialty_ids: list[UUID] = Field(default_factory=list)
    license_number: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    photo_url: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    is_active: bool = True
    #: The account this person signs in with. Optional — a collaborator can be
    #: in the directory without one — and never inferred from the email.
    user_id: UUID | None = None


class ProfessionalUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    professional_type: ProfessionalType | None = None
    # Authoritative when present: omitted disciplines are unlinked.
    specialty_ids: list[UUID] | None = None
    license_number: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    photo_url: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    is_active: bool | None = None
    user_id: UUID | None = None


class ProfessionalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clinic_id: UUID
    first_name: str
    last_name: str
    full_name: str
    professional_type: ProfessionalType
    specialties: list[SpecialtyBrief] = Field(default_factory=list)  # eager loaded
    license_number: str | None
    email: EmailStr | None
    phone: str | None
    photo_url: str | None
    notes: str | None
    is_active: bool
    # The linked account, if an admin has stated one. This is what makes a
    # clinical entry attributable to a professional; `has_system_access` below
    # is only a hint that a link is probably wanted.
    user_id: UUID | None = None
    # True when `email` matches a user account with a membership in this
    # clinic — computed at response time, not a column on the model.
    has_system_access: bool = False
    created_at: datetime
    updated_at: datetime


class MyProfessionalUpdate(BaseModel):
    """What a professional edits of their own profile.

    Not who the profile is (the account link, the type) nor whether it is
    active: those are the clinic's to decide (``PUT /{id}``).
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    specialty_ids: list[UUID] | None = None
    license_number: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)


class ProfessionalWorkloadResponse(BaseModel):
    """What is assigned to one professional, as the Apps that run say.

    ``patients`` counts each patient once across Apps; ``counts`` holds each
    App's own figures (``appointments``, ``appointments_upcoming``,
    ``plans_in_progress``, ``treatments_pending``, ``treatments_completed``).
    A key is missing when the App that owns it is off.
    """

    professional_id: UUID
    patients: int
    counts: dict[str, int] = Field(default_factory=dict)
