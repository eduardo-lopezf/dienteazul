"""The operator's window into a deployment (ADR 0049 rule 4).

``/api/v1/ops`` is read by the control plane, never by a clinic's users.
What is pinned here:

- it does not exist until ``CONTROL_PLANE_SECRET`` is set, and never
  under ``self`` custody;
- only a token signed with that secret, for that audience, opens it — a
  staff session does not;
- what it returns is sizes, counts and identifiers: a patient's name
  never crosses it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.models import Clinic, User
from app.core.auth.privacy_agreement import PRIVACY_AGREEMENT_VERSION
from app.core.ops.router import OPS_AUDIENCE
from app.modules.catalog.models import Specialty

SECRET = "control-plane-secret-for-tests-0123456789"


def _token(secret: str = SECRET, audience: str = OPS_AUDIENCE, minutes: int = 1) -> dict[str, str]:
    payload = {"aud": audience, "exp": datetime.now(UTC) + timedelta(minutes=minutes)}
    return {"Authorization": f"Bearer {jwt.encode(payload, secret, algorithm='HS256')}"}


@pytest.fixture
def ops_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)


async def test_absent_without_a_secret(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Set explicitly: a developer's own backend may well have one.
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", "")
    response = await client.get("/api/v1/ops/usage", headers=_token())
    assert response.status_code == 404


async def test_absent_under_self_custody(
    client: AsyncClient, ops_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TENANT_CUSTODY_MODE", "self")
    response = await client.get("/api/v1/ops/usage", headers=_token())
    assert response.status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {},
        _token(secret="another-secret-entirely-0123456789abcdef"),
        _token(audience="something-else"),
        _token(minutes=-5),
    ],
    ids=["no token", "wrong secret", "wrong audience", "expired"],
)
async def test_refuses_anything_but_its_own_token(
    client: AsyncClient, ops_enabled: None, headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/ops/usage", headers=headers)
    assert response.status_code == 401


async def test_refuses_a_staff_session(
    client: AsyncClient, ops_enabled: None, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/ops/usage", headers=auth_headers)
    assert response.status_code == 401


async def test_usage_lists_each_clinic_with_its_share(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/patients",
        json={"first_name": "Aurelia", "last_name": "Zamarripa"},
        headers=auth_headers,
    )
    assert created.status_code == 201

    response = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    assert response.status_code == 200
    usage = response.json()["data"]

    [clinic] = usage["clinics"]
    assert clinic["id"] == str(test_clinic.id)
    assert clinic["users"] == 1
    assert clinic["account_tier"] == test_clinic.account_tier
    assert clinic["database_rows"] >= 1
    assert 0 < clinic["database_bytes"] <= usage["database_bytes"]
    assert usage["shared_database_bytes"] + clinic["database_bytes"] == usage["database_bytes"]
    assert clinic["storage_bytes"] == 0


async def test_log_says_where_and_when_never_what(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await client.post(
        "/api/v1/patients",
        json={"first_name": "Aurelia", "last_name": "Zamarripa"},
        headers=auth_headers,
    )
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "test@example.com", "password": "TestPass1234"},
    )
    assert login.status_code == 200

    response = await client.get(f"/api/v1/ops/clinics/{test_clinic.id}/log", headers=_token())
    assert response.status_code == 200
    entries = response.json()["data"]

    assert any(e["kind"] == "record_created" and e["area"] == "patients" for e in entries)
    [access] = [e for e in entries if e["kind"] == "login"]
    assert access["role"] == "admin"
    assert access["user_id"]
    assert [e["at"] for e in entries] == sorted((e["at"] for e in entries), reverse=True)
    assert "Zamarripa" not in response.text
    assert "test@example.com" not in response.text


async def test_log_of_an_unknown_clinic(client: AsyncClient, ops_enabled: None) -> None:
    response = await client.get(
        "/api/v1/ops/clinics/00000000-0000-0000-0000-000000000000/log", headers=_token()
    )
    assert response.status_code == 404


HOLDER = {
    "timezone": "America/Tijuana",
    "tax_id": "ZAAU800101AB1",
    "holder_first_name": "Aurelia",
    "holder_last_name": "Zamarripa",
    "holder_email": "aurelia@example.com",
    "holder_professional_id": "1234567",
    "holder_password": "Temporal1234",
    "apps": ["workspace", "agenda", "patients", "treatments"],
}
CLINIC = HOLDER | {
    "account_tier": "clinic",
    "tax_id": "CDS200101XY9",
    "clinic_name": "Clínica Dental del Sur",
    "apps": [*HOLDER["apps"], "professionals"],
}


async def test_creating_a_clinic_needs_the_control_planes_token(
    client: AsyncClient, ops_enabled: None, auth_headers: dict[str, str]
) -> None:
    payload = HOLDER | {"account_tier": "basic"}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=auth_headers)
    assert response.status_code == 401


async def test_an_individual_tier_makes_the_holders_own_practice(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    response = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "basic"}, headers=_token()
    )
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    assert created["name"] == "Aurelia Zamarripa"

    clinic = await db_session.get(Clinic, UUID(created["clinic_id"]))
    assert (clinic.account_tier, clinic.timezone, clinic.tax_id) == (
        "basic",
        "America/Tijuana",
        "ZAAU800101AB1",
    )
    holder = await db_session.get(User, UUID(created["holder_user_id"]))
    assert holder.professional_id == "1234567"
    assert holder.password_hash != HOLDER["holder_password"]

    # The holder can sign in, and is the administrator of that clinic.
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": HOLDER["holder_email"], "password": HOLDER["holder_password"]},
    )
    assert login.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    [membership] = me.json()["data"]["clinics"]
    assert (membership["id"], membership["role"]) == (created["clinic_id"], "admin")


async def test_the_clinic_tier_takes_the_clinics_own_details(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    payload = CLINIC | {
        "clinic_legal_name": "Clínica Dental del Sur, S.C.",
        "clinic_phone": "6641234567",
    }
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 201, response.text
    clinic = await db_session.get(Clinic, UUID(response.json()["data"]["clinic_id"]))
    assert (clinic.name, clinic.legal_name, clinic.phone) == (
        "Clínica Dental del Sur",
        "Clínica Dental del Sur, S.C.",
        "6641234567",
    )


async def test_the_clinic_tier_without_a_clinic_name_is_refused(
    client: AsyncClient, ops_enabled: None
) -> None:
    response = await client.post(
        "/api/v1/ops/clinics", json=CLINIC | {"clinic_name": None}, headers=_token()
    )
    assert response.status_code == 422


async def test_an_email_that_already_belongs_to_a_clinic_is_refused(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic
) -> None:
    # test@example.com administers "Test Clinic": one e-mail, one account, one clinic.
    payload = CLINIC | {"holder_email": "test@example.com"}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 409
    assert "Test Clinic" in response.text

    usage = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    assert [c["name"] for c in usage.json()["data"]["clinics"]] == ["Test Clinic"]


async def test_an_account_removed_from_its_clinic_can_hold_a_new_one(
    client: AsyncClient, ops_enabled: None, auth_headers: dict[str, str]
) -> None:
    # ``auth_headers`` makes test@example.com with no clinic at all.
    payload = CLINIC | {"holder_email": "test@example.com", "holder_first_name": "Otro nombre"}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 201, response.text
    assert response.json()["data"]["holder_existed"] is True

    # The account is left as it was: its own password, no forced change,
    # its own name — and it now works in the new clinic.
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["data"]
    assert (me["user"]["first_name"], me["user"]["must_change_password"]) == ("Test", False)
    assert [(c["name"], c["role"]) for c in me["clinics"]] == [("Clínica Dental del Sur", "admin")]


async def test_a_new_holder_is_reported_as_new(client: AsyncClient, ops_enabled: None) -> None:
    response = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "medium"}, headers=_token()
    )
    assert response.json()["data"]["holder_existed"] is False


async def test_a_deactivated_account_cannot_be_made_holder(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, db_session: AsyncSession
) -> None:
    user = await db_session.scalar(select(User).where(User.email == "test@example.com"))
    user.is_active = False
    await db_session.commit()

    payload = HOLDER | {"account_tier": "basic", "holder_email": "test@example.com"}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 409


async def test_a_timezone_that_does_not_exist_is_refused(
    client: AsyncClient, ops_enabled: None
) -> None:
    payload = HOLDER | {"account_tier": "basic", "timezone": "America/Atlantida"}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 422


async def test_apps_say_for_whom_each_is_mandatory(client: AsyncClient, ops_enabled: None) -> None:
    response = await client.get("/api/v1/ops/apps", headers=_token())
    assert response.status_code == 200
    apps = {app["name"]: app for app in response.json()["data"]}

    everyone = {"basic", "medium", "advanced", "clinic", "clinic_pro", "hospital"}
    for name in ("workspace", "agenda", "patients", "treatments"):
        assert set(apps[name]["mandatory_for"]) == everyone, name
    # A clinic has professionals; one professional's practice need not.
    assert set(apps["professionals"]["mandatory_for"]) == {"clinic", "clinic_pro", "hospital"}
    assert apps["recalls"]["mandatory_for"] == []
    # These only integrate other Apps (ADR 0037); the Clinical record
    # still requires Professionals.
    for name in ("budgets_payments", "cash", "communications", "reports"):
        assert apps[name]["requires"] == [], name
    assert set(apps["clinical_record"]["requires"]) == {"patients", "professionals"} | set(
        apps["professionals"]["requires"]
    )


async def test_the_chosen_apps_are_kept_in_catalog_order(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    payload = HOLDER | {
        "account_tier": "basic",
        "apps": ["recalls", "treatments", "patients", "agenda", "workspace", "agenda"],
    }
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 201, response.text

    clinic = await db_session.get(Clinic, UUID(response.json()["data"]["clinic_id"]))
    assert clinic.apps == ["workspace", "agenda", "patients", "recalls", "treatments"]

    usage = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    [listed] = usage.json()["data"]["clinics"]
    assert listed["apps"] == clinic.apps


@pytest.mark.parametrize(
    "tier,apps",
    [
        ("basic", ["workspace", "agenda", "patients"]),
        ("clinic", ["workspace", "agenda", "patients", "treatments"]),
        # The Clinical record requires Professionals, left out here.
        ("basic", [*HOLDER["apps"], "clinical_record"]),
        ("basic", [*HOLDER["apps"], "ai"]),
        ("basic", [*HOLDER["apps"], "no_such_app"]),
    ],
    ids=[
        "a mandatory App left out",
        "a clinic without Professionals",
        "an App without the ones it requires",
        "an App the deployment has switched off",
        "an App that does not exist",
    ],
)
async def test_a_set_of_apps_a_clinic_cannot_have_is_refused(
    client: AsyncClient, ops_enabled: None, tier: str, apps: list[str]
) -> None:
    payload = CLINIC | {"account_tier": tier, "apps": apps}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 422, response.text


#: What the welcome sends when its privacy agreement is accepted.
ACCEPTED = {"version": PRIVACY_AGREEMENT_VERSION}


async def _login(client: AsyncClient, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", data={"username": HOLDER["holder_email"], "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_the_holder_must_replace_the_password_before_anything_else(
    client: AsyncClient, ops_enabled: None
) -> None:
    created = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "basic"}, headers=_token()
    )
    assert created.status_code == 201, created.text
    first = HOLDER["holder_password"]
    session = await _login(client, first)

    # Signed in, told so, and held at the door of everything else.
    me = await client.get("/api/v1/auth/me", headers=session)
    assert me.json()["data"]["user"]["must_change_password"] is True
    assert (await client.get("/api/v1/patients", headers=session)).status_code == 403

    async def change(current: str, new: str) -> int:
        body = {"current_password": current, "new_password": new}
        return (await client.post("/api/v1/auth/password", json=body, headers=session)).status_code

    assert await change("not-the-password1", "Propia5678") == 400
    assert await change(first, first) == 422  # "changing" it to itself
    assert await change(first, "sinnumeros") == 422
    assert (await client.get("/api/v1/patients", headers=session)).status_code == 403

    assert await change(first, "Propia5678") == 204
    # With its own password the account is let in — to the welcome first.
    held = await client.get("/api/v1/patients", headers=session)
    assert held.json()["message"] == "Onboarding required"
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=session)
    assert (await client.get("/api/v1/patients", headers=session)).status_code == 200
    me = await client.get("/api/v1/auth/me", headers=session)
    assert me.json()["data"]["user"]["must_change_password"] is False
    await _login(client, "Propia5678")


async def test_an_account_with_its_own_password_is_not_held(
    client: AsyncClient, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me.json()["data"]["user"]["must_change_password"] is False
    assert (await client.get("/api/v1/patients", headers=auth_headers)).status_code == 200


async def _active_specialties(db: AsyncSession, clinic_id: str) -> set[str]:
    rows = await db.execute(
        select(Specialty.key).where(
            Specialty.clinic_id == UUID(clinic_id), Specialty.is_active.is_(True)
        )
    )
    return set(rows.scalars())


async def test_specialties_on_offer_and_the_one_every_clinic_has(
    client: AsyncClient, ops_enabled: None
) -> None:
    response = await client.get("/api/v1/ops/specialties", headers=_token())
    assert response.status_code == 200
    specialties = {s["key"]: s for s in response.json()["data"]}
    assert len(specialties) == 17
    assert [key for key, s in specialties.items() if s["required"]] == ["general"]
    assert specialties["general"]["names"]["es"] == "Odontología General"


async def test_a_clinic_starts_with_exactly_the_specialties_chosen(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    payload = HOLDER | {"account_tier": "basic", "specialties": ["radiologia", "general"]}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 201, response.text

    clinic_id = response.json()["data"]["clinic_id"]
    # ``radiologia`` is not a baseline discipline; ``endodoncia`` is, and
    # was not chosen.
    assert await _active_specialties(db_session, clinic_id) == {"general", "radiologia"}


async def test_without_a_choice_a_clinic_gets_the_baseline_specialties(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    response = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "basic"}, headers=_token()
    )
    active = await _active_specialties(db_session, response.json()["data"]["clinic_id"])
    assert {"general", "endodoncia", "ortodoncia"} <= active and "radiologia" not in active


@pytest.mark.parametrize(
    "specialties", [["endodoncia"], ["general", "astrologia"]], ids=["without general", "unknown"]
)
async def test_a_set_of_specialties_a_clinic_cannot_have_is_refused(
    client: AsyncClient, ops_enabled: None, specialties: list[str]
) -> None:
    payload = HOLDER | {"account_tier": "basic", "specialties": specialties}
    response = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert response.status_code == 422, response.text


async def _status(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    [clinic] = response.json()["data"]["clinics"]
    return clinic


async def test_a_clinic_nobody_signed_in_to_has_no_recent_activity(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic
) -> None:
    clinic = await _status(client)
    assert (clinic["status"], clinic["last_access_at"]) == ("inactive", None)


async def test_a_clinic_is_active_while_someone_is_signed_in_and_offline_after(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "test@example.com", "password": "TestPass1234"},
    )
    assert (await _status(client))["status"] == "active"

    await client.post("/api/v1/auth/logout", json={"refresh_token": login.json()["refresh_token"]})
    clinic = await _status(client)
    assert clinic["status"] == "offline" and clinic["last_access_at"]


async def test_a_deactivated_clinic_is_closed_to_its_members_until_reactivated(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/patients", headers=auth_headers)).status_code == 200

    response = await client.post(
        f"/api/v1/ops/clinics/{test_clinic.id}/deactivate", headers=_token()
    )
    assert response.status_code == 200
    state = response.json()["data"]
    assert state["status"] == "deactivated"
    # Ten days from the deactivation, to the second.
    waited = datetime.fromisoformat(state["deletable_from"]) - datetime.fromisoformat(
        state["deactivated_at"]
    )
    assert waited == timedelta(days=10)

    assert (await client.get("/api/v1/patients", headers=auth_headers)).status_code == 403
    assert (await _status(client))["status"] == "deactivated"

    # Deactivating again does not restart the wait.
    again = await client.post(f"/api/v1/ops/clinics/{test_clinic.id}/deactivate", headers=_token())
    assert again.json()["data"]["deactivated_at"] == state["deactivated_at"]

    response = await client.post(
        f"/api/v1/ops/clinics/{test_clinic.id}/reactivate", headers=_token()
    )
    assert response.json()["data"]["deactivated_at"] is None
    assert (await client.get("/api/v1/patients", headers=auth_headers)).status_code == 200


async def test_deactivating_needs_the_control_planes_token(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/ops/clinics/{test_clinic.id}/deactivate", headers=auth_headers
    )
    assert response.status_code == 401


async def _only_user(client: AsyncClient, clinic: Clinic) -> dict:
    response = await client.get(f"/api/v1/ops/clinics/{clinic.id}/users", headers=_token())
    assert response.status_code == 200, response.text
    [user] = response.json()["data"]
    return user


async def test_the_users_of_a_clinic_with_their_role(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic
) -> None:
    user = await _only_user(client, test_clinic)
    assert (user["email"], user["first_name"], user["role"]) == (
        "test@example.com",
        "Test",
        "admin",
    )
    assert "password_hash" not in user


async def test_a_users_profile_can_be_corrected_but_not_given_a_taken_email(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, db_session: AsyncSession
) -> None:
    user = await _only_user(client, test_clinic)
    db_session.add(User(email="otra@example.com", password_hash="x", first_name="O", last_name="P"))
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/ops/users/{user['id']}",
        json={"first_name": "Aurelia", "professional_id": "7654321"},
        headers=_token(),
    )
    assert response.status_code == 200, response.text
    updated = await _only_user(client, test_clinic)
    assert (updated["first_name"], updated["last_name"], updated["professional_id"]) == (
        "Aurelia",
        "User",
        "7654321",
    )

    taken = await client.patch(
        f"/api/v1/ops/users/{user['id']}", json={"email": "otra@example.com"}, headers=_token()
    )
    assert taken.status_code == 409
    # The password is not something this route knows about.
    await _login_as(client, "test@example.com", "TestPass1234")


async def _login_as(client: AsyncClient, email: str, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text


async def test_a_user_can_be_deleted_in_development_and_not_in_production(
    client: AsyncClient,
    ops_enabled: None,
    test_clinic: Clinic,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _only_user(client, test_clinic)

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    refused = await client.delete(f"/api/v1/ops/users/{user['id']}", headers=_token())
    assert refused.status_code == 403
    assert await db_session.get(User, UUID(user["id"])) is not None

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    deleted = await client.delete(f"/api/v1/ops/users/{user['id']}", headers=_token())
    assert deleted.status_code == 204
    users = await client.get(f"/api/v1/ops/clinics/{test_clinic.id}/users", headers=_token())
    assert users.json()["data"] == []
    # And the e-mail is free again for a new account.
    payload = CLINIC | {"holder_email": "test@example.com"}
    again = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert (again.status_code, again.json()["data"]["holder_existed"]) == (201, False)


async def _create(client: AsyncClient, **overrides: object) -> str:
    response = await client.post("/api/v1/ops/clinics", json=CLINIC | overrides, headers=_token())
    assert response.status_code == 201, response.text
    return response.json()["data"]["clinic_id"]


async def test_a_clinic_reads_back_everything_it_was_created_with(
    client: AsyncClient, ops_enabled: None
) -> None:
    clinic_id = await _create(
        client, clinic_phone="6641234567", specialties=["general", "radiologia"]
    )

    response = await client.get(f"/api/v1/ops/clinics/{clinic_id}", headers=_token())
    assert response.status_code == 200, response.text
    clinic = response.json()["data"]
    assert (clinic["account_tier"], clinic["timezone"], clinic["tax_id"], clinic["phone"]) == (
        "clinic",
        "America/Tijuana",
        "CDS200101XY9",
        "6641234567",
    )
    assert clinic["apps"] == [*HOLDER["apps"], "professionals"]
    assert clinic["specialties"] == ["general", "radiologia"]
    assert (clinic["holder"]["email"], clinic["holder"]["professional_id"]) == (
        "aurelia@example.com",
        "1234567",
    )


async def test_a_clinic_can_be_changed_under_the_rules_of_creation(
    client: AsyncClient, ops_enabled: None
) -> None:
    clinic_id = await _create(client)
    change = {
        "account_tier": "clinic",
        "timezone": "America/Cancun",
        "tax_id": "NUE200101AA1",
        "clinic_name": "Clínica Renombrada",
        "clinic_legal_name": "Renombrada, S.C.",
        "apps": [*CLINIC["apps"], "recalls"],
        "specialties": ["general", "ortodoncia", "radiologia"],
    }

    response = await client.patch(f"/api/v1/ops/clinics/{clinic_id}", json=change, headers=_token())
    assert response.status_code == 200, response.text

    clinic = (await client.get(f"/api/v1/ops/clinics/{clinic_id}", headers=_token())).json()["data"]
    assert (clinic["name"], clinic["legal_name"], clinic["timezone"], clinic["tax_id"]) == (
        "Clínica Renombrada",
        "Renombrada, S.C.",
        "America/Cancun",
        "NUE200101AA1",
    )
    assert "recalls" in clinic["apps"]
    assert clinic["specialties"] == ["ortodoncia", "general", "radiologia"] or set(
        clinic["specialties"]
    ) == {"general", "ortodoncia", "radiologia"}

    # The rules of creation still hold: a clinic keeps Professionals.
    refused = await client.patch(
        f"/api/v1/ops/clinics/{clinic_id}",
        json=change | {"apps": HOLDER["apps"]},
        headers=_token(),
    )
    assert refused.status_code == 422


async def test_a_clinic_moved_to_an_individual_tier_takes_its_holders_name(
    client: AsyncClient, ops_enabled: None
) -> None:
    clinic_id = await _create(client)
    change = {
        "account_tier": "advanced",
        "timezone": "America/Tijuana",
        "tax_id": "ZAAU800101AB1",
        "apps": HOLDER["apps"],
    }
    response = await client.patch(f"/api/v1/ops/clinics/{clinic_id}", json=change, headers=_token())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == "Aurelia Zamarripa"


async def test_a_clinic_is_deleted_whole_in_development_and_not_at_all_in_production(
    client: AsyncClient,
    ops_enabled: None,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A clinic that stays, with a patient of its own…
    kept = await client.post(
        "/api/v1/patients", json={"first_name": "Se", "last_name": "Queda"}, headers=auth_headers
    )
    assert kept.status_code == 201
    # …and one to delete: seeded catalogue, holder, and a patient too.
    doomed = await _create(client)
    holder = await _login(client, HOLDER["holder_password"])
    changed = await client.post(
        "/api/v1/auth/password",
        json={"current_password": HOLDER["holder_password"], "new_password": "Propia5678"},
        headers=holder,
    )
    assert changed.status_code == 204
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder)
    gone = await client.post(
        "/api/v1/patients", json={"first_name": "Se", "last_name": "Va"}, headers=holder
    )
    assert gone.status_code == 201, gone.text

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    refused = await client.delete(f"/api/v1/ops/clinics/{doomed}", headers=_token())
    assert refused.status_code == 403

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    deleted = await client.delete(f"/api/v1/ops/clinics/{doomed}", headers=_token())
    assert deleted.status_code == 204, deleted.text

    usage = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    assert [c["name"] for c in usage.json()["data"]["clinics"]] == ["Test Clinic"]
    # Nothing of it is left, in any table that names a clinic…
    leftovers = await db_session.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND column_name = 'clinic_id'"
        )
    )
    for (table,) in leftovers:
        count = await db_session.scalar(
            text(f'SELECT count(*) FROM "{table}" WHERE clinic_id = :id'), {"id": UUID(doomed)}
        )
        assert count == 0, table
    # …its holder went with it, and the other clinic lost nothing.
    assert await db_session.scalar(select(User).where(User.email == HOLDER["holder_email"])) is None
    patients = await client.get("/api/v1/patients", headers=auth_headers)
    assert [p["last_name"] for p in patients.json()["data"]] == ["Queda"]


async def test_a_clinic_only_has_the_apps_chosen_for_it(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    """Created with the four mandatory Apps: Recalls is not one of them."""
    created = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "basic"}, headers=_token()
    )
    assert created.status_code == 201, created.text
    holder = await _login(client, HOLDER["holder_password"])
    await client.post(
        "/api/v1/auth/password",
        json={"current_password": HOLDER["holder_password"], "new_password": "Propia5678"},
        headers=holder,
    )
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder)

    # Its menu has no entry of an App it was not given…
    active = await client.get("/api/v1/modules/-/active", headers=holder)
    # (The list is empty here either way — the suite installs no module in
    # ``core_module`` — so this only pins that nothing extra slips in.)
    names = {module["name"] for module in active.json()["data"]}
    assert not names & {"recalls", "budget", "professionals", "reports"}
    # …those Apps' routes are not there for it, the ones it has are…
    assert (await client.get("/api/v1/recalls/stats/dashboard", headers=holder)).status_code == 404
    assert (await client.get("/api/v1/patients", headers=holder)).status_code == 200
    # …and it holds none of their permissions, administrator or not.
    me = (await client.get("/api/v1/auth/me", headers=holder)).json()["data"]
    assert any(p.startswith("patients.") for p in me["permissions"])
    assert not any(p.startswith(("recalls.", "budget.", "reports.")) for p in me["permissions"])
    apps = (await client.get("/api/v1/apps", headers=holder)).json()["data"]
    enabled = {app["name"] for app in apps if app["enabled"]}
    assert enabled == {"workspace", "agenda", "patients", "treatments"}

    # A clinic nobody chose for keeps everything the deployment runs.
    assert (
        await client.get("/api/v1/recalls/stats/dashboard", headers=auth_headers)
    ).status_code == 200


async def test_a_clinic_switches_on_the_apps_it_was_offered_and_no_others(
    client: AsyncClient, ops_enabled: None
) -> None:
    """Given the four mandatory Apps and offered Professionals and the
    Clinical record (which needs Professionals); Recalls was not offered."""
    payload = HOLDER | {
        "account_tier": "basic",
        "available_apps": ["clinical_record", "professionals", "agenda"],
    }
    created = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    assert created.status_code == 201, created.text
    clinic_id = created.json()["data"]["clinic_id"]
    holder = await _login(client, HOLDER["holder_password"])
    await client.post(
        "/api/v1/auth/password",
        json={"current_password": HOLDER["holder_password"], "new_password": "Propia5678"},
        headers=holder,
    )
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder)

    async def apps() -> dict[str, dict]:
        response = await client.get("/api/v1/apps", headers=holder)
        return {app["name"]: app for app in response.json()["data"]}

    listed = await apps()
    # An App it already has is not "available"; the two offered ones are.
    assert {n for n, a in listed.items() if a["available"]} == {"clinical_record", "professionals"}
    assert not listed["recalls"]["enabled"] and not listed["recalls"]["available"]
    assert (await client.get("/api/v1/consents/templates", headers=holder)).status_code == 404

    # Not offered: refused. Unknown: not found.
    refused = await client.post("/api/v1/apps/recalls/enable", headers=holder)
    assert refused.status_code == 403
    assert (await client.post("/api/v1/apps/nope/enable", headers=holder)).status_code == 404

    # Offered: on at once, and what it requires with it.
    enabled = await client.post("/api/v1/apps/clinical_record/enable", headers=holder)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["also_enabled"] == ["professionals"]
    listed = await apps()
    assert listed["clinical_record"]["enabled"] and listed["professionals"]["enabled"]
    assert not any(app["available"] for app in listed.values())
    assert (await client.get("/api/v1/consents/templates", headers=holder)).status_code == 200

    detail = await client.get(f"/api/v1/ops/clinics/{clinic_id}", headers=_token())
    assert detail.json()["data"]["apps"] == [
        "workspace",
        "agenda",
        "patients",
        "treatments",
        "professionals",
        "clinical_record",
    ]
    assert detail.json()["data"]["available_apps"] == []


async def test_an_app_that_needs_one_not_offered_cannot_be_switched_on(
    client: AsyncClient, ops_enabled: None
) -> None:
    payload = HOLDER | {"account_tier": "basic", "available_apps": ["clinical_record"]}
    await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    holder = await _login(client, HOLDER["holder_password"])
    await client.post(
        "/api/v1/auth/password",
        json={"current_password": HOLDER["holder_password"], "new_password": "Propia5678"},
        headers=holder,
    )
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder)
    response = await client.post("/api/v1/apps/clinical_record/enable", headers=holder)
    assert response.status_code == 409


async def test_the_apps_are_read_from_the_file_on_every_request(
    client: AsyncClient, ops_enabled: None, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An edit to ``apps.json`` shows at once in the operator's list, as
    waiting for a restart; what is running does not change."""
    from app.core.plugins import apps as catalog

    # What is running was read at boot, before the edit: make sure it is
    # in the cache already, or this test would be what "boot" read.
    catalog.load_app_catalog()
    edited = json.loads(catalog.APPS_FILE.read_text(encoding="utf-8"))
    for entry in edited["apps"]:
        if entry["name"] == "recalls":
            entry["status"] = "disabled"
        if entry["name"] == "reports":
            entry["tier"] = "core"
    copy = tmp_path / "apps.json"
    copy.write_text(json.dumps(edited), encoding="utf-8")
    monkeypatch.setattr(catalog, "APPS_FILE", copy)

    response = await client.get("/api/v1/ops/apps", headers=_token())
    apps = {app["name"]: app for app in response.json()["data"]}
    # Still running, and the file now says otherwise.
    assert (apps["recalls"]["enabled"], apps["recalls"]["pending_enabled"]) == (True, False)
    # Its tier is the file's, read now.
    assert apps["reports"]["tier"] == "core" and "basic" in apps["reports"]["mandatory_for"]
    assert apps["agenda"]["pending_enabled"] is None


async def test_a_clinics_apps_are_changed_on_their_own_and_at_once(
    client: AsyncClient, ops_enabled: None
) -> None:
    clinic_id = await _create(client)
    holder = await _login(client, HOLDER["holder_password"])
    await client.post(
        "/api/v1/auth/password",
        json={"current_password": HOLDER["holder_password"], "new_password": "Propia5678"},
        headers=holder,
    )
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder)
    assert (await client.get("/api/v1/recalls/stats/dashboard", headers=holder)).status_code == 404

    # Give it Recalls and offer it Budgets: nothing else about it is sent.
    change = {"apps": [*CLINIC["apps"], "recalls"], "available_apps": ["budgets_payments"]}
    response = await client.put(
        f"/api/v1/ops/clinics/{clinic_id}/apps", json=change, headers=_token()
    )
    assert response.status_code == 200, response.text
    clinic = response.json()["data"]
    assert "recalls" in clinic["apps"] and clinic["available_apps"] == ["budgets_payments"]
    assert (clinic["name"], clinic["timezone"]) == ("Clínica Dental del Sur", "America/Tijuana")
    # The same session, no restart, no new sign-in.
    assert (await client.get("/api/v1/recalls/stats/dashboard", headers=holder)).status_code == 200

    # Take it away again.
    response = await client.put(
        f"/api/v1/ops/clinics/{clinic_id}/apps", json={"apps": CLINIC["apps"]}, headers=_token()
    )
    assert response.json()["data"]["available_apps"] == []
    assert (await client.get("/api/v1/recalls/stats/dashboard", headers=holder)).status_code == 404

    # What its tier makes mandatory cannot be taken away.
    refused = await client.put(
        f"/api/v1/ops/clinics/{clinic_id}/apps", json={"apps": HOLDER["apps"]}, headers=_token()
    )
    assert refused.status_code == 422


async def test_a_clinic_moves_to_another_tier_and_keeps_its_apps(
    client: AsyncClient, ops_enabled: None
) -> None:
    payload = HOLDER | {"account_tier": "basic", "apps": [*HOLDER["apps"], "recalls"]}
    created = await client.post("/api/v1/ops/clinics", json=payload, headers=_token())
    clinic_id = created.json()["data"]["clinic_id"]
    url = f"/api/v1/ops/clinics/{clinic_id}/tier"

    # To a clinic: what that tier makes mandatory comes with it.
    response = await client.put(url, json={"account_tier": "clinic"}, headers=_token())
    assert response.status_code == 200, response.text
    clinic = response.json()["data"]
    assert clinic["account_tier"] == "clinic"
    assert {"recalls", "professionals"} <= set(clinic["apps"])
    assert clinic["name"] == "Aurelia Zamarripa"

    # And back: nothing it has is taken away.
    response = await client.put(url, json={"account_tier": "medium"}, headers=_token())
    clinic = response.json()["data"]
    assert (clinic["account_tier"], clinic["name"]) == ("medium", "Aurelia Zamarripa")
    assert "recalls" in clinic["apps"]

    refused = await client.put(url, json={"account_tier": "nonsense"}, headers=_token())
    assert refused.status_code == 422


# --- What a tier is allowed -------------------------------------------------


async def _set_limits(client: AsyncClient, tier: str, **limits: int | None) -> None:
    response = await client.put("/api/v1/ops/limits", json={tier: limits}, headers=_token())
    assert response.status_code == 200, response.text


def _new_user(n: int) -> dict[str, str]:
    return {
        "email": f"extra{n}@example.com",
        "password": "TestPass1234",
        "first_name": "Extra",
        "last_name": str(n),
        "role": "receptionist",
    }


async def test_limits_are_replaced_whole(client: AsyncClient, ops_enabled: None) -> None:
    await _set_limits(client, "basic", extra_users=0, storage_mb=20)
    await _set_limits(client, "medium", extra_users=2, storage_mb=None)

    response = await client.get("/api/v1/ops/limits", headers=_token())
    assert response.json()["data"] == {"medium": {"extra_users": 2, "storage_mb": None}}


async def test_a_clinic_adds_no_more_users_than_its_tier_allows(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _set_limits(client, test_clinic.account_tier, extra_users=1)

    first = await client.post("/api/v1/auth/users", json=_new_user(1), headers=auth_headers)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/auth/users", json=_new_user(2), headers=auth_headers)
    assert (second.status_code, second.json()["message"]) == (403, "User limit reached")

    limits = await client.get("/api/v1/auth/clinic/limits", headers=auth_headers)
    assert limits.json()["data"]["users"] == 2
    assert limits.json()["data"]["users_limit"] == 2

    # The limit is the operator's to move, and moving it is enough.
    await _set_limits(client, test_clinic.account_tier, extra_users=None)
    third = await client.post("/api/v1/auth/users", json=_new_user(2), headers=auth_headers)
    assert third.status_code == 201, third.text


async def test_a_clinics_own_limit_goes_over_its_tiers(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    await _set_limits(client, test_clinic.account_tier, extra_users=0, storage_mb=20)
    url = f"/api/v1/ops/clinics/{test_clinic.id}/limits"

    # One more user for this clinic alone; its disk stays the tier's.
    own = await client.put(url, json={"extra_users": 1}, headers=_token())
    assert own.json()["data"]["limits"] == {"extra_users": 1}
    limits = (await client.get("/api/v1/auth/clinic/limits", headers=auth_headers)).json()["data"]
    assert (limits["users_limit"], limits["storage_limit_bytes"]) == (2, 20 * 1024 * 1024)
    first = await client.post("/api/v1/auth/users", json=_new_user(1), headers=auth_headers)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/auth/users", json=_new_user(2), headers=auth_headers)
    assert second.status_code == 403

    # ``null`` is no limit for this clinic; nothing sent inherits again.
    await client.put(url, json={"extra_users": None}, headers=_token())
    third = await client.post("/api/v1/auth/users", json=_new_user(2), headers=auth_headers)
    assert third.status_code == 201, third.text
    back = await client.put(url, json={}, headers=_token())
    assert back.json()["data"]["limits"] == {}
    fourth = await client.post("/api/v1/auth/users", json=_new_user(3), headers=auth_headers)
    assert fourth.status_code == 403


async def test_an_upload_that_does_not_fit_is_refused(
    client: AsyncClient,
    ops_enabled: None,
    test_clinic: Clinic,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    folder = tmp_path / str(test_clinic.id)
    folder.mkdir()
    (folder / "held.bin").write_bytes(b"0" * (1024 * 1024 - 10))
    await _set_limits(client, test_clinic.account_tier, storage_mb=1)

    upload = {
        "files": {"file": ("x.pdf", b"%PDF-1.4 " + b"0" * 100, "application/pdf")},
        "data": {"document_type": "other", "title": "x"},
        "headers": auth_headers,
    }
    url = f"/api/v1/media/patients/{test_clinic.id}/documents"
    refused = await client.post(url, **upload)
    assert (refused.status_code, refused.json()["message"]) == (403, "Storage limit reached")

    limits = await client.get("/api/v1/auth/clinic/limits", headers=auth_headers)
    assert limits.json()["data"]["storage_bytes"] == 1024 * 1024 - 10
    assert limits.json()["data"]["storage_limit_bytes"] == 1024 * 1024

    # With room for it, the request gets past the limit (to a patient
    # that does not exist).
    await _set_limits(client, test_clinic.account_tier, storage_mb=2)
    assert (await client.post(url, **upload)).status_code == 404


# --- The welcome of a new clinic's holder -----------------------------------


async def test_accepting_keeps_the_version_that_was_shown(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    clinic_id, holder = await _new_holder(client)
    url = "/api/v1/auth/clinic/onboarding/accept"

    # No acceptance without saying which text it was.
    assert (await client.post(url, json={}, headers=holder)).status_code == 422
    assert await _pending(client, holder) is True

    # Nor of a text that is not the one in force.
    assert (await client.post(url, json={"version": "1999"}, headers=holder)).status_code == 409

    assert (await client.post(url, json=ACCEPTED, headers=holder)).status_code == 204
    clinic = await db_session.get(Clinic, UUID(clinic_id))
    assert clinic.privacy_accepted_version == PRIVACY_AGREEMENT_VERSION
    usage = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    [told] = [c for c in usage.json()["data"]["clinics"] if c["id"] == clinic_id]
    assert (told["privacy"], told["privacy_version"]) == ("accepted", PRIVACY_AGREEMENT_VERSION)


async def test_a_new_version_of_the_agreement_is_asked_of_its_administrators(
    client: AsyncClient,
    ops_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clinic_id, holder = await _new_holder(client)
    await client.post("/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder)
    assert (await client.get("/api/v1/patients", headers=holder)).status_code == 200

    # The text changes: what the clinic accepted is no longer in force.
    from app.core.auth import privacy_agreement, router
    from app.core.ops import usage

    for module in (privacy_agreement, router, usage):
        monkeypatch.setattr(module, "PRIVACY_AGREEMENT_VERSION", "2099-01-01")

    me = await client.get("/api/v1/auth/me", headers=holder)
    assert me.json()["data"]["clinics"][0]["privacy_renewal"] is True
    held = await client.get("/api/v1/patients", headers=holder)
    assert (held.status_code, held.json()["message"]) == (403, "Onboarding required")
    assert await _privacy(client, clinic_id) == "outdated"
    # Declining the new one closes the clinic, as declining the first did;
    # opened again by the operator, it is still asked.
    declined = await client.post("/api/v1/auth/clinic/onboarding/decline", headers=holder)
    assert declined.status_code == 204
    assert await _privacy(client, clinic_id) == "declined"
    await client.post(f"/api/v1/ops/clinics/{clinic_id}/reactivate", headers=_token())
    assert await _privacy(client, clinic_id) == "outdated"

    accepted = await client.post(
        "/api/v1/auth/clinic/onboarding/accept", json={"version": "2099-01-01"}, headers=holder
    )
    assert accepted.status_code == 204
    assert (await client.get("/api/v1/patients", headers=holder)).status_code == 200
    assert await _privacy(client, clinic_id) == "accepted"


async def _new_holder(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """A clinic made by the control plane and its holder, past the
    password change."""
    created = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "basic"}, headers=_token()
    )
    holder = await _login(client, HOLDER["holder_password"])
    await client.post(
        "/api/v1/auth/password",
        json={"current_password": HOLDER["holder_password"], "new_password": "Propia5678"},
        headers=holder,
    )
    return created.json()["data"]["clinic_id"], holder


async def _pending(client: AsyncClient, headers: dict[str, str]) -> bool:
    me = await client.get("/api/v1/auth/me", headers=headers)
    return me.json()["data"]["clinics"][0]["onboarding_pending"]


async def _privacy(client: AsyncClient, clinic_id: str) -> str:
    """What the operator is told about the clinic and the agreement."""
    usage = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    [clinic] = [c for c in usage.json()["data"]["clinics"] if c["id"] == clinic_id]
    return clinic["privacy"]


async def test_accepting_the_privacy_agreement_ends_the_welcome(
    client: AsyncClient, ops_enabled: None, db_session: AsyncSession
) -> None:
    clinic_id, holder = await _new_holder(client)
    assert await _pending(client, holder) is True
    assert await _privacy(client, clinic_id) == "pending"

    # Until then the clinic is open to the welcome and nothing else.
    held = await client.get("/api/v1/patients", headers=holder)
    assert (held.status_code, held.json()["message"]) == (403, "Onboarding required")
    assert (await client.get("/api/v1/auth/clinics", headers=holder)).status_code == 200
    assert (await client.get("/api/v1/agenda/cabinets", headers=holder)).status_code == 200

    accepted = await client.post(
        "/api/v1/auth/clinic/onboarding/accept", json=ACCEPTED, headers=holder
    )
    assert accepted.status_code == 204
    assert await _pending(client, holder) is False
    assert (await client.get("/api/v1/patients", headers=holder)).status_code == 200
    clinic = await db_session.get(Clinic, UUID(clinic_id))
    assert clinic.privacy_accepted_at is not None
    assert await _privacy(client, clinic_id) == "accepted"

    # Once accepted there is nothing left to decline.
    declined = await client.post("/api/v1/auth/clinic/onboarding/decline", headers=holder)
    assert declined.status_code == 409


async def test_declining_the_privacy_agreement_closes_the_clinic(
    client: AsyncClient, ops_enabled: None
) -> None:
    clinic_id, holder = await _new_holder(client)

    declined = await client.post("/api/v1/auth/clinic/onboarding/decline", headers=holder)
    assert declined.status_code == 204
    assert (await client.get("/api/v1/auth/clinic/limits", headers=holder)).status_code == 403
    me = await client.get("/api/v1/auth/me", headers=holder)
    assert me.json()["data"]["clinics"][0]["deactivated"] is True

    # The operator sees it deactivated, and can open it again: the holder
    # is back at the welcome.
    usage = await client.get("/api/v1/ops/usage?refresh=true", headers=_token())
    [clinic] = [c for c in usage.json()["data"]["clinics"] if c["id"] == clinic_id]
    assert (clinic["status"], clinic["privacy"]) == ("deactivated", "declined")
    assert clinic["privacy_at"] is not None
    await client.post(f"/api/v1/ops/clinics/{clinic_id}/reactivate", headers=_token())
    assert await _pending(client, holder) is True
    assert await _privacy(client, clinic_id) == "pending"


async def test_a_clinic_nobody_welcomed_has_no_welcome(
    client: AsyncClient, ops_enabled: None, test_clinic: Clinic, auth_headers: dict[str, str]
) -> None:
    assert await _pending(client, auth_headers) is False
    assert await _privacy(client, str(test_clinic.id)) == "not_asked"
    declined = await client.post("/api/v1/auth/clinic/onboarding/decline", headers=auth_headers)
    assert declined.status_code == 409
