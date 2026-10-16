"""Budgets and payments runs with the Apps it integrates switched off (ADR 0037).

Patients, the catalog, the odontogram and Professionals are ``integrates``
of the App's modules, never ``depends``. While one is off the App keeps
running: what is stored stays readable and nothing that needs the missing
App is created (``budget/integrations.py``).

- Patients off: budgets, invoices and payments are read without the
  patient; no budget, invoice or payment is made.
- Catalog off: no line is added; the budget is still read and collected.
- Professionals off: none is assigned, and the stored one is hidden.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.plugins.registry import module_registry
from app.modules.budget.integrations import (
    CATALOG_UNAVAILABLE,
    PATIENTS_UNAVAILABLE,
    PROFESSIONALS_UNAVAILABLE,
)
from app.modules.catalog.models import TreatmentCatalogItem, TreatmentCategory, VatType
from app.modules.patients.models import Patient
from app.modules.professionals.models import Professional

APP_MODULES = ["budget", "payments", "billing", "verifactu", "accounting_export"]
INTEGRATED = {"patients", "catalog", "odontogram", "professionals", "media"}
BUDGETS = "/api/v1/budget/budgets"


@contextmanager
def off(*names: str) -> Iterator[None]:
    was_active = [name for name in names if module_registry.is_installed(name)]
    for name in names:
        module_registry.deactivate(name)
    try:
        yield
    finally:
        for name in was_active:
            module_registry.activate(name)


@pytest.fixture
async def world(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    vat = VatType(
        id=uuid4(),
        clinic_id=test_clinic.id,
        names={"es": "Exento", "en": "Exempt"},
        rate=0.0,
        is_default=True,
        is_system=True,
    )
    category = TreatmentCategory(
        id=uuid4(),
        clinic_id=test_clinic.id,
        key="integrations",
        names={"es": "Prueba", "en": "Test"},
        display_order=1,
        is_active=True,
        is_system=False,
    )
    db_session.add_all([vat, category])
    await db_session.flush()
    item = TreatmentCatalogItem(
        id=uuid4(),
        clinic_id=test_clinic.id,
        category_id=category.id,
        internal_code="INT-001",
        names={"es": "Empaste", "en": "Filling"},
        default_price=80,
        vat_type_id=vat.id,
        treatment_scope="whole_tooth",
        is_diagnostic=False,
        is_active=True,
        is_system=False,
    )
    patient = Patient(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Lucía",
        last_name="Morales",
        email="lucia@example.com",
        status="active",
    )
    professional = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Dra",
        last_name="Soto",
        professional_type="dentist",
        is_active=True,
    )
    db_session.add_all([item, patient, professional])
    await db_session.commit()
    return {
        "patient_id": str(patient.id),
        "catalog_item_id": str(item.id),
        "vat_type_id": str(vat.id),
        "professional_id": str(professional.id),
    }


async def _budget_with_a_line(client: AsyncClient, headers: dict, world: dict) -> str:
    created = await client.post(
        BUDGETS,
        json={
            "patient_id": world["patient_id"],
            "valid_from": "2026-01-01",
            "assigned_professional_id": world["professional_id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    budget_id = created.json()["data"]["id"]
    line = await client.post(
        f"{BUDGETS}/{budget_id}/items",
        json={"catalog_item_id": world["catalog_item_id"], "quantity": 1},
        headers=headers,
    )
    assert line.status_code == 201, line.text
    return budget_id


def test_the_app_requires_none_of_its_integrations() -> None:
    for name in APP_MODULES:
        manifest = module_registry.get(name).manifest
        assert not set(manifest.get("depends", [])) & INTEGRATED, name
    assert set(module_registry.get("budget").manifest["integrates"]) == {
        "patients",
        "catalog",
        "odontogram",
        "professionals",
    }


@pytest.mark.asyncio
async def test_without_patients_the_app_only_reads(
    client: AsyncClient, auth_headers: dict, world: dict
) -> None:
    budget_id = await _budget_with_a_line(client, auth_headers, world)

    with off("patients"):
        read = await client.get(f"{BUDGETS}/{budget_id}", headers=auth_headers)
        assert read.status_code == 200, read.text
        budget = read.json()["data"]
        assert budget["patient"] is None
        assert budget["patient_id"] == world["patient_id"]
        assert len(budget["items"]) == 1

        listed = await client.get(BUDGETS, params={"search": "Lucía"}, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"] == []
        everything = await client.get(BUDGETS, headers=auth_headers)
        assert [b["patient"] for b in everything.json()["data"]] == [None]

        refused = await client.post(
            BUDGETS,
            json={"patient_id": world["patient_id"], "valid_from": "2026-01-01"},
            headers=auth_headers,
        )
        assert refused.status_code == 400
        assert refused.json()["message"] == PATIENTS_UNAVAILABLE

        duplicated = await client.post(
            f"{BUDGETS}/{budget_id}/duplicate", json={}, headers=auth_headers
        )
        assert duplicated.status_code == 400
        assert duplicated.json()["message"] == PATIENTS_UNAVAILABLE

        payment = await client.post(
            "/api/v1/payments",
            json={
                "patient_id": world["patient_id"],
                "amount": "20.00",
                "method": "cash",
                "payment_date": "2026-01-02",
                "allocations": [{"target_type": "on_account", "amount": "20.00"}],
            },
            headers=auth_headers,
        )
        assert payment.status_code == 422
        assert payment.json()["message"] == PATIENTS_UNAVAILABLE

        ledger = await client.get(
            f"/api/v1/payments/patients/{world['patient_id']}/ledger", headers=auth_headers
        )
        assert ledger.status_code == 200, ledger.text
        receivables = await client.get("/api/v1/payments/receivables", headers=auth_headers)
        assert receivables.status_code == 200, receivables.text
        assert receivables.json()["data"] == []

        invoice = await client.post(
            "/api/v1/billing/invoices",
            json={"patient_id": world["patient_id"], "items": []},
            headers=auth_headers,
        )
        assert invoice.status_code == 400
        assert invoice.json()["message"] == PATIENTS_UNAVAILABLE

    back = await client.get(f"{BUDGETS}/{budget_id}", headers=auth_headers)
    assert back.json()["data"]["patient"]["first_name"] == "Lucía"


@pytest.mark.asyncio
async def test_without_the_catalog_no_line_is_added(
    client: AsyncClient, auth_headers: dict, world: dict
) -> None:
    budget_id = await _budget_with_a_line(client, auth_headers, world)

    with off("catalog"):
        added = await client.post(
            f"{BUDGETS}/{budget_id}/items",
            json={"catalog_item_id": world["catalog_item_id"], "quantity": 1},
            headers=auth_headers,
        )
        assert added.status_code == 400
        assert added.json()["message"] == CATALOG_UNAVAILABLE

        read = await client.get(f"{BUDGETS}/{budget_id}", headers=auth_headers)
        assert read.status_code == 200, read.text
        items = read.json()["data"]["items"]
        assert len(items) == 1
        # The line keeps the name it was quoted under.
        assert items[0]["catalog_item"]["names"]["es"] == "Empaste"

        # ...and is collected.
        payment = await client.post(
            "/api/v1/payments",
            json={
                "patient_id": world["patient_id"],
                "amount": "80.00",
                "method": "card",
                "payment_date": "2026-01-02",
                "allocations": [
                    {"target_type": "budget", "target_id": budget_id, "amount": "80.00"}
                ],
            },
            headers=auth_headers,
        )
        assert payment.status_code == 201, payment.text

        invoice = await client.post(
            "/api/v1/billing/invoices",
            json={
                "patient_id": world["patient_id"],
                "items": [{"description": "Empaste", "unit_price": "80.00"}],
            },
            headers=auth_headers,
        )
        assert invoice.status_code == 400
        assert invoice.json()["message"] == CATALOG_UNAVAILABLE


@pytest.mark.asyncio
async def test_without_professionals_none_is_assigned_or_shown(
    client: AsyncClient, auth_headers: dict, world: dict
) -> None:
    budget_id = await _budget_with_a_line(client, auth_headers, world)

    with off("professionals"):
        read = await client.get(f"{BUDGETS}/{budget_id}", headers=auth_headers)
        assert read.status_code == 200, read.text
        assert read.json()["data"]["assigned_professional"] is None
        assert read.json()["data"]["assigned_professional_id"] == world["professional_id"]

        assigned = await client.put(
            f"{BUDGETS}/{budget_id}",
            json={"assigned_professional_id": str(uuid4())},
            headers=auth_headers,
        )
        assert assigned.status_code == 400
        assert assigned.json()["message"] == PROFESSIONALS_UNAVAILABLE

    back = await client.get(f"{BUDGETS}/{budget_id}", headers=auth_headers)
    assert back.json()["data"]["assigned_professional"]["last_name"] == "Soto"
