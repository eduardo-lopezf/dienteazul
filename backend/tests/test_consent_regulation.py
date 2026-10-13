"""A consent letter names the regulation the clinic's record refers to.

What these pin: signing keeps a copy of the clinic's line, and the copy
stays when the clinic changes the line afterwards.
"""

import pytest
from httpx import AsyncClient

from tests.test_plan_requires_informed_consent import (  # noqa: F401 — fixture
    CONSENTS,
    _consent,
    _sign,
    setup,
)

REGULATION = "/api/v1/auth/clinic/settings/record-regulation"


@pytest.mark.asyncio
async def test_a_signed_letter_keeps_the_regulation_it_named(
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,  # noqa: F811
) -> None:
    await client.put(REGULATION, headers=auth_headers, json={"text": "NOM-004-SSA3-2012"})
    consent = await _consent(client, auth_headers, setup, None)
    assert consent["regulation"] is None  # nothing is named until it is signed

    await _sign(client, auth_headers, consent)
    await client.put(REGULATION, headers=auth_headers, json={"text": "Otra norma"})

    listed = await client.get(f"{CONSENTS}/patients/{setup['patient_id']}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    signed = next(row for row in listed.json()["data"] if row["id"] == consent["id"])
    assert signed["regulation"] == "NOM-004-SSA3-2012"

    pdf = await client.get(f"{CONSENTS}/{consent['id']}/pdf", headers=auth_headers)
    assert pdf.status_code == 200, pdf.text
