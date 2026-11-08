"""The ingreso CFDI as Facturama's API Multiemisor V4 takes it.

``POST /api-lite/4/cfdis`` rejects unknown fields; the receiver needs
``Rfc``, ``Name``, ``FiscalRegime`` and ``TaxZipCode``; an IVA line carries
``TaxObject: "02"`` and ``Taxes: [{Name: "IVA", Base, Rate, Total,
IsRetention}]``. How an exempt line is written is not in Facturama's docs
(see ``cfdi_builder``): to confirm against the sandbox.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.modules.sat_cfdi.cfdi_builder import Issuer, Payment, Receiver, build_ingreso

ISSUER = Issuer(rfc="EKU9003173C9", name="ESCUELA KEMPER URGATE", regime="601", postal_code="42501")
PERSON = Receiver(
    rfc="GOMA800101AB1",
    name="ANA GOMEZ MARTINEZ",
    regime="612",
    tax_zip_code="06600",
    cfdi_use="D01",
)


def _item(price: str, quantity: int = 1, *, vat: float = 0.0, discount: str = "0.00", code=None):
    return SimpleNamespace(
        description="Limpieza dental",
        internal_code=code,
        unit_price=Decimal(price),
        quantity=quantity,
        line_discount=Decimal(discount),
        vat_rate=vat,
        display_order=0,
    )


def _build(items, receiver=PERSON, payment=Payment(method="PPD", form="99")) -> dict:
    return build_ingreso(
        folio="FAC-2026-0007",
        cfdi_date="2026-11-07T10:30:00",
        currency="MXN",
        issuer=ISSUER,
        receiver=receiver,
        items=items,
        product_code="85121800",
        unit_code="E48",
        payment=payment,
    )


def test_the_header_issuer_and_receiver() -> None:
    cfdi = _build([_item("500.00")], payment=Payment(method="PUE", form="04"))

    assert {k: v for k, v in cfdi.items() if k != "Items"} == {
        "Folio": "FAC-2026-0007",
        "Date": "2026-11-07T10:30:00",
        "CfdiType": "I",
        "Currency": "MXN",
        "ExpeditionPlace": "42501",
        "Exportation": "01",
        "PaymentMethod": "PUE",
        "PaymentForm": "04",
        "Issuer": {"Rfc": "EKU9003173C9", "Name": "ESCUELA KEMPER URGATE", "FiscalRegime": "601"},
        "Receiver": {
            "Rfc": "GOMA800101AB1",
            "Name": "ANA GOMEZ MARTINEZ",
            "FiscalRegime": "612",
            "TaxZipCode": "06600",
            "CfdiUse": "D01",
        },
    }


def test_a_line_with_iva() -> None:
    [line] = _build([_item("100.00", 2, vat=16.0, discount="20.00", code="LIMP")])["Items"]

    assert line == {
        "ProductCode": "85121800",
        "UnitCode": "E48",
        "IdentificationNumber": "LIMP",
        "Description": "Limpieza dental",
        "UnitPrice": 100.0,
        "Quantity": 2.0,
        "Subtotal": 200.0,
        "Discount": 20.0,
        "TaxObject": "02",
        "Taxes": [
            {"Name": "IVA", "Base": 180.0, "Rate": 0.16, "Total": 28.8, "IsRetention": False}
        ],
        "Total": 208.8,
    }


def test_an_exempt_line() -> None:
    [line] = _build([_item("850.00")])["Items"]

    assert line["TaxObject"] == "02"
    assert line["Taxes"] == [
        {"Name": "IVA Exento", "Base": 850.0, "Rate": 0.0, "Total": 0.0, "IsRetention": False}
    ]
    assert (line["Subtotal"], line["Total"]) == (850.0, 850.0)
    assert "IdentificationNumber" not in line
    assert "Discount" not in line


def test_amounts_are_rounded_to_cents() -> None:
    [line] = _build([_item("33.33", 3, vat=16.0)])["Items"]

    assert line["Subtotal"] == 99.99
    assert line["Taxes"][0]["Total"] == 16.0
    assert line["Total"] == 115.99
