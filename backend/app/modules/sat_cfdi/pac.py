"""The PAC that seals and stamps CFDIs: Facturama, API Multiemisor (ADR 0067).

``PacClient`` is what the module asks of a PAC; ``FacturamaClient`` is the
one there is: it registers a clinic's CSD and stamps CFDIs, with the
clinic's own Facturama account (``SatSettings``), never the deployment's.

From Facturama's docs (``/api-lite/csds``): ``POST`` registers the CSD of
an RFC, ``PUT /{rfc}`` replaces it; the body carries ``Rfc``,
``Certificate`` and ``PrivateKey`` in Base64 and ``PrivateKeyPassword``.
Basic authentication and the hosts come from Facturama's SDK and its
OpenAPI examples, and what an error looks like is not documented: to be confirmed
against the sandbox. ``GET /api-lite/csds`` is never called — the docs
show it answering with the key's password in clear.

Stamping is ``POST /api-lite/4/cfdis``; the answer carries Facturama's
``Id``, the stamped ``XmlBase64`` and ``TaxStamp.Uuid``. Facturama tells an
operation apart by ``Folio`` and ``Date``, so a retry sends both
unchanged (``SatCfdi.cfdi_date``).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .models import SatSettings

BASE_URLS = {
    "sandbox": "https://apisandbox.facturama.mx",
    "production": "https://api.facturama.mx",
}
_TIMEOUT = 30.0


class PacError(Exception):
    """The PAC did not do it. ``transient``: try again later; otherwise the
    PAC refused what it was sent, and the message says why."""

    def __init__(self, message: str, *, transient: bool) -> None:
        self.transient = transient
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class StampResult:
    #: The PAC's own id for the CFDI.
    pac_id: str
    #: The SAT's folio fiscal.
    uuid: str
    xml: str


class PacClient(Protocol):
    async def register_csd(
        self, rfc: str, cer: bytes, key: bytes, password: str, *, replace: bool
    ) -> None: ...

    async def stamp_cfdi(self, payload: dict[str, Any]) -> StampResult: ...


def _said(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300].strip()
    if isinstance(body, dict):
        return str(body.get("Message") or body.get("message") or body)[:300]
    return str(body)[:300]


class FacturamaClient:
    def __init__(
        self,
        environment: str,
        *,
        user: str,
        password: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.environment = environment
        self._base = BASE_URLS[environment]
        self._auth = (user, password) if user and password else None
        self._transport = transport

    async def _send(self, method: str, path: str, payload: dict) -> httpx.Response:
        if self._auth is None:
            raise PacError(
                "Faltan el usuario y la contraseña de Facturama de la clínica "
                "(Configuración → Facturación e impuestos → SAT).",
                transient=True,
            )
        try:
            async with httpx.AsyncClient(
                base_url=self._base, auth=self._auth, timeout=_TIMEOUT, transport=self._transport
            ) as client:
                response = await client.request(method, path, json=payload)
        except httpx.HTTPError as exc:
            raise PacError(f"Facturama no respondió: {exc}", transient=True) from exc
        if response.status_code in (401, 403):
            raise PacError("Facturama rechazó las credenciales del despliegue.", transient=False)
        if response.status_code >= 500:
            raise PacError(
                f"Facturama falló (HTTP {response.status_code}); inténtalo más tarde.",
                transient=True,
            )
        if response.status_code >= 400:
            raise PacError(f"Facturama lo rechazó: {_said(response)}", transient=False)
        return response

    async def register_csd(
        self, rfc: str, cer: bytes, key: bytes, password: str, *, replace: bool
    ) -> None:
        payload = {
            "Rfc": rfc,
            "Certificate": base64.b64encode(cer).decode(),
            "PrivateKey": base64.b64encode(key).decode(),
            "PrivateKeyPassword": password,
        }
        if replace:
            await self._send("PUT", f"/api-lite/csds/{rfc}", payload)
        else:
            await self._send("POST", "/api-lite/csds", payload)

    async def stamp_cfdi(self, payload: dict[str, Any]) -> StampResult:
        response = await self._send("POST", "/api-lite/4/cfdis", payload)
        try:
            body = response.json()
            return StampResult(
                pac_id=str(body["Id"]),
                uuid=str(body["TaxStamp"]["Uuid"]).upper(),
                xml=base64.b64decode(body["XmlBase64"]).decode("utf-8"),
            )
        except (ValueError, KeyError, TypeError) as exc:
            # Stamped or not, the answer cannot be read: retried with the
            # same Folio and Date, Facturama answers for the same operation.
            raise PacError(
                f"Facturama respondió algo que no se entiende: {_said(response)}", transient=True
            ) from exc


def client_for(settings: SatSettings | None) -> PacClient:
    """The PAC for a clinic's environment, with the clinic's own credentials.

    Each tenant has its own Facturama account (``SatSettings``); without
    one the client sends nothing and says so.
    """
    environment = settings.environment if settings else "sandbox"
    user = settings.facturama_user(environment) if settings else None
    password = settings.facturama_password(environment) if settings else None
    return FacturamaClient(environment, user=user or "", password=password or "")
