"""Smoke tests for the treatment plan module after the Treatment refactor."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.modules.catalog.models import (
    TreatmentCatalogItem,
    TreatmentCategory,
    TreatmentOdontogramMapping,
    VatType,
)


async def _ensure_clinic_and_patient(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict[str, str]
) -> dict:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]

    clinic = Clinic(
        id=uuid4(),
        name="Plan Clinic",
        tax_id="B11111111",
        address={"street": "a", "city": "b"},
        settings={
            "slot_duration_min": 15,
            # These tests are about plan mechanics. The rule that a plan
            # waits for a signed informed consent is on by default and has
            # its own tests (`test_plan_requires_informed_consent.py`).
            "consents": {"require_informed_for_plan": False},
        },
        account_tier="clinic",
    )
    db_session.add(clinic)
    await db_session.flush()

    db_session.add(
        # Admin, matching conftest's own clinic: these tests exercise plan
        # mechanics, not RBAC, and reopening is now limited to an
        # administrator or a professional the plan is assigned to. The
        # rule itself is covered by the reopen-authorisation tests below.
        ClinicMembership(id=uuid4(), user_id=user_id, clinic_id=clinic.id, role="admin")
    )
    await db_session.commit()

    patient_resp = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "Luis", "last_name": "Soto", "phone": "+34666333444"},
    )
    patient_id = patient_resp.json()["data"]["id"]

    return {"clinic_id": str(clinic.id), "user_id": user_id, "patient_id": patient_id}


async def _seed_catalog_crown(db_session: AsyncSession, clinic_id) -> str:
    vat = VatType(clinic_id=clinic_id, names={"es": "Exento"}, rate=0.0, is_default=True)
    db_session.add(vat)
    await db_session.flush()
    cat = TreatmentCategory(clinic_id=clinic_id, key="rest", names={"es": "R"}, is_system=True)
    db_session.add(cat)
    await db_session.flush()
    crown = TreatmentCatalogItem(
        clinic_id=clinic_id,
        category_id=cat.id,
        internal_code="PLAN-CROWN",
        names={"es": "Corona"},
        default_price=Decimal("500.00"),
        pricing_strategy="flat",
        treatment_scope="tooth",
        default_phase="rehabilitacion",
        vat_type_id=vat.id,
    )
    db_session.add(crown)
    await db_session.flush()
    db_session.add(
        TreatmentOdontogramMapping(
            clinic_id=clinic_id,
            catalog_item_id=crown.id,
            odontogram_treatment_type="crown",
            clinical_category="restauradora",
            visualization_rules=[],
            visualization_config={},
        )
    )
    await db_session.commit()
    return str(crown.id)


@pytest.fixture
async def setup(
    db_session: AsyncSession, auth_headers: dict[str, str], client: AsyncClient
) -> dict:
    ctx = await _ensure_clinic_and_patient(db_session, client, auth_headers)
    ctx["crown_id"] = await _seed_catalog_crown(db_session, ctx["clinic_id"])
    return ctx


async def _create_treatment(
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
    tooth_number: int = 16,
) -> str:
    r = await client.post(
        f"/api/v1/odontogram/patients/{setup['patient_id']}/treatments",
        headers=auth_headers,
        json={
            "catalog_item_id": setup["crown_id"],
            "tooth_numbers": [tooth_number],
            "status": "planned",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def _create_plan_with_items(
    client: AsyncClient, auth_headers: dict, setup: dict, tooth_numbers: list[int]
) -> tuple[str, list[str]]:
    """Helper: create a plan and add N items (one per tooth). Returns (plan_id, item_ids)."""
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Reorder plan"},
    )
    assert plan_resp.status_code == 201, plan_resp.text
    plan_id = plan_resp.json()["data"]["id"]

    item_ids: list[str] = []
    for tn in tooth_numbers:
        treatment_id = await _create_treatment(client, auth_headers, setup, tooth_number=tn)
        add = await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": treatment_id},
        )
        assert add.status_code == 201, add.text
        item_ids.append(add.json()["data"]["id"])
    return plan_id, item_ids


@pytest.mark.asyncio
async def test_create_empty_plan(client: AsyncClient, auth_headers: dict, setup: dict) -> None:
    r = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Demo plan"},
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_add_treatment_item_to_plan(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Demo"},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["treatment_id"] == treatment_id
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_duplicate_treatment_id_rejected(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"]},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    first = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert first.status_code == 201

    # Unique constraint on treatment_id — second add raises IntegrityError
    # which the handler surfaces as a 5xx. Capture the exception to keep the
    # assertion focused on "the duplicate was blocked".
    from sqlalchemy.exc import IntegrityError

    try:
        second = await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": treatment_id},
        )
        assert second.status_code in (400, 409, 500)
    except IntegrityError:
        pass


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reorder_items_happy_path(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15, 14])
    reversed_ids = list(reversed(item_ids))

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/reorder",
        headers=auth_headers,
        json={"item_ids": reversed_ids},
    )
    assert r.status_code == 200, r.text
    returned = [i["id"] for i in r.json()["data"]["items"]]
    assert returned == reversed_ids

    # Persistence: re-fetch.
    g = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    again = [i["id"] for i in g.json()["data"]["items"]]
    assert again == reversed_ids


@pytest.mark.asyncio
async def test_reorder_rejects_missing_item(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])
    # Drop one.
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/reorder",
        headers=auth_headers,
        json={"item_ids": [item_ids[0]]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reorder_rejects_foreign_item(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    from uuid import uuid4

    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])
    bogus = str(uuid4())
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/reorder",
        headers=auth_headers,
        json={"item_ids": [item_ids[0], bogus]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reorder_rejects_duplicate_ids(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/reorder",
        headers=auth_headers,
        json={"item_ids": [item_ids[0], item_ids[0]]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reorder_unknown_plan_returns_404(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    from uuid import uuid4

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{uuid4()}/items/reorder",
        headers=auth_headers,
        json={"item_ids": []},
    )
    assert r.status_code == 404


# -----------------------------------------------------------------------------
# Orphan cleanup on terminal plan states (archive / cancel)
# -----------------------------------------------------------------------------


async def _treatment_is_deleted(
    client: AsyncClient, auth_headers: dict, patient_id: str, treatment_id: str
) -> bool:
    """Check whether a Treatment is soft-deleted by looking for it in the odontogram list."""
    r = await client.get(
        f"/api/v1/odontogram/patients/{patient_id}/treatments",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    active_ids = {t["id"] for t in r.json()["data"]}
    return treatment_id not in active_ids


@pytest.mark.asyncio
async def test_delete_plan_removes_planned_treatments_from_odontogram(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Archiving a plan via DELETE soft-deletes its planned Treatments."""
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16, 15])

    # Snapshot treatment ids from the plan items
    plan_resp = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    treatment_ids = [i["treatment"]["id"] for i in plan_resp.json()["data"]["items"]]
    assert len(treatment_ids) == 2

    # Archive plan
    r = await client.delete(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 204, r.text

    # Both planned treatments should be gone from the odontogram
    for tid in treatment_ids:
        assert await _treatment_is_deleted(client, auth_headers, setup["patient_id"], tid), (
            f"treatment {tid} should be soft-deleted"
        )


@pytest.mark.asyncio
async def test_delete_plan_keeps_performed_treatments(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Archiving a plan preserves Treatments that were already performed."""
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16, 15])

    plan_resp = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    items = plan_resp.json()["data"]["items"]
    treatment_ids = [i["treatment"]["id"] for i in items]
    performed_id, planned_id = treatment_ids[0], treatment_ids[1]

    # Mark first treatment as performed
    r = await client.patch(
        f"/api/v1/odontogram/treatments/{performed_id}/perform",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200, r.text

    # Archive plan
    r = await client.delete(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 204, r.text

    # Performed survives, planned removed
    assert not await _treatment_is_deleted(
        client, auth_headers, setup["patient_id"], performed_id
    ), "performed treatment must be preserved"
    assert await _treatment_is_deleted(client, auth_headers, setup["patient_id"], planned_id), (
        "planned treatment must be soft-deleted"
    )


# -----------------------------------------------------------------------------
# Lock / unlock on budget generation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_item_allowed_after_the_budget_exists(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """The lock guards *changing* a plan, not filling it.

    This used to assert 409: a budget locked the plan against everything,
    so a caries found mid-treatment could only be planned by reopening —
    which cancels the budget the patient signed. Adding takes nothing away
    from what they agreed to, so it is allowed, and the new work is priced
    by an addendum (`test_treatment_plan_addendum.py`). Removing and
    editing still refuse; the two tests below pin that.
    """
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])

    # Confirm the plan (auto-creates budget) and activate.
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/status",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert r.status_code == 200, r.text

    new_treatment_id = await _create_treatment(client, auth_headers, setup, tooth_number=15)
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": new_treatment_id},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_remove_item_blocked_when_budget_generated(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])

    await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/status",
        headers=auth_headers,
        json={"status": "active"},
    )
    await client.post(
        f"/api/v1/budget/plans/{plan_id}/budget",
        headers=auth_headers,
    )

    r = await client.delete(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_ids[0]}",
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_cancel_plan_removes_planned_treatments(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Closing an active plan cleans up its orphaned planned Treatments.

    Workflow rework: draft → pending → active → closed (cancelled_by_clinic).
    """
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    plan_resp = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    treatment_id = plan_resp.json()["data"]["items"][0]["treatment"]["id"]

    # draft → pending (auto-creates draft budget)
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    # pending → active (admin override via patch /status, would normally come from
    # the budget acceptance event; tests do that path explicitly).
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/status",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert r.status_code == 200, r.text

    # active → closed (cancelled by clinic)
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/close",
        headers=auth_headers,
        json={"closure_reason": "cancelled_by_clinic"},
    )
    assert r.status_code == 200, r.text

    assert await _treatment_is_deleted(client, auth_headers, setup["patient_id"], treatment_id)


# ---------------------------------------------------------------------------
# Per-item assigned professional (doctor por tratamiento)
# ---------------------------------------------------------------------------


async def _add_professional(
    db_session: AsyncSession,
    clinic_id: str,
    email: str,
    role: str = "dentist",
) -> str:
    """Create a directory ``Professional`` for tests that need extra doctors."""
    from app.modules.professionals.models import Professional

    professional = Professional(
        id=uuid4(),
        clinic_id=clinic_id,
        first_name="Dr",
        last_name=email.split("@")[0],
        professional_type=role,
        email=email,
        is_active=True,
    )
    db_session.add(professional)
    await db_session.commit()
    return str(professional.id)


@pytest.mark.asyncio
async def test_add_item_inherits_plan_doctor(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    doctor_id = await _add_professional(db_session, setup["clinic_id"], "doc-a@test.com")

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={
            "patient_id": setup["patient_id"],
            "title": "Inherit",
            "assigned_professional_id": doctor_id,
        },
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["assigned_professional_id"] == doctor_id


@pytest.mark.asyncio
async def test_add_item_with_explicit_doctor_overrides_plan(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    doctor_a = await _add_professional(db_session, setup["clinic_id"], "doc-a2@test.com")
    doctor_b = await _add_professional(db_session, setup["clinic_id"], "doc-b@test.com")

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={
            "patient_id": setup["patient_id"],
            "assigned_professional_id": doctor_a,
        },
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id, "assigned_professional_id": doctor_b},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["assigned_professional_id"] == doctor_b


@pytest.mark.asyncio
async def test_add_item_plan_without_doctor_yields_null(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"]},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["assigned_professional_id"] is None


@pytest.mark.asyncio
async def test_add_item_rejects_user_not_in_clinic(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    # User exists but has no membership in our clinic.
    from app.core.auth.models import User
    from app.core.auth.service import hash_password

    other = User(
        id=uuid4(),
        email="not-here@test.com",
        password_hash=hash_password("TestPass123"),
        first_name="Foreign",
        last_name="Doc",
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"]},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id, "assigned_professional_id": str(other.id)},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_item_doctor_can_be_unset_to_null(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    doctor_id = await _add_professional(db_session, setup["clinic_id"], "doc-c@test.com")

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "assigned_professional_id": doctor_id},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    add = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    item_id = add.json()["data"]["id"]

    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}",
        headers=auth_headers,
        json={"assigned_professional_id": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["assigned_professional_id"] is None


@pytest.mark.asyncio
async def test_update_plan_cascade_reassigns_matching_pending(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    doctor_a = await _add_professional(db_session, setup["clinic_id"], "doc-cas-a@test.com")
    doctor_b = await _add_professional(db_session, setup["clinic_id"], "doc-cas-b@test.com")
    doctor_c = await _add_professional(db_session, setup["clinic_id"], "doc-cas-c@test.com")

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "assigned_professional_id": doctor_a},
    )
    plan_id = plan_resp.json()["data"]["id"]

    # Two items inherit doctor_a, one explicit override to doctor_b.
    t1 = await _create_treatment(client, auth_headers, setup, tooth_number=16)
    t2 = await _create_treatment(client, auth_headers, setup, tooth_number=15)
    t3 = await _create_treatment(client, auth_headers, setup, tooth_number=14)

    i1 = (
        await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": t1},
        )
    ).json()["data"]["id"]
    i2 = (
        await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": t2, "assigned_professional_id": doctor_b},
        )
    ).json()["data"]["id"]
    i3 = (
        await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": t3},
        )
    ).json()["data"]["id"]

    # Move plan doctor a → c with cascade.
    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
        json={"assigned_professional_id": doctor_c, "reassign_pending_items": True},
    )
    assert r.status_code == 200, r.text

    detail = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    by_id = {i["id"]: i for i in detail.json()["data"]["items"]}
    assert by_id[i1]["assigned_professional_id"] == doctor_c
    assert by_id[i2]["assigned_professional_id"] == doctor_b  # override survives
    assert by_id[i3]["assigned_professional_id"] == doctor_c


@pytest.mark.asyncio
async def test_update_plan_without_cascade_flag_leaves_items(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    doctor_a = await _add_professional(db_session, setup["clinic_id"], "doc-nc-a@test.com")
    doctor_c = await _add_professional(db_session, setup["clinic_id"], "doc-nc-c@test.com")

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "assigned_professional_id": doctor_a},
    )
    plan_id = plan_resp.json()["data"]["id"]
    t1 = await _create_treatment(client, auth_headers, setup)
    i1 = (
        await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": t1},
        )
    ).json()["data"]["id"]

    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
        json={"assigned_professional_id": doctor_c},  # no flag
    )
    assert r.status_code == 200

    detail = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    items = {i["id"]: i for i in detail.json()["data"]["items"]}
    assert items[i1]["assigned_professional_id"] == doctor_a


@pytest.mark.asyncio
async def test_update_plan_cascade_skips_completed_items(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    doctor_a = await _add_professional(db_session, setup["clinic_id"], "doc-sk-a@test.com")
    doctor_c = await _add_professional(db_session, setup["clinic_id"], "doc-sk-c@test.com")

    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "assigned_professional_id": doctor_a},
    )
    plan_id = plan_resp.json()["data"]["id"]
    t1 = await _create_treatment(client, auth_headers, setup, tooth_number=16)
    t2 = await _create_treatment(client, auth_headers, setup, tooth_number=15)

    i1 = (
        await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": t1},
        )
    ).json()["data"]["id"]
    i2 = (
        await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": t2},
        )
    ).json()["data"]["id"]

    # Complete item 1.
    c = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{i1}/complete",
        headers=auth_headers,
        json={"completed_without_appointment": True},
    )
    assert c.status_code == 200, c.text

    # Cascade: i1 should keep doctor_a (completed); i2 should switch to doctor_c.
    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
        json={"assigned_professional_id": doctor_c, "reassign_pending_items": True},
    )
    assert r.status_code == 200, r.text

    detail = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    items = {i["id"]: i for i in detail.json()["data"]["items"]}
    assert items[i1]["assigned_professional_id"] == doctor_a
    assert items[i2]["assigned_professional_id"] == doctor_c


@pytest.mark.asyncio
async def test_treatment_added_event_carries_assigned_professional(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    from app.core.events import event_bus

    captured: list[dict] = []

    def _spy(payload: dict) -> None:
        captured.append(payload)

    event_bus.subscribe("treatment_plan.treatment_added", _spy)
    try:
        doctor_id = await _add_professional(db_session, setup["clinic_id"], "doc-event@test.com")
        plan_resp = await client.post(
            "/api/v1/treatment_plan/treatment-plans",
            headers=auth_headers,
            json={
                "patient_id": setup["patient_id"],
                "assigned_professional_id": doctor_id,
            },
        )
        plan_id = plan_resp.json()["data"]["id"]
        treatment_id = await _create_treatment(client, auth_headers, setup)

        r = await client.post(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
            headers=auth_headers,
            json={"treatment_id": treatment_id},
        )
        assert r.status_code == 201, r.text
    finally:
        event_bus.unsubscribe("treatment_plan.treatment_added", _spy)

    assert captured, "treatment_added event was not published"
    assert captured[-1]["assigned_professional_id"] == doctor_id


@pytest.mark.asyncio
async def test_change_item_doctor_works_when_plan_is_locked(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    """Doctor reassignment bypasses the plan-lock guard.

    Reassigning who performs a treatment doesn't change the patient-facing
    contract, so it must stay possible even after the plan is confirmed and
    its budget is active.
    """
    doctor_b = await _add_professional(db_session, setup["clinic_id"], "doc-lock-b@test.com")

    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16])
    item_id = item_ids[0]

    # Confirm + activate → plan ends up locked by an active budget.
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/status",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert r.status_code == 200, r.text

    # Sanity: a structural change on the same item is still rejected.
    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}",
        headers=auth_headers,
        json={"notes": "blocked by lock"},
    )
    assert r.status_code == 409, r.text

    # But the doctor change goes through.
    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}",
        headers=auth_headers,
        json={"assigned_professional_id": doctor_b},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["assigned_professional_id"] == doctor_b


@pytest.mark.asyncio
async def test_change_doctor_rejected_on_completed_item(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    setup: dict,
) -> None:
    """Once an item is completed, the planned doctor is frozen.

    ``completed_by`` is the source of truth for "who did it" after the fact;
    rewriting ``assigned_professional_id`` post-completion would distort
    clinical history.
    """
    doctor_b = await _add_professional(db_session, setup["clinic_id"], "doc-comp-b@test.com")

    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16])
    item_id = item_ids[0]

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/complete",
        headers=auth_headers,
        json={"completed_without_appointment": True},
    )
    assert r.status_code == 200, r.text

    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}",
        headers=auth_headers,
        json={"assigned_professional_id": doctor_b},
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Multi-session billing
# ---------------------------------------------------------------------------


async def _seed_catalog_crown_with_sessions(db_session: AsyncSession, clinic_id) -> str:
    """Seed a catalog item with a 2-session template (200€ + 600€ = 800€)."""
    from app.modules.catalog.models import CatalogItemSession

    vat = VatType(clinic_id=clinic_id, names={"es": "Exento"}, rate=0.0, is_default=True)
    db_session.add(vat)
    await db_session.flush()
    cat = TreatmentCategory(clinic_id=clinic_id, key="restMS", names={"es": "R"}, is_system=True)
    db_session.add(cat)
    await db_session.flush()
    crown = TreatmentCatalogItem(
        clinic_id=clinic_id,
        category_id=cat.id,
        internal_code="CROWN-MS",
        names={"es": "Corona multi-sesión"},
        default_price=Decimal("800.00"),
        pricing_strategy="flat",
        treatment_scope="tooth",
        vat_type_id=vat.id,
    )
    db_session.add(crown)
    await db_session.flush()
    db_session.add(
        TreatmentOdontogramMapping(
            clinic_id=clinic_id,
            catalog_item_id=crown.id,
            odontogram_treatment_type="crown",
            clinical_category="restauradora",
            visualization_rules=[],
            visualization_config={},
        )
    )
    db_session.add_all(
        [
            CatalogItemSession(
                catalog_item_id=crown.id,
                sequence=1,
                labels={"es": "Toma de medidas"},
                default_price=Decimal("200.00"),
            ),
            CatalogItemSession(
                catalog_item_id=crown.id,
                sequence=2,
                labels={"es": "Colocación"},
                default_price=Decimal("600.00"),
            ),
        ]
    )
    await db_session.commit()
    return str(crown.id)


@pytest.fixture
async def setup_multi_session(
    db_session: AsyncSession, auth_headers: dict[str, str], client: AsyncClient
) -> dict:
    ctx = await _ensure_clinic_and_patient(db_session, client, auth_headers)
    ctx["crown_ms_id"] = await _seed_catalog_crown_with_sessions(db_session, ctx["clinic_id"])
    return ctx


async def _add_multi_session_item(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> tuple[str, str, list[dict]]:
    """Create a plan + a treatment from the MS catalog item, add it. Returns (plan_id, item_id, sessions)."""
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": ctx["patient_id"], "title": "MS"},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_resp = await client.post(
        f"/api/v1/odontogram/patients/{ctx['patient_id']}/treatments",
        headers=auth_headers,
        json={
            "catalog_item_id": ctx["crown_ms_id"],
            "tooth_numbers": [16],
            "status": "planned",
        },
    )
    treatment_id = treatment_resp.json()["data"]["id"]
    add = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert add.status_code == 201, add.text
    item = add.json()["data"]
    return plan_id, item["id"], item["sessions"]


@pytest.mark.asyncio
async def test_add_item_snapshots_catalog_sessions(
    client: AsyncClient, auth_headers: dict, setup_multi_session: dict
):
    """Catalog template with 2 sessions creates 2 plan item sessions."""
    _, _, sessions = await _add_multi_session_item(client, auth_headers, setup_multi_session)
    assert len(sessions) == 2
    assert [s["sequence"] for s in sessions] == [1, 2]
    assert sessions[0]["label"] == "Toma de medidas"
    assert float(sessions[0]["amount"]) == 200.00
    assert sessions[1]["label"] == "Colocación"
    assert float(sessions[1]["amount"]) == 600.00
    assert all(s["status"] == "pending" for s in sessions)


@pytest.mark.asyncio
async def test_append_session_by_hand_returns_the_saved_row(
    client: AsyncClient, auth_headers: dict, setup: dict
):
    """Appending a session manually must persist it and answer 201.

    The service appended the row to the collection and returned the item
    without flushing. `id` is a Python-side `default=uuid4`, so it was still
    None when the response model serialized it, and Pydantic answered 500 —
    which rolled the row back. Adding a session by hand had never once
    worked; a long treatment could only ever get the sessions its catalog
    template carried.
    """
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"]},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)
    item = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    item_id = item.json()["data"]["id"]

    added = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions",
        headers=auth_headers,
        json={"label": "Revisión al mes", "amount": "0.00"},
    )
    assert added.status_code == 201, added.text
    sessions = added.json()["data"]["sessions"]
    assert len(sessions) == 2
    assert sessions[1]["id"] is not None
    assert sessions[1]["label"] == "Revisión al mes"
    assert sessions[1]["sequence"] == 2

    # And it is really in the database, not just in the response.
    reread = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}", headers=auth_headers
    )
    stored = [i for i in reread.json()["data"]["items"] if i["id"] == item_id][0]
    assert len(stored["sessions"]) == 2


@pytest.mark.asyncio
async def test_add_item_without_catalog_template_creates_single_session(
    client: AsyncClient, auth_headers: dict, setup: dict
):
    """Item from a catalog item without sessions falls back to one session."""
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"]},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)
    add = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    sessions = add.json()["data"]["sessions"]
    assert len(sessions) == 1
    assert float(sessions[0]["amount"]) == 500.00


@pytest.mark.asyncio
async def test_complete_first_session_does_not_finalize_item(
    client: AsyncClient, auth_headers: dict, setup_multi_session: dict
):
    """Completing 1/2 sessions leaves item pending and emits the session event only."""
    from app.core.events import event_bus

    events: list[dict] = []

    async def _capture(payload: dict) -> None:
        events.append(payload)

    event_bus.subscribe("treatment_plan.item_session_completed", _capture)
    event_bus.subscribe("treatment_plan.treatment_completed", _capture)
    try:
        plan_id, item_id, sessions = await _add_multi_session_item(
            client, auth_headers, setup_multi_session
        )
        r = await client.patch(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions/{sessions[0]['id']}/complete",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["status"] == "pending"
        completed = [s for s in data["sessions"] if s["status"] == "completed"]
        assert len(completed) == 1
        # Session-completed event fired; treatment_completed must NOT have fired yet.
        session_events = [e for e in events if "session_id" in e]
        treatment_events = [e for e in events if "treatment_category_key" in e]
        assert len(session_events) == 1
        assert session_events[0]["amount"] == "200.00"
        assert treatment_events == []
    finally:
        # Only the capture: popping the key also dropped the real
        # subscribers (payments books earned entries on this event), and
        # every test after this one ran without them.
        event_bus.unsubscribe("treatment_plan.item_session_completed", _capture)
        event_bus.unsubscribe("treatment_plan.treatment_completed", _capture)


@pytest.mark.asyncio
async def test_complete_last_session_finalizes_item(
    client: AsyncClient, auth_headers: dict, setup_multi_session: dict
):
    """Completing the final pending session flips the item to completed and fires treatment_completed."""
    from app.core.events import event_bus

    events: list[dict] = []

    async def _capture(payload: dict) -> None:
        events.append(payload)

    event_bus.subscribe("treatment_plan.treatment_completed", _capture)
    try:
        plan_id, item_id, sessions = await _add_multi_session_item(
            client, auth_headers, setup_multi_session
        )
        for s in sessions:
            r = await client.patch(
                f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions/{s['id']}/complete",
                headers=auth_headers,
                json={},
            )
            assert r.status_code == 200, r.text
        item = r.json()["data"]
        assert item["status"] == "completed"
        assert len(events) == 1  # treatment_completed fires exactly once
    finally:
        # Only the capture: popping the key also dropped the real
        # subscribers (payments books earned entries on this event), and
        # every test after this one ran without them.
        event_bus.unsubscribe("treatment_plan.treatment_completed", _capture)


@pytest.mark.asyncio
async def test_cancel_session_blocks_earned(
    client: AsyncClient, auth_headers: dict, setup_multi_session: dict
):
    """Cancelled sessions do not fire the session_completed event."""
    from app.core.events import event_bus

    session_events: list[dict] = []

    async def _capture(payload: dict) -> None:
        session_events.append(payload)

    event_bus.subscribe("treatment_plan.item_session_completed", _capture)
    try:
        plan_id, item_id, sessions = await _add_multi_session_item(
            client, auth_headers, setup_multi_session
        )
        # Cancel the 2nd session, complete the 1st
        cancel = await client.patch(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions/{sessions[1]['id']}/cancel",
            headers=auth_headers,
            json={},
        )
        assert cancel.status_code == 200, cancel.text
        complete = await client.patch(
            f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions/{sessions[0]['id']}/complete",
            headers=auth_headers,
            json={},
        )
        item = complete.json()["data"]
        # Item finalizes since all sessions are terminal and one is completed
        assert item["status"] == "completed"
        # Only the completed session fired an earned event; cancelled didn't
        assert len(session_events) == 1
    finally:
        # Only the capture: popping the key also dropped the real
        # subscribers (payments books earned entries on this event), and
        # every test after this one ran without them.
        event_bus.unsubscribe("treatment_plan.item_session_completed", _capture)


@pytest.mark.asyncio
async def test_legacy_complete_endpoint_advances_next_session(
    client: AsyncClient, auth_headers: dict, setup_multi_session: dict
):
    """Legacy PATCH /items/{id}/complete completes the next pending session."""
    plan_id, item_id, sessions = await _add_multi_session_item(
        client, auth_headers, setup_multi_session
    )
    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/complete",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    item = r.json()["data"]
    assert item["status"] == "pending"
    assert sum(1 for s in item["sessions"] if s["status"] == "completed") == 1


@pytest.mark.asyncio
async def test_edit_completed_session_rejected(
    client: AsyncClient, auth_headers: dict, setup_multi_session: dict
):
    """Edits on completed sessions are refused (400)."""
    plan_id, item_id, sessions = await _add_multi_session_item(
        client, auth_headers, setup_multi_session
    )
    await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions/{sessions[0]['id']}/complete",
        headers=auth_headers,
        json={},
    )
    r = await client.put(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_id}/sessions/{sessions[0]['id']}",
        headers=auth_headers,
        json={"label": "Cambio", "amount": 250.00},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_plan_item_inherits_catalog_phase(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Adding a treatment seeds its stage of care from the catalog default."""
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Fases"},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["phase"] == "rehabilitacion"


@pytest.mark.asyncio
async def test_plan_item_phase_can_override_the_catalog(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """The plan owns the decision: the same crown can be urgent care.

    This is why the phase is stored on the item and not read through to the
    catalog row — one patient's planned rehabilitation is another's emergency.
    """
    plan_resp = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Fases"},
    )
    plan_id = plan_resp.json()["data"]["id"]
    treatment_id = await _create_treatment(client, auth_headers, setup, tooth_number=25)

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id, "phase": "urgencia"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["phase"] == "urgencia"


# -----------------------------------------------------------------------------
# Reopen → re-confirm relinks the plan to a live budget
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconfirm_after_reopen_links_the_fresh_budget(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """A reopened plan that is confirmed again points at a *draft* budget.

    Reopening cancels the linked budget but leaves ``budget_id`` set.
    ``confirm`` then provisioned a new draft budget (its idempotency
    check ignores cancelled ones) and used to discard it, because it
    only assigned the link when ``budget_id`` was NULL. The plan was
    left in ``pending`` pointing at a cancelled budget, which matches
    no bandeja tab, so it vanished from the pipeline while the fresh
    budget floated unreferenced.
    """
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    # Minted by `budget` on hearing of the confirmation (ADR 0042).
    r = await client.get(f"/api/v1/treatment_plan/treatment-plans/{plan_id}", headers=auth_headers)
    first_budget_id = r.json()["data"]["budget_id"]
    assert first_budget_id is not None

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/reopen",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "draft"

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "pending"
    r = await client.get(f"/api/v1/treatment_plan/treatment-plans/{plan_id}", headers=auth_headers)
    plan = r.json()["data"]

    second_budget_id = plan["budget_id"]
    assert second_budget_id is not None
    assert second_budget_id != first_budget_id, (
        "re-confirmation must adopt the new budget, not keep the cancelled one"
    )

    # The budget the plan points at has to be workable, otherwise the
    # plan shows up in no pipeline tab.
    r = await client.get(
        f"/api/v1/budget/budgets/{second_budget_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_pipeline_en_curso_holds_pending_and_active(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """The leading tab carries every plan in flight, both statuses."""
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])

    # A draft plan is not yet in flight.
    r = await client.get(
        "/api/v1/treatment_plan/treatment-plans/pipeline?tab=en_curso",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert plan_id not in [row["plan_id"] for row in r.json()["data"]]

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    # `pending` counts — this is the case reception reported.
    r = await client.get(
        "/api/v1/treatment_plan/treatment-plans/pipeline?tab=en_curso",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert plan_id in [row["plan_id"] for row in r.json()["data"]]

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/status",
        headers=auth_headers,
        json={"status": "active"},
    )
    assert r.status_code == 200, r.text

    # ...and so does `active`.
    r = await client.get(
        "/api/v1/treatment_plan/treatment-plans/pipeline?tab=en_curso",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert plan_id in [row["plan_id"] for row in r.json()["data"]]


@pytest.mark.asyncio
async def test_accepting_the_budget_after_a_reopen_still_activates_the_plan(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """The plan reaches ``active`` even when a reopen came first.

    This is the cascade the reopen→re-confirm bug caused. ``budget``
    resolves the plan to activate with a reverse lookup on
    ``treatment_plans.budget_id``; while the re-confirmed budget was
    orphaned that lookup returned NULL, the accepted-budget handler took
    its "orphan budget" early return, and the plan sat in ``pending``
    with an accepted budget nobody had connected to it.
    """
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/reopen",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/treatment_plan/treatment-plans/{plan_id}", headers=auth_headers)
    budget_id = r.json()["data"]["budget_id"]

    r = await client.post(
        f"/api/v1/budget/budgets/{budget_id}/send",
        json={},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/budget/budgets/{budget_id}/accept",
        json={
            "signature": {
                "signed_by_name": "Test Patient",
                "relationship_to_patient": "patient",
            }
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "active", (
        "an accepted budget must still carry the plan to active after a reopen"
    )


@pytest.mark.asyncio
async def test_attending_an_appointment_moves_the_plan_to_active(
    client: AsyncClient, auth_headers: dict, setup: dict, db_session: AsyncSession
) -> None:
    """The first consultation the patient attends starts the plan.

    The clinic counts a plan as under way from the moment the patient
    turns up, which is well before the budget is signed. Note the
    appointment here completes without ticking any treatment off — a
    diagnostic visit usually does — so this also pins that attendance,
    not completion, is the trigger.
    """
    from datetime import UTC, datetime, timedelta

    from app.modules.agenda.models import Appointment, AppointmentTreatment
    from app.modules.professionals.models import Professional
    from app.modules.treatment_plan import events as tp_events

    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "pending"

    professional = Professional(
        id=uuid4(),
        clinic_id=setup["clinic_id"],
        first_name="Ada",
        last_name="Lovelace",
        professional_type="dentist",
    )
    db_session.add(professional)
    await db_session.flush()

    started = datetime.now(UTC) - timedelta(hours=2)
    appointment = Appointment(
        id=uuid4(),
        clinic_id=setup["clinic_id"],
        patient_id=setup["patient_id"],
        professional_id=professional.id,
        start_time=started,
        end_time=started + timedelta(minutes=30),
        status="completed",
    )
    db_session.add(appointment)
    await db_session.flush()

    db_session.add(
        AppointmentTreatment(
            id=uuid4(),
            appointment_id=appointment.id,
            planned_treatment_item_id=item_ids[0],
            # Nothing ticked off: the dentist looked, measured and booked.
            completed_in_appointment=False,
        )
    )
    await db_session.commit()

    await tp_events.on_appointment_completed(
        {
            "appointment_id": str(appointment.id),
            "clinic_id": str(setup["clinic_id"]),
            "patient_id": str(setup["patient_id"]),
            # What the agenda puts in the event (ADR 0042).
            "planned_items": [{"planned_item_id": str(item_ids[0]), "completed": False}],
        }
    )

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    plan = r.json()["data"]
    assert plan["status"] == "active", "attending the consultation must start the plan"
    # The budget is untouched — attendance does not sign anything.
    assert plan["budget_id"] is not None


@pytest.mark.asyncio
async def test_attendance_does_not_start_an_unconfirmed_plan(
    client: AsyncClient, auth_headers: dict, setup: dict, db_session: AsyncSession
) -> None:
    """A `draft` plan must not skip confirmation just because a visit happened."""
    from datetime import UTC, datetime, timedelta

    from app.modules.agenda.models import Appointment, AppointmentTreatment
    from app.modules.professionals.models import Professional
    from app.modules.treatment_plan import events as tp_events

    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16])

    professional = Professional(
        id=uuid4(),
        clinic_id=setup["clinic_id"],
        first_name="Grace",
        last_name="Hopper",
        professional_type="dentist",
    )
    db_session.add(professional)
    await db_session.flush()

    started = datetime.now(UTC) - timedelta(hours=1)
    appointment = Appointment(
        id=uuid4(),
        clinic_id=setup["clinic_id"],
        patient_id=setup["patient_id"],
        professional_id=professional.id,
        start_time=started,
        end_time=started + timedelta(minutes=30),
        status="completed",
    )
    db_session.add(appointment)
    await db_session.flush()
    db_session.add(
        AppointmentTreatment(
            id=uuid4(),
            appointment_id=appointment.id,
            planned_treatment_item_id=item_ids[0],
            completed_in_appointment=False,
        )
    )
    await db_session.commit()

    await tp_events.on_appointment_completed(
        {
            "appointment_id": str(appointment.id),
            "clinic_id": str(setup["clinic_id"]),
            "patient_id": str(setup["patient_id"]),
            # What the agenda puts in the event (ADR 0042).
            "planned_items": [{"planned_item_id": str(item_ids[0]), "completed": False}],
        }
    )

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_completing_a_treatment_starts_the_plan(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Work recorded against a plan starts it, with no appointment involved.

    Ticking a treatment off straight on the plan is how a first
    consultation is usually recorded: it sets
    ``completed_without_appointment`` and creates no appointment row, so
    the attendance rule keyed to ``appointment.completed`` never saw it
    and the plan sat in ``pending`` with work already done against it.
    """
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "pending"

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_ids[0]}/complete",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "active", (
        "a completed treatment must start the plan even without an appointment"
    )


@pytest.mark.asyncio
async def test_completing_the_last_treatment_crosses_both_transitions(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """One completion can both start and finish a plan.

    A single-item plan that is confirmed and then carried out has no
    moment in between. Starting before checking for completion is what
    lets it land on ``completed`` rather than stalling in ``pending``
    with every item done — ``_check_and_complete_plan`` only ever
    finishes an ``active`` plan.
    """
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_ids[0]}/complete",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "completed"


@pytest.mark.asyncio
async def test_completing_a_treatment_does_not_start_a_draft_plan(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """An unconfirmed plan still has to be confirmed, work or no work."""
    plan_id, item_ids = await _create_plan_with_items(client, auth_headers, setup, [16, 15])

    r = await client.patch(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items/{item_ids[0]}/complete",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "draft"


# -----------------------------------------------------------------------------
# Who may reopen a plan
# -----------------------------------------------------------------------------


async def _make_dentist_membership(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, clinic_id: str
) -> None:
    """Demote the acting user to dentist in this clinic."""
    from sqlalchemy import update as sa_update

    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    await db_session.execute(
        sa_update(ClinicMembership)
        .where(
            ClinicMembership.user_id == UUID(user_id),
            ClinicMembership.clinic_id == UUID(clinic_id),
        )
        .values(role="dentist")
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_dentist_cannot_reopen_a_plan_that_is_not_theirs(
    client: AsyncClient, auth_headers: dict, setup: dict, db_session: AsyncSession
) -> None:
    """Reopening throws away a budget, so it is not open to any dentist.

    The plan here is assigned to nobody, which by the rule leaves it to
    an administrator alone.
    """
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    await _make_dentist_membership(db_session, client, auth_headers, setup["clinic_id"])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/reopen",
        headers=auth_headers,
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_the_assigned_professional_may_reopen_their_own_plan(
    client: AsyncClient, auth_headers: dict, setup: dict, db_session: AsyncSession
) -> None:
    """Assignment carries the right with it, without an admin role.

    The bridge between an account and a directory profile is the licence
    number — ``users.professional_id`` against
    ``professionals.license_number`` — so the professional is only
    recognised once both carry the same one.
    """
    from sqlalchemy import update as sa_update

    from app.core.auth.models import User
    from app.modules.professionals.models import Professional
    from app.modules.treatment_plan.models import TreatmentPlan

    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]

    licence = "TEST/9001"
    professional = Professional(
        id=uuid4(),
        clinic_id=UUID(setup["clinic_id"]),
        first_name="Ada",
        last_name="Lovelace",
        professional_type="dentist",
        license_number=licence,
    )
    db_session.add(professional)
    await db_session.execute(
        sa_update(User).where(User.id == UUID(user_id)).values(professional_id=licence)
    )
    await db_session.execute(
        sa_update(TreatmentPlan)
        .where(TreatmentPlan.id == UUID(plan_id))
        .values(assigned_professional_id=professional.id)
    )
    await db_session.commit()

    await _make_dentist_membership(db_session, client, auth_headers, setup["clinic_id"])

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/reopen",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_reopening_is_written_to_the_plan_history(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Every reopen leaves a line naming who did it and what it cancelled."""
    plan_id, _ = await _create_plan_with_items(client, auth_headers, setup, [16])
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/reopen",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/history",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    actions = [entry["action"] for entry in data["entries"]]
    assert "reopened" in actions
    assert "confirmed" in actions

    reopened = next(e for e in data["entries"] if e["action"] == "reopened")
    assert reopened["from_status"] == "pending"
    assert reopened["to_status"] == "draft"
    assert reopened["actor_name"]
    assert reopened["payload"]["cancelled_budget"]


# -----------------------------------------------------------------------------
# Searching by name
# -----------------------------------------------------------------------------


async def _patient_named(client: AsyncClient, auth_headers: dict, first: str, last: str) -> str:
    r = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": first, "last_name": last, "phone": "+34600111222"},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


@pytest.mark.asyncio
async def test_plan_search_matches_full_name_and_ignores_accents(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """The two ways reception actually types a name.

    Matching the whole query against one column at a time meant "Juan
    Pérez" found nobody — no column holds both words — and an ILIKE
    between "Perez" and "Pérez" matches nothing either, which in Spanish
    is most of what "the search doesn't work" means.
    """
    patient_id = await _patient_named(client, auth_headers, "Begoña", "Ñuño Peña")
    r = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": patient_id, "title": "Buscador"},
    )
    assert r.status_code == 201, r.text
    plan_id = r.json()["data"]["id"]

    async def found(query: str) -> list[str]:
        resp = await client.get(
            "/api/v1/treatment_plan/treatment-plans",
            headers=auth_headers,
            params={"search": query, "page_size": 100},
        )
        assert resp.status_code == 200, resp.text
        return [p["id"] for p in resp.json()["data"]]

    # Either half, in either order, accented or not.
    assert plan_id in await found("Begoña")
    assert plan_id in await found("Begona")
    assert plan_id in await found("Ñuño")
    assert plan_id in await found("Nuno")
    assert plan_id in await found("Begona Nuno")
    assert plan_id in await found("Nuno Begona")
    # Case is handled by ILIKE and always was.
    assert plan_id in await found("BEGONA")

    # Every word has to match something, or a two-word query would widen
    # the results instead of narrowing them.
    assert plan_id not in await found("Begona Zzzz")
    assert await found("zzzznotapatient") == []


@pytest.mark.asyncio
async def test_plan_search_is_applied_at_all(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """The "Todos" tab sent `search` into a parameter that did not exist.

    FastAPI drops unknown query parameters without complaining, so the
    box filtered nothing and every plan came back — the list looked
    broken rather than empty.
    """
    mine = await _patient_named(client, auth_headers, "Zenobia", "Quintanilla")
    r = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": mine, "title": "Buscador"},
    )
    assert r.status_code == 201, r.text

    other = await _patient_named(client, auth_headers, "Wenceslao", "Barrenechea")
    r = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": other, "title": "Buscador"},
    )
    assert r.status_code == 201, r.text

    unfiltered = await client.get(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        params={"page_size": 100},
    )
    filtered = await client.get(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        params={"search": "Zenobia", "page_size": 100},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] < unfiltered.json()["total"]
    assert filtered.json()["total"] == 1


@pytest.mark.asyncio
async def test_pipeline_search_matches_full_name_and_ignores_accents(
    client: AsyncClient, auth_headers: dict, setup: dict
) -> None:
    """Same rules on the bandeja, which has its own hand-written SQL."""
    patient_id = await _patient_named(client, auth_headers, "Begoña", "Ñuño Peña")
    # The treatment has to belong to this patient, not the fixture's, or
    # the plan refuses it.
    r = await client.post(
        f"/api/v1/odontogram/patients/{patient_id}/treatments",
        headers=auth_headers,
        json={
            "catalog_item_id": setup["crown_id"],
            "tooth_numbers": [16],
            "status": "planned",
        },
    )
    assert r.status_code == 201, r.text
    treatment_id = r.json()["data"]["id"]

    r = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": patient_id, "title": "Buscador"},
    )
    plan_id = r.json()["data"]["id"]
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/items",
        headers=auth_headers,
        json={"treatment_id": treatment_id},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/treatment_plan/treatment-plans/{plan_id}/confirm",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    async def found(query: str) -> list[str]:
        resp = await client.get(
            "/api/v1/treatment_plan/treatment-plans/pipeline",
            headers=auth_headers,
            params={"tab": "por_presupuestar", "q": query, "page_size": 100},
        )
        assert resp.status_code == 200, resp.text
        return [row["plan_id"] for row in resp.json()["data"]]

    assert plan_id in await found("Begona Nuno")
    assert plan_id in await found("Nuno")
    assert plan_id not in await found("Begona Zzzz")


@pytest.mark.asyncio
async def test_plan_number_survives_a_gap_in_the_sequence(
    client: AsyncClient, auth_headers: dict, setup: dict, db_session: AsyncSession
) -> None:
    """The number is one past the highest, not one past the count.

    Counting handed out a number that already existed as soon as a plan
    row had ever been removed, and every later plan failed on the unique
    constraint.
    """
    from sqlalchemy import delete

    from app.modules.treatment_plan.models import TreatmentPlan

    numbers = []
    ids = []
    for _ in range(2):
        r = await client.post(
            "/api/v1/treatment_plan/treatment-plans",
            headers=auth_headers,
            json={"patient_id": setup["patient_id"], "title": "Gap"},
        )
        assert r.status_code == 201, r.text
        numbers.append(r.json()["data"]["plan_number"])
        ids.append(r.json()["data"]["id"])

    await db_session.execute(delete(TreatmentPlan).where(TreatmentPlan.id == UUID(ids[0])))
    await db_session.commit()

    r = await client.post(
        "/api/v1/treatment_plan/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Gap"},
    )
    assert r.status_code == 201, r.text
    third = r.json()["data"]["plan_number"]
    assert third not in numbers
    assert int(third.split("-")[-1]) == int(numbers[1].split("-")[-1]) + 1
