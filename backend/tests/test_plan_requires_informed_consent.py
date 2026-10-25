"""A treatment plan waits for the patient's informed consent.

What these pin: the letter is not mandatory until the clinic switches
the rule on. With it on, a plan is not confirmed until an informed
consent written for it is signed; one for another plan, of another kind
or revoked does not count; and with no consents kept at all (the
Clinical record App off) nobody asks.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.consents.providers import requires_informed_for_plan
from app.modules.professionals.models import Professional
from app.modules.treatment_plan import service as plan_service
from app.modules.treatment_plan.errors import ERROR_CATALOG
from tests.test_treatment_plan import (
    _create_plan_with_items,
    _ensure_clinic_and_patient,
    _seed_catalog_crown,
)

PLANS = "/api/v1/treatment_plan/treatment-plans"
CONSENTS = "/api/v1/consents"
SETTINGS = f"{CONSENTS}/settings"


@pytest.fixture
async def setup(db_session: AsyncSession, auth_headers: dict, client: AsyncClient) -> dict:
    """A clinic that asks for the consent, with a dentist to explain it."""
    ctx = await _ensure_clinic_and_patient(db_session, client, auth_headers)
    ctx["crown_id"] = await _seed_catalog_crown(db_session, ctx["clinic_id"])
    # Off until a clinic asks for it.
    on = await client.put(SETTINGS, headers=auth_headers, json={"require_informed_for_plan": True})
    assert on.status_code == 200, on.text
    dentist = Professional(
        id=uuid4(),
        clinic_id=ctx["clinic_id"],
        first_name="Marta",
        last_name="Ruiz",
        professional_type="dentist",
        license_number="CED-12345",
        is_active=True,
    )
    db_session.add(dentist)
    await db_session.commit()
    ctx["dentist_id"] = str(dentist.id)
    return ctx


async def _consent(
    client: AsyncClient, headers: dict, setup: dict, plan_id: str | None, kind: str = "informed"
) -> dict:
    created = await client.post(
        f"{CONSENTS}/patients/{setup['patient_id']}",
        headers=headers,
        json={
            "kind": kind,
            "title": "Corona en 16",
            "body": "Riesgos y alternativas explicados.",
            "plan_id": plan_id,
            "explained_by_professional_id": setup["dentist_id"] if kind == "informed" else None,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _sign(client: AsyncClient, headers: dict, consent: dict) -> None:
    signed = await client.post(
        f"{CONSENTS}/{consent['id']}/sign",
        headers=headers,
        json={
            "signed_by_name": "Luis Soto",
            "signer_capacity": "patient",
            "signature_data": {"png": "data:image/png;base64,AAAA"},
        },
    )
    assert signed.status_code == 200, signed.text


async def _confirm(client: AsyncClient, headers: dict, plan_id: str):
    return await client.post(f"{PLANS}/{plan_id}/confirm", headers=headers)


def test_a_clinic_asks_for_it_only_when_it_said_so() -> None:
    def clinic(settings):
        return Clinic(name="C", tax_id="X", settings=settings)

    assert not requires_informed_for_plan(clinic(None))
    assert not requires_informed_for_plan(clinic({"slot_duration_min": 15}))
    assert not requires_informed_for_plan(clinic({"consents": {}}))
    assert not requires_informed_for_plan(
        clinic({"consents": {"require_informed_for_plan": False}})
    )
    assert requires_informed_for_plan(clinic({"consents": {"require_informed_for_plan": True}}))


@pytest.mark.asyncio
async def test_a_plan_is_not_confirmed_without_its_signed_consent(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])

    refused = await _confirm(client, auth_headers, plan_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["message"] == "informed_consent_required"
    definition = ERROR_CATALOG["treatment_plan.plan.consent_required"]
    assert refused.json()["code"] == definition.code
    assert refused.json()["category"] == definition.category.value
    assert refused.json()["reference"] == refused.headers["x-request-id"]
    # And the plan is where it was.
    plan = (await client.get(f"{PLANS}/{plan_id}", headers=auth_headers)).json()["data"]
    assert plan["status"] == "draft"

    # Written for the plan but not signed yet: still waiting.
    consent = await _consent(client, auth_headers, setup, plan_id)
    assert (await _confirm(client, auth_headers, plan_id)).status_code == 409

    await _sign(client, auth_headers, consent)
    confirmed = await _confirm(client, auth_headers, plan_id)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] != "draft"


@pytest.mark.asyncio
async def test_only_a_standing_informed_consent_for_this_plan_counts(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    other_plan, _ = await _create_plan_with_items(client, auth_headers, setup, [26])

    # Signed, for another plan.
    await _sign(client, auth_headers, await _consent(client, auth_headers, setup, other_plan))
    # Signed, for no plan in particular.
    await _sign(client, auth_headers, await _consent(client, auth_headers, setup, None))
    # Signed for this plan, but it is the consent to the use of data.
    await _sign(
        client, auth_headers, await _consent(client, auth_headers, setup, plan_id, "data_use")
    )
    assert (await _confirm(client, auth_headers, plan_id)).status_code == 409

    # Signed for this plan, then revoked: it no longer consents.
    revoked = await _consent(client, auth_headers, setup, plan_id)
    await _sign(client, auth_headers, revoked)
    taken_back = await client.post(
        f"{CONSENTS}/{revoked['id']}/revoke",
        headers=auth_headers,
        json={"note": "Cambió de opinión"},
    )
    assert taken_back.status_code == 200, taken_back.text
    assert (await _confirm(client, auth_headers, plan_id)).status_code == 409


@pytest.mark.asyncio
async def test_the_clinic_can_switch_the_rule_off(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    assert (await client.get(SETTINGS, headers=auth_headers)).json()["data"] == {
        "require_informed_for_plan": True
    }

    off = await client.put(
        SETTINGS, headers=auth_headers, json={"require_informed_for_plan": False}
    )
    assert off.json()["data"] == {"require_informed_for_plan": False}
    assert (await _confirm(client, auth_headers, plan_id)).status_code == 200


@pytest.mark.asyncio
async def test_with_no_consents_kept_nobody_asks(
    client: AsyncClient, auth_headers: dict, setup: dict, monkeypatch
) -> None:
    """The Clinical record App off: Treatments runs without it (ADR 0037)."""
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    real = plan_service.provider
    monkeypatch.setattr(
        plan_service,
        "provider",
        lambda contract: None if contract.__name__ == "PlanConsents" else real(contract),
    )
    assert (await _confirm(client, auth_headers, plan_id)).status_code == 200


@pytest.mark.asyncio
async def test_a_treatment_is_still_performed_without_the_letter_and_the_plan_says_so(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """A plan confirmed before the clinic asked, or whose letter was
    revoked, keeps going: the screen warns, the server does not stop."""
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])

    async def plan() -> dict:
        return (await client.get(f"{PLANS}/{plan_id}", headers=auth_headers)).json()["data"]

    assert (await plan())["informed_consent_missing"] is True

    consent = await _consent(client, auth_headers, setup, plan_id)
    await _sign(client, auth_headers, consent)
    assert (await plan())["informed_consent_missing"] is False
    assert (await _confirm(client, auth_headers, plan_id)).status_code == 200

    # The patient takes the consent back once treatment is under way.
    await client.post(f"{CONSENTS}/{consent['id']}/revoke", headers=auth_headers, json={})
    current = await plan()
    assert current["informed_consent_missing"] is True

    done = await client.patch(
        f"{PLANS}/{plan_id}/items/{current['items'][0]['id']}/complete",
        headers=auth_headers,
        json={},
    )
    assert done.status_code == 200, done.text
    after = await plan()
    assert after["items"][0]["status"] == "completed"
    # Performed, and still flagged: nothing hid that the letter is missing.
    assert after["informed_consent_missing"] is True


@pytest.mark.asyncio
async def test_a_clinic_that_does_not_ask_is_not_told_anything_is_missing(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    await client.put(SETTINGS, headers=auth_headers, json={"require_informed_for_plan": False})
    plan = (await client.get(f"{PLANS}/{plan_id}", headers=auth_headers)).json()["data"]
    assert plan["informed_consent_missing"] is False


@pytest.mark.asyncio
async def test_completing_a_visit_is_told_which_plans_lack_the_consent(
    client: AsyncClient, auth_headers: dict, setup: dict, db_session: AsyncSession
) -> None:
    """The agenda asks before a visit is completed, and only for work still
    to do on a plan whose consent the clinic requires and does not have."""
    from datetime import UTC, datetime, timedelta

    from app.modules.agenda.models import Appointment, AppointmentTreatment

    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16])
    start = datetime.now(UTC) - timedelta(hours=1)
    appointment = Appointment(
        id=uuid4(),
        clinic_id=setup["clinic_id"],
        patient_id=setup["patient_id"],
        professional_id=setup["dentist_id"],
        start_time=start,
        end_time=start + timedelta(minutes=30),
        status="in_treatment",
    )
    db_session.add(appointment)
    await db_session.flush()
    db_session.add(
        AppointmentTreatment(
            id=uuid4(), appointment_id=appointment.id, planned_treatment_item_id=item_ids[0]
        )
    )
    await db_session.commit()
    check = f"/api/v1/agenda/appointments/{appointment.id}/completion-check"

    async def lacking() -> list[str]:
        answer = await client.get(check, headers=auth_headers)
        assert answer.status_code == 200, answer.text
        return [plan["plan_id"] for plan in answer.json()["data"]["plans_lacking_consent"]]

    assert await lacking() == [plan_id]

    # A clinic that does not ask is not told anything.
    await client.put(SETTINGS, headers=auth_headers, json={"require_informed_for_plan": False})
    assert await lacking() == []
    await client.put(SETTINGS, headers=auth_headers, json={"require_informed_for_plan": True})

    await _sign(client, auth_headers, await _consent(client, auth_headers, setup, plan_id))
    assert await lacking() == []
