"""Stamping: pending ingreso CFDIs go to Facturama after commit (ADR 0067).

A scheduled job, every minute. A CFDI is due once it is older than its
clinic's ``stamp_delay_minutes`` — billing records a payment after the
invoice is issued, and waiting lets a payment made at the desk make it
``PUE`` — and past its ``next_attempt_at`` after a failure.

Each one is taken with ``FOR UPDATE SKIP LOCKED``, so several backend
processes share the work (ADR 0051). On its first attempt the CFDI fixes
its ``Fecha`` and its payment method and form, and every retry sends the
same: Facturama tells an operation apart by ``Folio`` and ``Date``.

Facturama not answering leaves it ``pending`` for a later attempt;
refusing it makes it ``rejected``, which nothing retries by itself.

Only ingresos (``I``) so far; egresos, payment complements and
cancellations are sent by the layers to come.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.auth.models import Clinic
from app.core.plugins.apps import modules_outside
from app.modules.billing.service import InvoiceService, compute_paid_summary

from . import pac
from .cfdi_builder import Issuer, Payment, Receiver, build_ingreso
from .models import PUBLIC_CFDI_USE, PUBLIC_REGIME, PUBLIC_RFC, SatCfdi, SatSettings
from .receivers import SatReceiverService
from .service import compliance_block

logger = logging.getLogger(__name__)

#: ``payments.method`` → ``c_FormaPago``. A card is taken as credit (``04``):
#: billing does not tell credit from debit (``28``). Insurance and other
#: have no form of their own, so they make the CFDI ``PPD``.
PAYMENT_FORMS = {"cash": "01", "bank_transfer": "03", "direct_debit": "03", "card": "04"}

#: Minutes before the next attempt, by attempts made so far.
_BACKOFF = (5, 15, 60, 240)
_BATCH = 50


class _CannotBuildError(Exception):
    """The CFDI cannot be put together from what the clinic has."""


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=_BACKOFF[min(attempts, len(_BACKOFF)) - 1])


async def _payment(db: AsyncSession, invoice) -> Payment:
    """``PUE`` with the form of the largest payment when it is paid in full,
    ``PPD`` with ``99`` otherwise."""
    _, balance_due = await compute_paid_summary(db, invoice.clinic_id, invoice.id)
    if invoice.total <= 0 or balance_due > 0:
        return Payment(method="PPD", form="99")
    by_method: dict[str, Decimal] = defaultdict(Decimal)
    for link in invoice.invoice_payments:
        by_method[link.payment.method] += link.amount
    form = PAYMENT_FORMS.get(max(by_method, key=by_method.__getitem__)) if by_method else None
    return Payment(method="PUE", form=form) if form else Payment(method="PPD", form="99")


async def _payload(db: AsyncSession, cfdi: SatCfdi, settings: SatSettings) -> dict:
    invoice = await InvoiceService.get_invoice(
        db, cfdi.clinic_id, cfdi.invoice_id, include_items=True, include_payments=True
    )
    clinic = await db.get(Clinic, cfdi.clinic_id)
    if invoice is None or clinic is None:
        raise _CannotBuildError("La factura ya no existe.")
    if not settings.product_code:
        raise _CannotBuildError("Falta la clave de producto o servicio del SAT.")

    rfc = (invoice.billing_tax_id or "").strip().upper()
    if rfc == PUBLIC_RFC:
        receiver = Receiver(
            rfc=rfc,
            name=invoice.billing_name or "",
            regime=PUBLIC_REGIME,
            tax_zip_code=settings.expedition_postal_code or "",
            cfdi_use=PUBLIC_CFDI_USE,
        )
    else:
        profile = await SatReceiverService.get(db, cfdi.clinic_id, rfc)
        if profile is None:
            raise _CannotBuildError(
                f"Faltan el régimen, el código postal fiscal y el uso de {rfc}."
            )
        receiver = Receiver(
            rfc=rfc,
            name=invoice.billing_name or "",
            regime=profile.tax_regime,
            tax_zip_code=profile.tax_zip_code,
            cfdi_use=profile.cfdi_use,
        )

    if cfdi.cfdi_date is None:
        local = datetime.now(UTC).astimezone(ZoneInfo(clinic.timezone))
        cfdi.cfdi_date = local.strftime("%Y-%m-%dT%H:%M:%S")
    if cfdi.payment_method is None:
        payment = await _payment(db, invoice)
        cfdi.payment_method, cfdi.payment_form = payment.method, payment.form

    return build_ingreso(
        folio=invoice.invoice_number or "",
        cfdi_date=cfdi.cfdi_date,
        currency=clinic.currency,
        issuer=Issuer(
            rfc=(clinic.tax_id or "").strip().upper(),
            name=(clinic.legal_name or "").strip(),
            regime=settings.tax_regime or "",
            postal_code=settings.expedition_postal_code or "",
        ),
        receiver=receiver,
        items=sorted(invoice.items, key=lambda item: item.display_order),
        product_code=settings.product_code,
        unit_code=settings.unit_code,
        payment=Payment(method=cfdi.payment_method, form=cfdi.payment_form or "99"),
    )


async def _record(db: AsyncSession, cfdi: SatCfdi) -> None:
    """Tell billing, in ``Invoice.compliance_data["MX"]``."""
    invoice = await InvoiceService.get_invoice(
        db, cfdi.clinic_id, cfdi.invoice_id, include_items=False, include_payments=False
    )
    if invoice is not None:
        invoice.compliance_data = {**(invoice.compliance_data or {}), "MX": compliance_block(cfdi)}


async def _stamp_one(cfdi_id: UUID, now: datetime) -> None:
    async with database.async_session_maker() as db:
        cfdi = (
            await db.execute(
                select(SatCfdi)
                .where(SatCfdi.id == cfdi_id, SatCfdi.state == "pending")
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if cfdi is None:  # another process has it, or it is done
            return
        settings = (
            await db.execute(select(SatSettings).where(SatSettings.clinic_id == cfdi.clinic_id))
        ).scalar_one()

        try:
            payload = await _payload(db, cfdi, settings)
            result = await pac.client_for(settings).stamp_cfdi(payload)
        except _CannotBuildError as exc:
            cfdi.state, cfdi.last_error = "rejected", str(exc)
        except pac.PacError as exc:
            cfdi.attempts += 1
            cfdi.last_error = str(exc)
            if exc.transient:
                cfdi.next_attempt_at = now + _backoff(cfdi.attempts)
            else:
                cfdi.state = "rejected"
        else:
            cfdi.attempts += 1
            cfdi.state = "stamped"
            cfdi.uuid, cfdi.pac_id, cfdi.xml = result.uuid, result.pac_id, result.xml
            cfdi.stamped_at = datetime.now(UTC)
            cfdi.last_error, cfdi.next_attempt_at = None, None

        await _record(db, cfdi)
        await db.commit()
        if cfdi.state == "rejected":
            logger.warning("sat_cfdi: CFDI %s rejected: %s", cfdi.id, cfdi.last_error)


async def _clinics_with_the_module(db: AsyncSession) -> list[UUID]:
    """Clinics that have ``sat_cfdi``: switched on, by an allowed tier, in an
    App they have (ADR 0066). One that switched it off keeps its pending
    CFDIs; they are stamped if it switches it on again."""
    rows = (
        await db.execute(
            select(Clinic.id, Clinic.apps, Clinic.account_tier, Clinic.modules).where(
                Clinic.modules.contains(["sat_cfdi"])
            )
        )
    ).all()
    return [
        row.id
        for row in rows
        if "sat_cfdi" not in modules_outside(row.apps, row.account_tier, row.modules)
    ]


async def stamp_due(now: datetime | None = None) -> None:
    """Stamp every ingreso CFDI that is due. The scheduled job."""
    now = now or datetime.now(UTC)
    async with database.async_session_maker() as db:
        clinics = await _clinics_with_the_module(db)
        if not clinics:
            return
        due = (
            (
                await db.execute(
                    select(SatCfdi.id)
                    .join(SatSettings, SatSettings.clinic_id == SatCfdi.clinic_id)
                    .where(
                        SatCfdi.clinic_id.in_(clinics),
                        SatCfdi.kind == "I",
                        SatCfdi.state == "pending",
                        SatCfdi.created_at
                        <= now - func.make_interval(0, 0, 0, 0, 0, SatSettings.stamp_delay_minutes),
                        or_(SatCfdi.next_attempt_at.is_(None), SatCfdi.next_attempt_at <= now),
                    )
                    .order_by(SatCfdi.created_at)
                    .limit(_BATCH)
                )
            )
            .scalars()
            .all()
        )
    for cfdi_id in due:
        try:
            await _stamp_one(cfdi_id, now)
        except Exception:
            # One CFDI must not stop the rest; it stays pending and is tried again.
            logger.exception("sat_cfdi: stamping %s failed", cfdi_id)
