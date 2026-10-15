"""Clinical notes module database models.

Polymorphic clinical-notes store. Notes attach to one of three owner types
and carry a ``note_type`` discriminator that the UI uses for filtering and
color-coding.

Owner / type matrix:

| ``note_type``      | ``owner_type`` | ``owner_id`` references          |
|--------------------|----------------|----------------------------------|
| ``administrative`` | ``patient``    | ``patients.id``                  |
| ``diagnosis``      | ``patient``    | ``patients.id`` (optional tooth) |
| ``treatment``      | ``treatment``  | ``treatments.id`` (odontogram)   |
| ``treatment_plan`` | ``plan``       | ``treatment_plans.id``           |
| ``appointment_clinical``       | ``appointment`` | ``appointments.id``      |
| ``appointment_administrative`` | ``appointment`` | ``appointments.id``      |

``owner_id`` has no DB-level FK (polymorphic) — the service layer validates
that the owner exists in the same clinic before insert.

Document attachments live in the ``media`` module: this module registers
its owner_types (``patient``, ``treatment``, ``plan``,
``appointment_treatment``, ``clinical_note``) with
``media.attachment_registry`` at import time and consumes
``media.AttachmentService`` for link/unlink/list operations. The legacy
``clinical_note_attachments`` table was migrated into
``media.media_attachments`` in revision ``cn_0002``.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

# Note types — discriminator surfaced to the UI for filtering + color-coding.
NOTE_TYPE_ADMINISTRATIVE = "administrative"
NOTE_TYPE_DIAGNOSIS = "diagnosis"
NOTE_TYPE_TREATMENT = "treatment"
NOTE_TYPE_TREATMENT_PLAN = "treatment_plan"
NOTE_TYPE_APPOINTMENT_CLINICAL = "appointment_clinical"
NOTE_TYPE_APPOINTMENT_ADMINISTRATIVE = "appointment_administrative"
NOTE_TYPES = (
    NOTE_TYPE_ADMINISTRATIVE,
    NOTE_TYPE_DIAGNOSIS,
    NOTE_TYPE_TREATMENT,
    NOTE_TYPE_TREATMENT_PLAN,
    NOTE_TYPE_APPOINTMENT_CLINICAL,
    NOTE_TYPE_APPOINTMENT_ADMINISTRATIVE,
)

# Owner types — what ``owner_id`` references.
NOTE_OWNER_PATIENT = "patient"
NOTE_OWNER_TREATMENT = "treatment"
NOTE_OWNER_PLAN = "plan"
NOTE_OWNER_APPOINTMENT = "appointment"
NOTE_OWNER_TYPES = (
    NOTE_OWNER_PATIENT,
    NOTE_OWNER_TREATMENT,
    NOTE_OWNER_PLAN,
    NOTE_OWNER_APPOINTMENT,
)


if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User


class ClinicalNote(Base, TimestampMixin):
    """Timestamped clinical note.

    Polymorphic on ``owner_type`` (``patient`` / ``treatment`` / ``plan``).
    ``note_type`` adds a UI-facing discriminator independent of the linkage —
    e.g. an ``administrative`` note also sits on a patient owner, but the UI
    treats it differently from a ``diagnosis`` note on the same patient.
    """

    __tablename__ = "clinical_notes"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)

    note_type: Mapped[str] = mapped_column(String(40))
    owner_type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True))

    # Optional tooth pin used by ``diagnosis`` notes that the dentist tied
    # to a specific tooth while exploring with the odontogram. NULL for
    # every other note_type.
    tooth_number: Mapped[int | None] = mapped_column(Integer)

    body: Mapped[str] = mapped_column(Text)
    #: Vital signs taken at the visit the note is about, when they were:
    #: ``systolic``/``diastolic`` (mmHg), ``heart_rate`` and
    #: ``respiratory_rate`` (per minute), ``temperature_c``. Part of the
    #: note as written — an amendment rewords the text, not the readings.
    vitals: Mapped[dict | None] = mapped_column(JSONB)
    #: The account that operated the software. The audit trail, unchanged.
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    #: Who answers for the note clinically, and through whom an exported record
    #: names a licence (ADR 0032). Two fields rather than one because an
    #: assistant may type what a dentist is responsible for. Resolved from the
    #: acting account's directory profile; NULL when it has none, which is the
    #: truthful answer rather than a guess.
    authored_by_professional_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professionals.id"), default=None, index=True
    )

    # Which version of the text ``body`` currently holds, counting from 1.
    # The current text stays right here, on the note, because that is what
    # every consumer reads and reading it must not cost a join
    # ([ADR 0032](../../../../docs/adr/0032-clinical-record-is-append-only.md)).
    # What changed is that superseding it now files the old text away instead
    # of destroying it.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # When the text was last corrected. NULL means never: the note still says
    # what it said when it was written, and a reader can tell at a glance —
    # which is the distinction that was impossible before, when an amendment
    # and an original were the same thing.
    amended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    clinic: Mapped["Clinic"] = relationship()
    author: Mapped["User"] = relationship()

    __table_args__ = (
        CheckConstraint(
            "note_type IN ('administrative', 'diagnosis', 'treatment', "
            "'treatment_plan', 'appointment_clinical', 'appointment_administrative')",
            name="ck_clinical_notes_note_type",
        ),
        CheckConstraint(
            "owner_type IN ('patient', 'treatment', 'plan', 'appointment')",
            name="ck_clinical_notes_owner_type",
        ),
        CheckConstraint(
            "(note_type = 'administrative' AND owner_type = 'patient' AND tooth_number IS NULL) "
            "OR (note_type = 'diagnosis' AND owner_type = 'patient') "
            "OR (note_type = 'treatment' AND owner_type = 'treatment' AND tooth_number IS NULL) "
            "OR (note_type = 'treatment_plan' AND owner_type = 'plan' "
            "AND tooth_number IS NULL) "
            "OR (note_type = 'appointment_clinical' AND owner_type = 'appointment' "
            "AND tooth_number IS NULL) "
            "OR (note_type = 'appointment_administrative' AND owner_type = 'appointment' "
            "AND tooth_number IS NULL)",
            name="ck_clinical_notes_type_owner_matrix",
        ),
        Index(
            "idx_clinical_notes_owner",
            "clinic_id",
            "owner_type",
            "owner_id",
            "deleted_at",
            "created_at",
        ),
        Index(
            "idx_clinical_notes_patient_recent",
            "clinic_id",
            "note_type",
            "owner_id",
            "deleted_at",
            "created_at",
        ),
        Index("idx_clinical_notes_author", "author_id"),
    )


class ClinicalNoteVersion(Base, TimestampMixin):
    """A superseded body of a note, kept with the reason it was superseded.

    ``clinical_notes.body`` used to be assigned in place: `note.body = body`.
    The prior text was gone, so a correction and an original were the same
    thing, and "what did the note say on the day of the procedure" — the
    question a complaint or an insurance review turns on — had no answer.

    An amendment is now a new version. The note keeps the current text; each
    earlier text lands here with its number, the instant it stopped being
    current, who replaced it and why. Reconstructing the note at any past
    instant is walking these rows: the first one whose ``superseded_at`` is
    later than the instant asked about holds the text that was on screen then,
    and if none is, the note itself does.

    Rows are never updated or deleted. A wrong amendment is corrected by
    amending again, which is the same rule the rest of the clinical surface
    follows.
    """

    __tablename__ = "clinical_note_versions"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    note_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinical_notes.id", ondelete="CASCADE"),
        index=True,
    )

    #: Which version this text was. 1 is the note as first written.
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)

    superseded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: The account that replaced this text. The note's own ``author_id`` still
    #: names whoever wrote it — an admin correcting someone else's note does
    #: not become its author.
    superseded_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    #: And who answers for the correction clinically. A correction is part of
    #: what the note says, so it is attributable the same way the original is.
    superseded_by_professional_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professionals.id"), default=None
    )
    #: Free text, optional. Asking for a reason and refusing the amendment
    #: without one would buy a record full of "correction"; the useful ones are
    #: written when there is something to say.
    amendment_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("note_id", "version", name="uq_clinical_note_version"),
        Index("idx_clinical_note_versions_note", "note_id", "version"),
    )
