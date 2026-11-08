"""Commissions module database models."""

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic
    from app.modules.professionals.models import Professional


class CommissionAgreement(Base, TimestampMixin):
    """What the clinic has agreed to pay one professional.

    A general percentage plus, optionally, a different one for specific
    treatments of the catalogue (``CommissionRate``). Mutable on purpose:
    an issued liquidation copies the percentages it used, so renegotiating
    never rewrites what somebody was already paid.
    """

    __tablename__ = "commission_agreements"
    __table_args__ = (
        UniqueConstraint("clinic_id", "professional_id", name="uq_commission_agreement"),
        CheckConstraint(
            "default_percent >= 0 AND default_percent <= 100",
            name="ck_commission_agreement_percent_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    # FK allowed: `professionals` is in `manifest.depends`.
    professional_id: Mapped[UUID] = mapped_column(
        ForeignKey("professionals.id", ondelete="CASCADE"), index=True
    )

    #: ``collected`` or ``earned`` — see `liquidations` for why both exist.
    basis: Mapped[str] = mapped_column(String(10), default="collected")
    #: ``None`` when only specific treatments carry a percentage.
    default_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    clinic: Mapped["Clinic"] = relationship(foreign_keys=[clinic_id])
    professional: Mapped["Professional"] = relationship()
    rates: Mapped[list["CommissionRate"]] = relationship(
        back_populates="agreement",
        cascade="all, delete-orphan",
        order_by="CommissionRate.created_at",
    )


class CommissionRate(Base, TimestampMixin):
    """A percentage for one treatment of the catalogue, overriding the default.

    ``catalog_item_id`` carries no foreign key: the catalog is another App,
    reached through ``TreatmentCatalogue`` (ADR 0039), and a rate must
    survive that App being switched off.
    """

    __tablename__ = "commission_rates"
    __table_args__ = (
        UniqueConstraint("agreement_id", "catalog_item_id", name="uq_commission_rate_item"),
        CheckConstraint("percent >= 0 AND percent <= 100", name="ck_commission_rate_percent_range"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    agreement_id: Mapped[UUID] = mapped_column(
        ForeignKey("commission_agreements.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    agreement: Mapped[CommissionAgreement] = relationship(back_populates="rates")
