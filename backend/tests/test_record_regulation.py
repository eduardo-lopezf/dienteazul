"""The regulation a clinic's clinical record refers to.

What these pin: it is the clinic's line of text; the product only offers
one for the country the clinic is in; an empty line prints none and is
not the same as never having chosen; and it is printed on the sheet the
patient signs and on the record that is handed over.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.regulation import DEFAULTS, SETTINGS_KEY, default_regulation, record_regulation
from app.modules.patients.models import Patient
from app.modules.patients_clinical.questionnaire_pdf import render_html

URL = "/api/v1/auth/clinic/settings/record-regulation"
NOM = DEFAULTS["MX"]


def _clinic(**fields) -> Clinic:
    return Clinic(name="C", tax_id="X", **fields)


def test_the_default_follows_the_country_the_clinic_is_in() -> None:
    assert default_regulation(_clinic(address={"country": "mx"}, currency="EUR")) == NOM
    # No address yet: the currency it charges in says where it is.
    assert default_regulation(_clinic(address={}, currency="MXN")) == NOM
    # A country whose standard the product does not know gets none.
    assert default_regulation(_clinic(address={"country": "ES"}, currency="EUR")) is None
    assert default_regulation(_clinic(address=None, currency="USD")) is None


def test_what_the_clinic_wrote_wins_and_an_empty_line_prints_none() -> None:
    clinic = _clinic(address={"country": "MX"}, currency="MXN")
    assert record_regulation(clinic) == NOM
    clinic.settings = {SETTINGS_KEY: "  Norma propia  "}
    assert record_regulation(clinic) == "Norma propia"
    clinic.settings = {SETTINGS_KEY: ""}
    assert record_regulation(clinic) is None


@pytest.mark.asyncio
async def test_a_clinic_sets_clears_and_restores_its_regulation(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    test_clinic.address = {"country": "MX"}
    await db_session.commit()

    start = (await client.get(URL, headers=auth_headers)).json()["data"]
    assert start == {"text": NOM, "default": NOM, "is_default": True}

    own = "NOM-004-SSA3-2012 y NOM-013-SSA2-2015"
    saved = await client.put(URL, headers=auth_headers, json={"text": f" {own} "})
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"] == {"text": own, "default": NOM, "is_default": False}

    cleared = (await client.put(URL, headers=auth_headers, json={"text": ""})).json()["data"]
    assert cleared == {"text": None, "default": NOM, "is_default": False}

    restored = (await client.put(URL, headers=auth_headers, json={"text": None})).json()["data"]
    assert restored == {"text": NOM, "default": NOM, "is_default": True}

    too_long = await client.put(URL, headers=auth_headers, json={"text": "x" * 301})
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_it_is_not_public(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.put(URL, json={"text": "x"})).status_code == 401


def test_the_sheet_the_patient_signs_names_it_above_the_signature() -> None:
    patient = Patient(first_name="Ana", last_name="Ruiz")
    html = render_html(patient, "es", "", "Norma <propia>")
    line = html.index("Normativa de referencia: Norma &lt;propia&gt;")
    assert line < html.index('class="sign"')
    # And a clinic that prints none gets a sheet without the line.
    assert "Normativa de referencia" not in render_html(patient, "es", "", None)


@pytest.mark.asyncio
async def test_the_blank_questionnaire_and_the_record_are_printed_with_it(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    monkeypatch,
) -> None:
    from app.modules.patients_clinical import questionnaire_pdf
    from app.modules.record import pdf as record_pdf

    test_clinic.address = {"country": "MX"}
    await db_session.commit()

    printed: dict[str, str] = {}
    monkeypatch.setattr(
        questionnaire_pdf, "_html_to_pdf", lambda html: printed.setdefault("form", html).encode()
    )
    monkeypatch.setattr(
        record_pdf, "_html_to_pdf", lambda html: printed.setdefault("record", html).encode()
    )

    form = await client.get(
        f"/api/v1/patients_clinical/patients/{test_patient.id}/questionnaire-form",
        headers=auth_headers,
    )
    assert form.status_code == 200, form.text
    assert f"Normativa de referencia: {NOM}" in printed["form"]

    handed = await client.post(
        f"/api/v1/record/patients/{test_patient.id}/disclosures",
        headers=auth_headers,
        json={
            "purpose": "continuity_of_care",
            "recipient_name": "Dra. Laura Méndez",
            "evidence": "Valoración de endodoncia en 46",
            "scope": ["patients.identification"],
        },
    )
    assert handed.status_code == 201, handed.text
    assert f"Normativa de referencia: {NOM}" in printed["record"]
