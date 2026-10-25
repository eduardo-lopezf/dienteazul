"""Professionals is core for every tier (2026-10-18).

- An individual practice (basic, medium, advanced) has its holder's profile,
  linked to their account, from the day it exists — or the day it is moved
  to such a tier. A clinic tier gets none: it builds its directory.
- The directory's menu entry is for clinic tiers only.
- ``/me`` is the caller's own profile; ``/workload`` what is assigned to each
  professional, from the Apps that assign work.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, User
from app.core.plugins.registry import module_registry
from app.core.plugins.router import _nav_visible
from app.modules.agenda.models import Appointment
from app.modules.patients.models import Patient
from app.modules.professionals.errors import ERROR_CATALOG
from app.modules.professionals.events import (
    on_clinic_account_tier_changed,
    on_clinic_created,
)
from app.modules.professionals.models import Professional
from app.modules.treatment_plan.models import TreatmentPlan
from tests.test_ops_endpoint import HOLDER, _token, ops_enabled  # noqa: F401


async def _profiles(db: AsyncSession, clinic_id: UUID) -> list[Professional]:
    db.expire_all()
    result = await db.execute(select(Professional).where(Professional.clinic_id == clinic_id))
    return list(result.scalars().all())


async def _admin_id(client: AsyncClient, headers: dict) -> UUID:
    me = await client.get("/api/v1/auth/me", headers=headers)
    return UUID(me.json()["data"]["user"]["id"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("ops_enabled")
async def test_a_new_individual_practice_has_its_holders_profile(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await client.post(
        "/api/v1/ops/clinics", json=HOLDER | {"account_tier": "basic"}, headers=_token()
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]

    [profile] = await _profiles(db_session, UUID(data["clinic_id"]))
    assert profile.user_id == UUID(data["holder_user_id"])
    assert (profile.first_name, profile.last_name) == ("Aurelia", "Zamarripa")
    assert profile.license_number == HOLDER["holder_professional_id"]
    assert profile.professional_type == "dentist"


@pytest.mark.asyncio
async def test_a_clinic_tier_builds_its_own_directory(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    await on_clinic_created({"clinic_id": str(test_clinic.id)})
    assert await _profiles(db_session, test_clinic.id) == []


@pytest.mark.asyncio
async def test_moving_to_an_individual_tier_gives_the_holder_a_profile_once(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    test_clinic.account_tier = "medium"
    await db_session.commit()

    for _ in range(2):
        await on_clinic_account_tier_changed({"clinic_id": str(test_clinic.id)})

    [profile] = await _profiles(db_session, test_clinic.id)
    assert profile.user_id == await _admin_id(client, auth_headers)


def test_the_directory_entry_is_for_clinic_tiers_only() -> None:
    [entry] = module_registry.get("professionals").manifest["frontend"]["navigation"]
    for tier in ("clinic", "clinic_pro", "hospital"):
        assert _nav_visible(entry, "admin", tier), tier
    for tier in ("basic", "medium", "advanced"):
        assert not _nav_visible(entry, "admin", tier), tier


@pytest.mark.asyncio
async def test_a_professional_keeps_their_own_details_and_nothing_else(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    missing = await client.get("/api/v1/professionals/me", headers=auth_headers)
    assert missing.status_code == 404
    missing_body = missing.json()
    missing_definition = ERROR_CATALOG["professionals.profile.not_found"]
    assert missing_body["code"] == missing_definition.code
    assert missing_body["category"] == missing_definition.category.value
    assert missing_body["reference"] == missing.headers["x-request-id"]

    user_id = await _admin_id(client, auth_headers)
    db_session.add(
        Professional(
            id=uuid4(),
            clinic_id=test_clinic.id,
            user_id=user_id,
            first_name="Ana",
            last_name="Ríos",
            professional_type="dentist",
        )
    )
    await db_session.commit()

    mine = await client.get("/api/v1/professionals/me", headers=auth_headers)
    assert mine.status_code == 200, mine.text
    assert mine.json()["data"]["user_id"] == str(user_id)

    edited = await client.put(
        "/api/v1/professionals/me",
        json={"license_number": "9876543", "is_active": False, "user_id": None},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    data = edited.json()["data"]
    assert data["license_number"] == "9876543"
    # Who the profile is stays the clinic's.
    assert (data["is_active"], data["user_id"]) == (True, str(user_id))


@pytest.mark.asyncio
async def test_the_workload_counts_each_patient_once_across_apps(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    user = await db_session.get(User, await _admin_id(client, auth_headers))
    dentist = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Dra",
        last_name="Paz",
        professional_type="dentist",
    )
    idle = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Dr",
        last_name="Sola",
        professional_type="dentist",
    )
    ana = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Ana", last_name="Uno")
    beto = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Beto", last_name="Dos")
    db_session.add_all([dentist, idle, ana, beto])
    await db_session.flush()

    soon = datetime.now(UTC) + timedelta(days=2)
    past = datetime.now(UTC) - timedelta(days=2)
    for start, status, patient in (
        (soon, "scheduled", ana),
        (past, "completed", ana),
        (soon, "cancelled", beto),
    ):
        db_session.add(
            Appointment(
                id=uuid4(),
                clinic_id=test_clinic.id,
                patient_id=patient.id,
                professional_id=dentist.id,
                start_time=start,
                end_time=start + timedelta(minutes=30),
                status=status,
            )
        )
    for number, status, patient in (("P-1", "active", ana), ("P-2", "draft", beto)):
        db_session.add(
            TreatmentPlan(
                id=uuid4(),
                clinic_id=test_clinic.id,
                patient_id=patient.id,
                plan_number=number,
                status=status,
                assigned_professional_id=dentist.id,
                created_by=user.id,
            )
        )
    await db_session.commit()

    response = await client.get("/api/v1/professionals/workload", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = {row["professional_id"]: row for row in response.json()["data"]}

    busy = rows[str(dentist.id)]
    # Ana, in two appointments and a plan: one patient. Beto's appointment
    # was cancelled and his plan is a draft: not one they see yet.
    assert busy["patients"] == 1
    assert busy["counts"]["appointments"] == 2
    assert busy["counts"]["appointments_upcoming"] == 1
    assert busy["counts"]["plans_in_progress"] == 1
    # Nothing assigned reads as zeros, not as missing figures.
    idle_row = rows[str(idle.id)]
    assert idle_row["patients"] == 0
    assert idle_row["counts"]["appointments"] == 0
    assert idle_row["counts"]["treatments_pending"] == 0

    # An App that is off says nothing: its figures are absent, not zero.
    module_registry.deactivate("agenda")
    try:
        response = await client.get("/api/v1/professionals/workload", headers=auth_headers)
    finally:
        module_registry.activate("agenda")
    busy = {row["professional_id"]: row for row in response.json()["data"]}[str(dentist.id)]
    assert "appointments" not in busy["counts"]
    assert busy["patients"] == 1
