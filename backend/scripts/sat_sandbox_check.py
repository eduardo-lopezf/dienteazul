"""Check the SAT module against Facturama's sandbox, end to end.

Answers what Facturama's docs leave open (``docs/technical/sat_cfdi/overview.md``):
Basic authentication and the sandbox host, what registering an RFC that
already has a CSD does, how an exempt line comes out in the stamped XML,
whether a repeated Folio + Date gives back the same CFDI, what an error
looks like, and what a cancellation answers.

It uses the module's own code — ``csd.read_csd``, ``pac.FacturamaClient``
and ``cfdi_builder.build_ingreso`` — and only the sandbox: nothing reaches
the SAT. It reads the database and writes nothing to it.

The Facturama account is the clinic's own — each tenant enters it in
Settings → Billing & tax → SAT; it never comes from the environment — so
the script takes the clinic and uses its sandbox user and password. It
also needs a test CSD (Facturama publishes the SAT's at
https://cdnfacturama.azureedge.net/content/csd-pruebas.zip, password
``12345678a``)::

    docker-compose exec backend python scripts/sat_sandbox_check.py \\
        --clinic <clinic id> --cer /tmp/sat-csd/eku.cer --key /tmp/sat-csd/eku.key
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app import database  # noqa: E402
from app.modules.sat_cfdi.cfdi_builder import Issuer, Payment, Receiver, build_ingreso  # noqa: E402
from app.modules.sat_cfdi.csd import CsdError, read_csd  # noqa: E402
from app.modules.sat_cfdi.models import SatSettings  # noqa: E402
from app.modules.sat_cfdi.pac import BASE_URLS, FacturamaClient, PacError  # noqa: E402


def _title(text: str) -> None:
    print(f"\n=== {text}")


def _raw(response: httpx.Response) -> str:
    return f"HTTP {response.status_code}: {response.text[:800]}"


def _line(description: str, price: str, vat: float) -> SimpleNamespace:
    return SimpleNamespace(
        description=description,
        internal_code=None,
        unit_price=Decimal(price),
        quantity=1,
        line_discount=Decimal("0"),
        vat_rate=vat,
    )


async def main(args: argparse.Namespace) -> int:
    async with database.async_session_maker() as db:
        settings = (
            await db.execute(select(SatSettings).where(SatSettings.clinic_id == args.clinic))
        ).scalar_one_or_none()
    user = settings.facturama_user("sandbox") if settings else None
    password = settings.facturama_password("sandbox") if settings else None
    if not (user and password):
        print(
            "La clínica no tiene usuario y contraseña de Facturama para pruebas: "
            "Configuración → Facturación e impuestos → SAT."
        )
        return 2

    cer, key = Path(args.cer).read_bytes(), Path(args.key).read_bytes()
    _title("1. El CSD, leído por csd.read_csd")
    try:
        info = read_csd(cer, key, args.password)
    except CsdError as exc:
        print(f"No se puede usar: {exc}")
        return 1
    print(info)

    client = FacturamaClient("sandbox", user=user, password=password)

    _title("2. Registrarlo (POST /api-lite/csds), y otra vez (¿qué pasa si ya está?)")
    for attempt in (1, 2):
        try:
            await client.register_csd(info.rfc, cer, key, args.password, replace=False)
            print(f"POST #{attempt}: OK")
        except PacError as exc:
            print(f"POST #{attempt}: {'transitorio' if exc.transient else 'rechazado'} — {exc}")
    try:
        await client.register_csd(info.rfc, cer, key, args.password, replace=True)
        print("PUT: OK")
    except PacError as exc:
        print(f"PUT: {'transitorio' if exc.transient else 'rechazado'} — {exc}")

    now = datetime.now(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%dT%H:%M:%S")
    payload = build_ingreso(
        folio=f"DA-SANDBOX-{datetime.now():%Y%m%d%H%M%S}",
        cfdi_date=now,
        currency="MXN",
        issuer=Issuer(rfc=info.rfc, name=args.name, regime=args.regime, postal_code=args.zip),
        receiver=Receiver(
            rfc="XAXX010101000",
            name="PUBLICO EN GENERAL PRUEBA",
            regime="616",
            tax_zip_code=args.zip,
            cfdi_use="S01",
        ),
        items=[_line("Limpieza dental", "850.00", 0.0), _line("Cepillo dental", "100.00", 16.0)],
        product_code=args.product_code,
        unit_code="E48",
        payment=Payment(method="PUE", form="01"),
    )

    _title("3. Timbrar un ingreso: una línea exenta y otra al 16 %")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    try:
        stamped = await client.stamp_cfdi(payload)
    except PacError as exc:
        print(f"{'Transitorio' if exc.transient else 'Rechazado'}: {exc}")
        stamped = None
    if stamped:
        print(f"UUID {stamped.uuid} · Id {stamped.pac_id}")
        for node in re.findall(r"<cfdi:Traslado [^>]*/>", stamped.xml):
            print("  ", node)

        _title("4. El mismo Folio y Date otra vez (¿devuelve el mismo CFDI?)")
        try:
            again = await client.stamp_cfdi(payload)
            same = "el mismo" if again.uuid == stamped.uuid else f"OTRO ({again.uuid})"
            print(f"UUID {again.uuid}: {same}")
        except PacError as exc:
            print(f"{'Transitorio' if exc.transient else 'Rechazado'}: {exc}")

    base = BASE_URLS["sandbox"]
    async with httpx.AsyncClient(base_url=base, auth=(user, password), timeout=30) as raw:
        _title("5. Un error a propósito (ProductCode inválido), sin interpretar")
        broken = {**payload, "Folio": payload["Folio"] + "-ERR"}
        broken["Items"] = [{**payload["Items"][0], "ProductCode": "00000000"}]
        print(_raw(await raw.post("/api-lite/4/cfdis", json=broken)))

        if stamped:
            _title("6. Cancelarlo con motivo 02 (DELETE /api-lite/cfdis/{id}), sin interpretar")
            print(
                _raw(await raw.delete(f"/api-lite/cfdis/{stamped.pac_id}", params={"motive": "02"}))
            )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--clinic", required=True, help="Id of the clinic whose account is used")
    parser.add_argument("--cer", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--password", default="12345678a")
    parser.add_argument("--name", default="ESCUELA KEMPER URGATE")
    parser.add_argument("--regime", default="601")
    parser.add_argument("--zip", default="42501")
    # Any code valid in c_ClaveProdServ will do for the sandbox; this one is
    # Facturama's own example. The clinic's real one is its accountant's call.
    parser.add_argument("--product-code", default="10101504")
    sys.exit(asyncio.run(main(parser.parse_args())))
