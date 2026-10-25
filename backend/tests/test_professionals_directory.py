"""Tests for the professionals directory CRUD endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import hash_password
from app.modules.professionals.errors import ERROR_CATALOG


@pytest.mark.asyncio
async def test_professional_matching_user_email_has_system_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    """A directory profile whose email matches a member of this clinic is
    flagged as having system access."""
    # auth_headers belongs to test@example.com, who test_clinic already
    # made an admin member of this clinic.
    create_response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Test",
            "last_name": "User",
            "professional_type": "dentist",
            "email": "test@example.com",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["data"]["has_system_access"] is True


@pytest.mark.asyncio
async def test_professional_without_matching_user_lacks_system_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    create_response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "External",
            "last_name": "Collaborator",
            "professional_type": "collaborator",
            "email": "no-such-user@example.com",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["data"]["has_system_access"] is False


@pytest.mark.asyncio
async def test_professional_without_email_lacks_system_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    create_response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={"first_name": "No", "last_name": "Email", "professional_type": "collaborator"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["data"]["has_system_access"] is False


@pytest.mark.asyncio
async def test_system_access_scoped_to_clinic_membership(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    """A matching email belonging to a user with no membership in *this*
    clinic must not be reported as having access here."""
    other_clinic = Clinic(
        id=uuid4(),
        name="Other Clinic",
        tax_id="B87654321",
        address={"street": "Other St", "city": "Madrid"},
        settings={"slot_duration_min": 15},
        account_tier="clinic",
    )
    db_session.add(other_clinic)
    await db_session.flush()

    outsider = User(
        id=uuid4(),
        email="outsider@example.com",
        password_hash=hash_password("TestPass1234"),
        first_name="Out",
        last_name="Sider",
    )
    db_session.add(outsider)
    await db_session.flush()
    db_session.add(
        ClinicMembership(id=uuid4(), user_id=outsider.id, clinic_id=other_clinic.id, role="dentist")
    )
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Out",
            "last_name": "Sider",
            "professional_type": "dentist",
            "email": "outsider@example.com",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["data"]["has_system_access"] is False


@pytest.mark.asyncio
async def test_list_and_get_report_system_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    create_response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Test",
            "last_name": "User",
            "professional_type": "dentist",
            "email": "TEST@Example.com",  # case-insensitive match
        },
    )
    professional_id = create_response.json()["data"]["id"]

    list_response = await client.get("/api/v1/professionals", headers=auth_headers)
    assert list_response.status_code == 200
    item = next(p for p in list_response.json()["data"] if p["id"] == professional_id)
    assert item["has_system_access"] is True

    get_response = await client.get(
        f"/api/v1/professionals/{professional_id}", headers=auth_headers
    )
    assert get_response.status_code == 200
    assert get_response.json()["data"]["has_system_access"] is True


async def _create_clinic_specialty(client: AsyncClient, auth_headers: dict, name: str) -> str:
    response = await client.post(
        "/api/v1/catalog/specialties",
        headers=auth_headers,
        json={"names": {"es": name, "en": name}},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


@pytest.mark.asyncio
async def test_specialties_come_back_resolved(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    """A profile links to catalog specialties, and the names travel with it."""
    specialty_id = await _create_clinic_specialty(client, auth_headers, "Ortodoncia")

    response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Orto",
            "last_name": "Dentista",
            "professional_type": "dentist",
            "specialty_ids": [specialty_id],
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert [s["id"] for s in data["specialties"]] == [specialty_id]
    assert data["specialties"][0]["names"]["es"] == "Ortodoncia"


@pytest.mark.asyncio
async def test_professional_can_practise_several_disciplines(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    """A dentist doing both endodontics and periodontics is ordinary."""
    endo = await _create_clinic_specialty(client, auth_headers, "Endodoncia")
    perio = await _create_clinic_specialty(client, auth_headers, "Periodoncia")

    created = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Multi",
            "last_name": "Disciplina",
            "professional_type": "dentist",
            "specialty_ids": [endo, perio],
        },
    )
    assert created.status_code == 201
    assert {s["id"] for s in created.json()["data"]["specialties"]} == {endo, perio}

    # The update payload is authoritative: dropping one unlinks it.
    updated = await client.put(
        f"/api/v1/professionals/{created.json()['data']['id']}",
        headers=auth_headers,
        json={"specialty_ids": [perio]},
    )
    assert updated.status_code == 200
    assert [s["id"] for s in updated.json()["data"]["specialties"]] == [perio]


@pytest.mark.asyncio
async def test_specialty_from_another_clinic_is_rejected(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    """The FK alone only proves the row exists — tenancy must be checked."""
    from app.modules.catalog.models import Specialty

    other_clinic = Clinic(
        id=uuid4(),
        name="Otra Clínica",
        tax_id="B99999999",
        address={"street": "Otra", "city": "Madrid"},
        settings={},
        account_tier="clinic",
    )
    db_session.add(other_clinic)
    await db_session.flush()

    foreign = Specialty(id=uuid4(), clinic_id=other_clinic.id, names={"es": "Ajena"})
    db_session.add(foreign)
    await db_session.commit()

    response = await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Intruso",
            "last_name": "Perfil",
            "professional_type": "dentist",
            "specialty_ids": [str(foreign.id)],
        },
    )
    assert response.status_code == 400
    definition = ERROR_CATALOG["professionals.specialty.not_found"]
    body = response.json()
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_search_matches_linked_specialty_name(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    """Search by discipline still works now that it lives in another table."""
    specialty_id = await _create_clinic_specialty(client, auth_headers, "Endodoncia")
    await client.post(
        "/api/v1/professionals",
        headers=auth_headers,
        json={
            "first_name": "Endo",
            "last_name": "Especialista",
            "professional_type": "dentist",
            "specialty_ids": [specialty_id],
        },
    )

    response = await client.get("/api/v1/professionals?search=Endodoncia", headers=auth_headers)
    assert response.status_code == 200
    names = [p["first_name"] for p in response.json()["data"]]
    assert "Endo" in names
