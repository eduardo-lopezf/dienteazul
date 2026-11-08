"""An ingreso CFDI 4.0 as Facturama's API Multiemisor V4 takes it.

``POST /api-lite/4/cfdis`` (``CfdiLiteBindingModel``) rejects fields it
does not know, so only documented ones are sent. Amounts go as numbers
rounded to cents.

How an exempt line is written is not in Facturama's docs: it is sent as
``TaxObject: "02"`` with an ``IVA Exento`` tax at rate 0 — to confirm
against the sandbox. Dental services by a licensed professional are
exempt (art. 15, fr. XIV LIVA); a line at a rate above 0 carries IVA.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

_CENT = Decimal("0.01")


def _money(value: Decimal) -> float:
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class Issuer:
    rfc: str
    name: str
    regime: str
    #: ``LugarExpedicion``.
    postal_code: str


@dataclass(frozen=True, slots=True)
class Receiver:
    rfc: str
    name: str
    regime: str
    tax_zip_code: str
    cfdi_use: str


@dataclass(frozen=True, slots=True)
class Payment:
    #: ``PUE`` or ``PPD``.
    method: str
    #: ``FormaPago``; ``99`` ("por definir") with ``PPD``.
    form: str


class Line(Protocol):
    description: str
    internal_code: str | None
    unit_price: Decimal
    quantity: int
    line_discount: Decimal
    #: Percent, as billing keeps it (16.0).
    vat_rate: float


def _item(line: Line, product_code: str, unit_code: str) -> dict[str, Any]:
    subtotal = Decimal(line.unit_price) * line.quantity
    discount = Decimal(line.line_discount or 0)
    base = subtotal - discount
    rate = Decimal(str(line.vat_rate or 0)) / 100
    tax = (base * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
    item: dict[str, Any] = {
        "ProductCode": product_code,
        "UnitCode": unit_code,
    }
    if line.internal_code:
        item["IdentificationNumber"] = line.internal_code
    item.update(
        {
            "Description": line.description,
            "UnitPrice": _money(Decimal(line.unit_price)),
            "Quantity": float(line.quantity),
            "Subtotal": _money(subtotal),
        }
    )
    if discount:
        item["Discount"] = _money(discount)
    item["TaxObject"] = "02"
    item["Taxes"] = [
        {
            "Name": "IVA" if rate else "IVA Exento",
            "Base": _money(base),
            "Rate": float(rate),
            "Total": _money(tax),
            "IsRetention": False,
        }
    ]
    item["Total"] = _money(base + tax)
    return item


def build_ingreso(
    *,
    folio: str,
    cfdi_date: str,
    currency: str,
    issuer: Issuer,
    receiver: Receiver,
    items: list[Line],
    product_code: str,
    unit_code: str,
    payment: Payment,
) -> dict[str, Any]:
    return {
        "Folio": folio,
        "Date": cfdi_date,
        "CfdiType": "I",
        "Currency": currency,
        "ExpeditionPlace": issuer.postal_code,
        "Exportation": "01",
        "PaymentMethod": payment.method,
        "PaymentForm": payment.form,
        "Issuer": {"Rfc": issuer.rfc, "Name": issuer.name, "FiscalRegime": issuer.regime},
        "Receiver": {
            "Rfc": receiver.rfc,
            "Name": receiver.name,
            "FiscalRegime": receiver.regime,
            "TaxZipCode": receiver.tax_zip_code,
            "CfdiUse": receiver.cfdi_use,
        },
        "Items": [_item(line, product_code, unit_code) for line in items],
    }
