"""Registering the CSD with Facturama, which seals CFDIs with it.

The CSD is registered when it is uploaded, before it is stored. Facturama
refusing it means it is not stored; Facturama not answering means it is
stored unregistered, and registering is retried from the settings. An
invoice is issued only with the CSD registered in the clinic's
environment — sandbox and production are separate accounts.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.sat_cfdi.models import SatCertificate
from app.modules.sat_cfdi.pac import PacError

from .conftest import ISSUER_RFC, PASSWORD, FakePac, make_csd, set_credentials

SETTINGS = {
    "tax_regime": "601",
    "expedition_postal_code": "42501",
    "environment": "sandbox",
    "product_code": "85121800",
}


async def _upload(client: AsyncClient, headers: dict, csd=None):
    csd = csd or make_csd()
    return await client.post(
        "/api/v1/sat_cfdi/certificate",
        files={
            "cer": ("csd.cer", csd.cer, "application/octet-stream"),
            "key": ("csd.key", csd.key, "application/octet-stream"),
        },
        data={"password": csd.password},
        headers=headers,
    )


async def _settings(client: AsyncClient, headers: dict, **changes) -> dict:
    """The SAT settings, with the clinic's Facturama account in both environments."""
    for environment in ("sandbox", "production"):
        await set_credentials(client, headers, environment)
    response = await client.put(
        "/api/v1/sat_cfdi/settings", json={**SETTINGS, **changes}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _register(client: AsyncClient, headers: dict):
    return await client.post("/api/v1/sat_cfdi/certificate/register", headers=headers)


@pytest.mark.asyncio
async def test_an_uploaded_csd_is_registered_in_the_clinic_s_environment(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic, fake_pac: FakePac
) -> None:
    await _settings(client, auth_headers)

    response = await _upload(client, auth_headers)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert (data["registered_in"], data["registration_error"]) == (["sandbox"], None)
    assert fake_pac.environments == ["sandbox"]
    assert fake_pac.registered == [{"rfc": ISSUER_RFC, "replace": False, "password": PASSWORD}]
    settings = (await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)).json()
    assert settings["data"]["ready"] is True


@pytest.mark.asyncio
async def test_a_renewed_csd_replaces_the_registered_one(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic, fake_pac: FakePac
) -> None:
    await _settings(client, auth_headers)
    await _upload(client, auth_headers)
    await _upload(client, auth_headers, make_csd(number="30001000000500003417"))

    assert [call["replace"] for call in fake_pac.registered] == [False, True]


@pytest.mark.asyncio
async def test_a_csd_facturama_refuses_is_not_stored(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    mexican_clinic: Clinic,
    fake_pac: FakePac,
) -> None:
    await _settings(client, auth_headers)
    fake_pac.fail = PacError("Facturama no acepta el certificado: es una FIEL", transient=False)

    response = await _upload(client, auth_headers)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "sat_cfdi.certificate.pac_refused"
    assert "FIEL" in response.text
    stored = await db_session.execute(
        select(SatCertificate).where(SatCertificate.clinic_id == mexican_clinic.id)
    )
    assert stored.scalars().all() == []


@pytest.mark.asyncio
async def test_while_facturama_does_not_answer_the_csd_waits_to_be_registered(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic, fake_pac: FakePac
) -> None:
    await _settings(client, auth_headers)
    fake_pac.fail = PacError("Facturama no respondió", transient=True)

    uploaded = await _upload(client, auth_headers)

    assert uploaded.status_code == 201, uploaded.text
    data = uploaded.json()["data"]
    assert (data["registered_in"], data["registration_error"]) == ([], "Facturama no respondió")
    settings = (await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)).json()
    assert settings["data"]["ready"] is False
    assert "Facturama" in settings["data"]["missing"]

    still_down = await _register(client, auth_headers)
    assert still_down.status_code == 503, still_down.text
    assert still_down.json()["code"] == "sat_cfdi.pac.unavailable"

    fake_pac.fail = None
    registered = await _register(client, auth_headers)
    assert registered.status_code == 200, registered.text
    assert registered.json()["data"]["registered_in"] == ["sandbox"]
    assert registered.json()["data"]["registration_error"] is None
    settings = (await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)).json()
    assert settings["data"]["ready"] is True


@pytest.mark.asyncio
async def test_another_environment_needs_its_own_registration(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic, fake_pac: FakePac
) -> None:
    await _settings(client, auth_headers)
    await _upload(client, auth_headers)

    data = await _settings(client, auth_headers, environment="production")

    assert data["ready"] is False
    assert "producción" in data["missing"]
    registered = await _register(client, auth_headers)
    assert registered.status_code == 200, registered.text
    assert fake_pac.environments == ["sandbox", "production"]
    # The first time in production: a new registration there.
    assert fake_pac.registered[-1]["replace"] is False
    assert registered.json()["data"]["registered_in"] == ["sandbox", "production"]

    # Back in sandbox it is still registered: nothing to do.
    assert (await _settings(client, auth_headers))["ready"] is True
    settings = (await client.get("/api/v1/sat_cfdi/settings", headers=auth_headers)).json()
    assert settings["data"]["ready"] is True


@pytest.mark.asyncio
async def test_registering_needs_a_csd(
    client: AsyncClient, auth_headers: dict, mexican_clinic: Clinic
) -> None:
    await _settings(client, auth_headers)

    response = await _register(client, auth_headers)

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "sat_cfdi.certificate.missing"
