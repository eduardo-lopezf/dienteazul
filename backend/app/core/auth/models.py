"""Core authentication and authorization models."""

from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.privacy import AccountTier, DataClass, PiiKind, pii
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.modules.agenda.models import Appointment, Cabinet
    from app.modules.patients.models import Patient


# Account/business tiers a Clinic row can operate under. The taxonomy and
# the rule pairing it with a custody mode live in
# ``app.core.privacy.tiers``; this is the string view of it, kept because
# the column stores text and the CHECK constraint below is built from it.
# Root is deliberately not a value — it is a platform-level actor, not a
# kind of clinic, and does not belong to this taxonomy.
ACCOUNT_TIERS: Final[list[str]] = [tier.value for tier in AccountTier]


class Clinic(Base, TimestampMixin):
    """Clinic entity - the main organizational unit."""

    __tablename__ = "clinics"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), info=pii(PiiKind.NAME))
    # RFC in Mexico, CIF/NIF in Spain — the column is the tax identifier
    # of the clinic whatever the jurisdiction calls it.
    tax_id: Mapped[str] = mapped_column(
        String(20), info=pii(PiiKind.NATIONAL_ID, data_class=DataClass.FINANCIAL)
    )
    legal_name: Mapped[str | None] = mapped_column(
        String(200), default=None, info=pii(PiiKind.NAME, data_class=DataClass.FINANCIAL)
    )
    address: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    phone: Mapped[str | None] = mapped_column(String(20), info=pii(PiiKind.PHONE))
    email: Mapped[str | None] = mapped_column(String(255), info=pii(PiiKind.EMAIL))
    # IANA timezone id (e.g. "Europe/Madrid"). Single source of truth
    # for any module that needs local-time semantics — schedules,
    # reports, future billing date-windows, etc.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="America/Mexico_City"
    )
    # ISO 4217 currency code. Single source of truth for any module
    # that renders money — budgets, invoices, catalog, reports.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="MXN")
    # Account/business tier — see ``AccountTier``. Mandatory at creation
    # and deliberately without a server default: a clinic that came into
    # existence without anyone deciding its tier would get one by
    # accident, and the tier is half of a commercial pairing whose other
    # half (custody) is decided by the deployment. Still gates no
    # behaviour at runtime (ADR 0024 rule 3) — what a tier is *allowed*
    # to be pairs with ``CustodyMode`` in ``app.core.privacy.tiers``, and
    # that check runs at creation, not on every request. Named
    # ``account_tier`` and not ``tenant_type`` because a tenant is the
    # DB-isolation unit (ADR 0012) and a clinic lives *inside* one — the
    # old name put two unrelated concepts under the same word (ADR 0023).
    account_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    # Apps chosen for the clinic when it was created, by their name in
    # ``apps.json``. ``None`` when nobody chose — the first clinic of a
    # deployment, made by ``/auth/setup`` — and that means all of them.
    # A clinic only has the Apps on its list: the routes of the others
    # answer 404 to its members (``get_clinic_context``), and their menu
    # entries and permissions are left out (``/modules/-/active``,
    # ``/auth/me``). What runs at all is still the deployment's decision
    # (ADR 0038); this narrows it per clinic.
    apps: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    # Apps the clinic does not have but may switch on itself, from
    # Settings → Apps. An App on neither list is not available to it.
    available_apps: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    # When the operator deactivated the clinic. While set, nobody can work
    # in it (``get_clinic_context``); its data is untouched and clearing
    # the column brings it all back.
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        CheckConstraint(
            "account_tier IN (" + ", ".join(f"'{tier}'" for tier in ACCOUNT_TIERS) + ")",
            name="ck_clinics_account_tier",
        ),
    )

    # Relationships
    memberships: Mapped[list["ClinicMembership"]] = relationship(
        back_populates="clinic", cascade="all, delete-orphan"
    )
    patients: Mapped[list["Patient"]] = relationship(back_populates="clinic")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="clinic")
    cabinets: Mapped[list["Cabinet"]] = relationship(
        back_populates="clinic",
        cascade="all, delete-orphan",
        order_by="Cabinet.display_order",
    )


class AuthSession(Base, TimestampMixin):
    """One refresh token's lifetime, so a session can be ended (ADR 0029, invariant 3).

    Before this table the only revocation was ``User.token_version``: a
    global switch that logs a user out of every device at once and is
    incremented in exactly one place, when an account is deactivated. A
    clinic that loses a laptop could not end *that* session without
    ending every other one.

    One row per refresh token. ``id`` is the token's ``jti``, so the
    token itself carries no state — the row is the state. Rotation
    creates a new row and stamps ``rotated_at`` on the old one, and every
    row from one login shares a ``family_id``.

    That pairing is what makes theft detectable. A refresh token is a
    bearer credential: a stolen one is indistinguishable from the real
    one *until somebody uses it twice*. When a token that has already
    been rotated (or revoked) is presented again, one of the two holders
    is an attacker and there is no way to tell which — so the whole
    family dies and both parties have to log in.

    Deliberately holds no IP and no user agent. Both are personal data
    under GDPR and would need classification and a retention policy
    (ADR 0025); neither is needed to *end* a session, only to label one
    in a UI that does not exist yet.
    """

    __tablename__ = "auth_sessions"

    # The refresh token's ``jti``. Not a surrogate key: the token names
    # the row it depends on.
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Constant across every rotation descending from one login, so
    # revoking a compromised chain does not need to walk it.
    family_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    family_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when this token was exchanged for the next one. A rotated token
    # is spent; presenting it again is the reuse signal.
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # ``logout`` | ``reuse`` | ``superseded`` — why the row stopped being
    # usable. Prose for an operator reading the table after an incident.
    revoked_reason: Mapped[str | None] = mapped_column(String(20), default=None)

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None and self.rotated_at is None


class User(Base, TimestampMixin):
    """User account for authentication."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, info=pii(PiiKind.EMAIL)
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100), info=pii(PiiKind.NAME))
    last_name: Mapped[str] = mapped_column(String(100), info=pii(PiiKind.NAME))
    professional_id: Mapped[str | None] = mapped_column(String(50))  # Colegiado number
    is_active: Mapped[bool] = mapped_column(default=True)
    token_version: Mapped[int] = mapped_column(default=0)  # For token revocation
    # Set on an account created with a password its owner did not choose.
    # While it is set the account can sign in, read its own profile and
    # change its password — ``get_clinic_context`` refuses everything
    # else — and ``POST /auth/password`` clears it.
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default=false())

    # Relationships
    # Oldest first. The app works in a user's first clinic, so the order
    # has to be the same at every sign-in — and joining a second clinic
    # must not move anyone out of the one they already work in.
    memberships: Mapped[list["ClinicMembership"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="ClinicMembership.created_at",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class ClinicBrandLogo(Base, TimestampMixin):
    """The logo the workspace shows next to its name, in the sidebar. One
    per clinic (ADR 0043).

    A table of its own rather than a key in ``Clinic.settings``: the
    settings travel with every request, and an image has no business
    there. The name it sits next to does live in the settings (``brand``).
    """

    __tablename__ = "clinic_brand_logos"

    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), primary_key=True)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)


class ClinicLetterhead(Base, TimestampMixin):
    """A letterhead for what the clinic prints: the clinic's own, or one
    professional's.

    ``owner_key`` says whose it is — ``"clinic"`` or a professional's id —
    and is unique per clinic: one letterhead each. The professional is an
    id without a foreign key, because the directory is a module and the
    core chain cannot point into a module's branch. See
    ``app.core.letterhead``.
    """

    __tablename__ = "clinic_letterheads"
    __table_args__ = (
        UniqueConstraint("clinic_id", "owner_key", name="uq_clinic_letterhead_owner"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    owner_key: Mapped[str] = mapped_column(String(36), nullable=False)

    #: Replaces the clinic's name when set.
    heading: Mapped[str | None] = mapped_column(String(120), info=pii(PiiKind.NAME))
    #: A line of its owner's: the professional and their licence, a speciality.
    subheading: Mapped[str | None] = mapped_column(String(200))
    show_address: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: The logo. On the row, loaded only when a document is printed.
    logo: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    logo_mime_type: Mapped[str | None] = mapped_column(String(40))


class ClinicMembership(Base, TimestampMixin):
    """Association between users and clinics with role."""

    __tablename__ = "clinic_memberships"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    role: Mapped[str] = mapped_column(
        String(20)
    )  # admin, dentist, hygienist, assistant, receptionist

    # Relationships
    user: Mapped["User"] = relationship(back_populates="memberships")
    clinic: Mapped["Clinic"] = relationship(back_populates="memberships")


class TierLimit(Base):
    """What a clinic of an account tier is allowed. ``None`` is no limit,
    and so is a tier with no row. Written by the control plane."""

    __tablename__ = "tier_limits"

    tier: Mapped[str] = mapped_column(String(20), primary_key=True)
    #: Users a clinic may add besides its holder.
    extra_users: Mapped[int | None] = mapped_column(Integer)
    #: Disk space for its files, in megabytes.
    storage_mb: Mapped[int | None] = mapped_column(Integer)
