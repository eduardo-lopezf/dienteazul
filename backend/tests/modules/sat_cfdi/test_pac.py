"""The Facturama client, against a fake transport (nothing leaves the test).

From Facturama's API Multiemisor docs: ``POST /api-lite/csds`` registers
the CSD of an RFC, ``PUT /api-lite/csds/{rfc}`` replaces it, with
``Rfc``, ``Certificate`` and ``PrivateKey`` (both Base64) and
``PrivateKeyPassword``. Basic authentication and the two hosts come from
Facturama's SDK; what an error looks like is not documented, so the
client reads ``Message`` when there is one and the text otherwise.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.modules.sat_cfdi.pac import FacturamaClient, PacError

CER, KEY = b"\x30\x82cer", b"\x30\x82key"


def _client(handler, environment: str = "sandbox") -> FacturamaClient:
    return FacturamaClient(
        environment,
        user="clinica",
        password="secreta",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment", "replace", "method", "url"),
    [
        ("sandbox", False, "POST", "https://apisandbox.facturama.mx/api-lite/csds"),
        ("sandbox", True, "PUT", "https://apisandbox.facturama.mx/api-lite/csds/EKU9003173C9"),
        ("production", False, "POST", "https://api.facturama.mx/api-lite/csds"),
    ],
)
async def test_registering_a_csd(environment, replace, method, url) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    await _client(handler, environment).register_csd(
        "EKU9003173C9", CER, KEY, "12345678a", replace=replace
    )

    [request] = seen
    assert (request.method, str(request.url)) == (method, url)
    assert (
        request.headers["Authorization"] == "Basic " + base64.b64encode(b"clinica:secreta").decode()
    )
    assert json.loads(request.content) == {
        "Rfc": "EKU9003173C9",
        "Certificate": base64.b64encode(CER).decode(),
        "PrivateKey": base64.b64encode(KEY).decode(),
        "PrivateKeyPassword": "12345678a",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "transient", "says"),
    [
        (
            httpx.Response(400, json={"Message": "El certificado no es un CSD"}),
            False,
            "no es un CSD",
        ),
        (httpx.Response(400, text="bad request"), False, "bad request"),
        (httpx.Response(401), False, "credenciales"),
        (httpx.Response(503), True, "503"),
    ],
)
async def test_what_facturama_answers_is_said(response, transient, says) -> None:
    with pytest.raises(PacError) as caught:
        await _client(lambda request: response).register_csd(
            "EKU9003173C9", CER, KEY, "x", replace=False
        )
    assert caught.value.transient is transient
    assert says in str(caught.value)


@pytest.mark.asyncio
async def test_an_unreachable_facturama_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(PacError) as caught:
        await _client(handler).register_csd("EKU9003173C9", CER, KEY, "x", replace=False)
    assert caught.value.transient is True


@pytest.mark.asyncio
async def test_without_credentials_nothing_is_sent() -> None:
    calls: list[httpx.Request] = []
    client = FacturamaClient(
        "sandbox",
        user="",
        password="",
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)),
    )

    with pytest.raises(PacError) as caught:
        await client.register_csd("EKU9003173C9", CER, KEY, "x", replace=False)

    assert caught.value.transient is True
    assert "Facturama" in str(caught.value)
    assert calls == []


@pytest.mark.asyncio
async def test_stamping_a_cfdi() -> None:
    seen: list[httpx.Request] = []
    xml = '<?xml version="1.0"?><cfdi:Comprobante Version="4.0"/>'

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "Id": "J6MjEYRjnLnV6aMCK8dV-w2",
                "XmlBase64": base64.b64encode(xml.encode()).decode(),
                "TaxStamp": {"Uuid": "fe3c73d5-7881-49e0-80a3-e6c7e2eece40"},
            },
        )

    result = await _client(handler).stamp_cfdi({"Folio": "FAC-1", "Date": "2026-11-07T10:00:00"})

    [request] = seen
    assert (request.method, str(request.url)) == (
        "POST",
        "https://apisandbox.facturama.mx/api-lite/4/cfdis",
    )
    assert json.loads(request.content) == {"Folio": "FAC-1", "Date": "2026-11-07T10:00:00"}
    assert (result.pac_id, result.uuid, result.xml) == (
        "J6MjEYRjnLnV6aMCK8dV-w2",
        "FE3C73D5-7881-49E0-80A3-E6C7E2EECE40",
        xml,
    )


@pytest.mark.asyncio
async def test_an_answer_that_cannot_be_read_is_retried() -> None:
    with pytest.raises(PacError) as caught:
        await _client(lambda request: httpx.Response(200, json={"Id": "x"})).stamp_cfdi({})
    assert caught.value.transient is True
