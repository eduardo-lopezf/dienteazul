"""Tests for the catalog module."""

import inspect
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.modules.catalog.errors import ERROR_CATALOG
from app.modules.catalog.models import (
    TreatmentCatalogItem,
    TreatmentCategory,
    VatType,
)
from app.modules.catalog.router import list_items
from app.modules.catalog.service import MAX_PAGE_SIZE


@pytest.fixture
async def catalog_clinic_setup(
    db_session: AsyncSession, auth_headers: dict[str, str], client: AsyncClient
) -> dict:
    """Set up a clinic with the test user as admin for catalog tests."""
    # Get user from /me endpoint
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = response.json()["data"]["user"]["id"]

    # Create clinic
    clinic = Clinic(
        id=uuid4(),
        name="Catalog Test Clinic",
        tax_id="B87654321",
        address={"street": "Catalog St", "city": "Madrid"},
        settings={"slot_duration_min": 15},
        account_tier="clinic",
    )
    db_session.add(clinic)
    await db_session.flush()

    # Create admin membership
    membership = ClinicMembership(
        id=uuid4(),
        user_id=user_id,
        clinic_id=clinic.id,
        role="admin",
    )
    db_session.add(membership)

    # Create default VAT types for the clinic
    vat_exempt = VatType(
        id=uuid4(),
        clinic_id=clinic.id,
        names={"es": "Exento", "en": "Exempt"},
        rate=0.0,
        is_default=True,
        is_system=True,
    )
    vat_reduced = VatType(
        id=uuid4(),
        clinic_id=clinic.id,
        names={"es": "Reducido (10%)", "en": "Reduced (10%)"},
        rate=10.0,
        is_default=False,
        is_system=True,
    )
    vat_standard = VatType(
        id=uuid4(),
        clinic_id=clinic.id,
        names={"es": "General (21%)", "en": "Standard (21%)"},
        rate=21.0,
        is_default=False,
        is_system=True,
    )
    db_session.add_all([vat_exempt, vat_reduced, vat_standard])
    await db_session.commit()

    return {
        "clinic_id": str(clinic.id),
        "user_id": user_id,
        "vat_exempt_id": str(vat_exempt.id),
        "vat_reduced_id": str(vat_reduced.id),
        "vat_standard_id": str(vat_standard.id),
    }


@pytest.mark.asyncio
async def test_list_categories(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test listing treatment categories."""
    response = await client.get(
        "/api/v1/catalog/categories",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_create_category(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test creating a treatment category."""
    response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "test_category",
            "names": {"es": "Categoría de Prueba", "en": "Test Category"},
            "display_order": 100,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["key"] == "test_category"
    assert data["names"]["es"] == "Categoría de Prueba"
    assert data["names"]["en"] == "Test Category"
    assert data["is_system"] is False


@pytest.mark.asyncio
async def test_create_category_duplicate_key(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test that duplicate category keys are rejected."""
    # Create first category
    await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "duplicate_key",
            "names": {"es": "Primera", "en": "First"},
        },
        headers=auth_headers,
    )

    # Try to create duplicate
    response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "duplicate_key",
            "names": {"es": "Segunda", "en": "Second"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    definition = ERROR_CATALOG["catalog.category.duplicate"]
    body = response.json()
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == response.headers["x-request-id"]
    assert "duplicate_key" in body["message"]


@pytest.mark.asyncio
async def test_update_category(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test updating a treatment category."""
    # Create category
    create_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "update_test",
            "names": {"es": "Original", "en": "Original"},
        },
        headers=auth_headers,
    )
    category_id = create_response.json()["data"]["id"]

    # Update category
    response = await client.put(
        f"/api/v1/catalog/categories/{category_id}",
        json={
            "names": {"es": "Actualizado", "en": "Updated"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["names"]["es"] == "Actualizado"
    assert data["names"]["en"] == "Updated"


@pytest.mark.asyncio
async def test_delete_category(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test deleting a treatment category."""
    # Create category
    create_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "delete_test",
            "names": {"es": "Para Borrar", "en": "To Delete"},
        },
        headers=auth_headers,
    )
    category_id = create_response.json()["data"]["id"]

    # Delete category
    response = await client.delete(
        f"/api/v1/catalog/categories/{category_id}",
        headers=auth_headers,
    )
    assert response.status_code == 204

    # Verify it's deleted
    get_response = await client.get(
        f"/api/v1/catalog/categories/{category_id}",
        headers=auth_headers,
    )
    assert get_response.status_code == 404
    definition = ERROR_CATALOG["catalog.category.not_found"]
    body = get_response.json()
    assert body["code"] == definition.code
    assert body["category"] == definition.category.value
    assert body["reference"] == get_response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_list_catalog_items(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test listing catalog items."""
    response = await client.get(
        "/api/v1/catalog/items",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert isinstance(data["data"], list)
    assert "total" in data
    assert "page" in data
    assert "page_size" in data


@pytest.mark.asyncio
async def test_create_catalog_item(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test creating a catalog item."""
    # First create a category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "item_test_category",
            "names": {"es": "Categoría", "en": "Category"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create catalog item with VAT type
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "TEST-001",
            "names": {"es": "Tratamiento de Prueba", "en": "Test Treatment"},
            "descriptions": {"es": "Descripción", "en": "Description"},
            "default_price": 100.00,
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
            "is_diagnostic": False,
            "requires_surfaces": False,
            "requires_appointment": True,
            "default_duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["internal_code"] == "TEST-001"
    assert data["names"]["es"] == "Tratamiento de Prueba"
    assert float(data["default_price"]) == 100.00
    assert data["vat_type"]["rate"] == 0.0  # Check rate from VatType object
    assert data["vat_type_id"] == catalog_clinic_setup["vat_exempt_id"]
    assert data["is_system"] is False


@pytest.mark.asyncio
async def test_create_catalog_item_duplicate_code(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test that duplicate internal codes are rejected."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "dup_item_category",
            "names": {"es": "Cat", "en": "Cat"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create first item
    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "DUP-001",
            "names": {"es": "Primero", "en": "First"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )

    # Try to create duplicate
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "DUP-001",
            "names": {"es": "Segundo", "en": "Second"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_get_catalog_item(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test getting a single catalog item."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "get_item_category",
            "names": {"es": "Cat", "en": "Cat"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create item
    create_response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "GET-001",
            "names": {"es": "Obtener", "en": "Get"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    item_id = create_response.json()["data"]["id"]

    # Get item
    response = await client.get(
        f"/api/v1/catalog/items/{item_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["internal_code"] == "GET-001"


@pytest.mark.asyncio
async def test_update_catalog_item(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test updating a catalog item."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "update_item_category",
            "names": {"es": "Cat", "en": "Cat"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create item
    create_response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "UPD-001",
            "names": {"es": "Original", "en": "Original"},
            "default_price": 50.00,
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    item_id = create_response.json()["data"]["id"]

    # Update item
    response = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={
            "names": {"es": "Actualizado", "en": "Updated"},
            "default_price": 75.00,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["names"]["es"] == "Actualizado"
    assert float(data["default_price"]) == 75.00


@pytest.mark.asyncio
async def test_delete_catalog_item(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test deleting a catalog item (soft delete)."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "delete_item_category",
            "names": {"es": "Cat", "en": "Cat"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create item
    create_response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "DEL-001",
            "names": {"es": "Borrar", "en": "Delete"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    item_id = create_response.json()["data"]["id"]

    # Delete item
    response = await client.delete(
        f"/api/v1/catalog/items/{item_id}",
        headers=auth_headers,
    )
    assert response.status_code == 204

    # Verify it's not in list
    list_response = await client.get(
        "/api/v1/catalog/items",
        headers=auth_headers,
    )
    item_ids = [item["id"] for item in list_response.json()["data"]]
    assert item_id not in item_ids


@pytest.mark.asyncio
async def test_search_catalog_items(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test searching catalog items."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "search_category",
            "names": {"es": "Búsqueda", "en": "Search"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create items
    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "SRCH-CORONA",
            "names": {"es": "Corona Dental", "en": "Dental Crown"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )

    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "SRCH-EXTRAC",
            "names": {"es": "Extracción", "en": "Extraction"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )

    # Search by code
    response = await client.get(
        "/api/v1/catalog/items/search?q=CORONA",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) >= 1
    assert any("CORONA" in item["internal_code"] for item in data)

    # Search by name
    response = await client.get(
        "/api/v1/catalog/items/search?q=Extrac",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_recent_items_are_ordered_by_last_use_not_by_count(
    client: AsyncClient,
    auth_headers: dict,
    catalog_clinic_setup: dict,
    db_session: AsyncSession,
):
    """Recency and frequency are different questions, and they disagree.

    The treatment a clinic used twice yesterday belongs above the one it used
    thirty times last year — that is the whole reason this endpoint exists
    next to `/items/popular`.
    """
    category = await client.post(
        "/api/v1/catalog/categories",
        json={"key": "recency", "names": {"es": "Recencia"}},
        headers=auth_headers,
    )
    category_id = category.json()["data"]["id"]

    codes = ["REC-OLD", "REC-NEW"]
    item_ids = {}
    for code in codes:
        created = await client.post(
            "/api/v1/catalog/items",
            json={
                "category_id": category_id,
                "internal_code": code,
                "names": {"es": code},
                "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
                "treatment_scope": "global_mouth",
            },
            headers=auth_headers,
        )
        item_ids[code] = created.json()["data"]["id"]

    patient = await client.post(
        "/api/v1/patients",
        json={"first_name": "Reciente", "last_name": "Prueba"},
        headers=auth_headers,
    )
    patient_id = patient.json()["data"]["id"]

    # The old one three times, the new one once and later. Written straight to
    # the chart table because that is what the ranking reads — and on
    # `recorded_at`, the clinical date, not `created_at`, which is only when
    # the row happened to be written.
    clinic_id = catalog_clinic_setup["clinic_id"]
    await db_session.execute(
        text("""
            INSERT INTO treatments
                (id, clinic_id, patient_id, clinical_type, scope, catalog_item_id,
                 status, recorded_at, source_module, created_at, updated_at)
            VALUES
                (gen_random_uuid(), :clinic, :patient, 'other', 'global_mouth', :old,
                 'planned', now() - interval '30 days', 'test', now(), now()),
                (gen_random_uuid(), :clinic, :patient, 'other', 'global_mouth', :old,
                 'planned', now() - interval '29 days', 'test', now(), now()),
                (gen_random_uuid(), :clinic, :patient, 'other', 'global_mouth', :old,
                 'planned', now() - interval '28 days', 'test', now(), now()),
                (gen_random_uuid(), :clinic, :patient, 'other', 'global_mouth', :new,
                 'planned', now() - interval '1 day', 'test', now(), now())
        """),
        {
            "clinic": clinic_id,
            "patient": patient_id,
            "old": item_ids["REC-OLD"],
            "new": item_ids["REC-NEW"],
        },
    )
    await db_session.commit()

    recent = await client.get("/api/v1/catalog/items/recent?limit=5", headers=auth_headers)
    assert recent.status_code == 200
    ranked = [i["internal_code"] for i in recent.json()["data"]]
    assert ranked[:2] == ["REC-NEW", "REC-OLD"]

    popular = await client.get("/api/v1/catalog/items/popular?limit=5", headers=auth_headers)
    assert popular.status_code == 200


@pytest.mark.asyncio
async def test_search_items_ignores_accents_and_word_order(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Staff type without accents and in whatever order the words come out.

    A plain ILIKE on the whole string answers neither: "reconstruccion" never
    matches "Reconstrucción", and "radicular alisado" never matches "Raspado y
    alisado radicular". Same two rules as the patient search.
    """
    category = await client.post(
        "/api/v1/catalog/categories",
        json={"key": "accents", "names": {"es": "Acentos"}},
        headers=auth_headers,
    )
    category_id = category.json()["data"]["id"]

    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "ACC-RAR",
            "names": {"es": "Raspado y alisado radicular"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "ACC-RECON",
            "names": {"es": "Reconstrucción amplia"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )

    unaccented = await client.get(
        "/api/v1/catalog/items/search?q=reconstruccion",
        headers=auth_headers,
    )
    assert unaccented.status_code == 200
    assert [i["internal_code"] for i in unaccented.json()["data"]] == ["ACC-RECON"]

    reordered = await client.get(
        "/api/v1/catalog/items/search?q=radicular%20alisado",
        headers=auth_headers,
    )
    assert reordered.status_code == 200
    assert [i["internal_code"] for i in reordered.json()["data"]] == ["ACC-RAR"]

    # The picker needs both of these to decide what it may offer and whether
    # the treatment is still waiting for a tooth.
    assert unaccented.json()["data"][0]["treatment_scope"] == "tooth"
    assert unaccented.json()["data"][0]["is_diagnostic"] is False


@pytest.mark.asyncio
async def test_list_items_with_category_filter(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test filtering catalog items by category."""
    # Create two categories
    cat1_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "filter_cat_1",
            "names": {"es": "Cat 1", "en": "Cat 1"},
        },
        headers=auth_headers,
    )
    cat1_id = cat1_response.json()["data"]["id"]

    cat2_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "filter_cat_2",
            "names": {"es": "Cat 2", "en": "Cat 2"},
        },
        headers=auth_headers,
    )
    cat2_id = cat2_response.json()["data"]["id"]

    # Create items in each category
    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": cat1_id,
            "internal_code": "FILT-CAT1",
            "names": {"es": "En Cat 1", "en": "In Cat 1"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )

    await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": cat2_id,
            "internal_code": "FILT-CAT2",
            "names": {"es": "En Cat 2", "en": "In Cat 2"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )

    # Filter by category 1
    response = await client.get(
        f"/api/v1/catalog/items?category_id={cat1_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    # All items should be from category 1
    for item in data:
        if item["internal_code"].startswith("FILT-"):
            assert item["category_id"] == cat1_id


@pytest.mark.asyncio
async def test_get_odontogram_treatments(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test getting treatments with odontogram mappings."""
    response = await client.get(
        "/api/v1/catalog/odontogram-treatments",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_get_odontogram_treatments_by_category(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test getting odontogram treatments grouped by category."""
    response = await client.get(
        "/api/v1/catalog/odontogram-treatments/by-category",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert isinstance(data["data"], dict)


@pytest.mark.asyncio
async def test_catalog_item_with_odontogram_mapping(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test creating a catalog item with odontogram mapping."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "odonto_test_category",
            "names": {"es": "Odontograma", "en": "Odontogram"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create item with odontogram mapping
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "ODONTO-001",
            "names": {"es": "Con Mapeo", "en": "With Mapping"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
            "odontogram_mapping": {
                "odontogram_treatment_type": "crown",
                "clinical_category": "restauradora",
                "visualization_rules": [
                    {"layer": "cenital_pattern", "pattern": "outline", "color": "#3B82F6"}
                ],
                "visualization_config": {"color": "#3B82F6"},
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["internal_code"] == "ODONTO-001"
    assert data["odontogram_mapping"] is not None
    assert data["odontogram_mapping"]["odontogram_treatment_type"] == "crown"


@pytest.mark.asyncio
async def test_catalog_requires_authentication(client: AsyncClient):
    """Test that catalog endpoints require authentication."""
    response = await client.get("/api/v1/catalog/items")
    assert response.status_code == 401

    response = await client.get("/api/v1/catalog/categories")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_catalog_item_pagination(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test catalog item pagination."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "pagination_category",
            "names": {"es": "Paginación", "en": "Pagination"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create multiple items
    for i in range(5):
        await client.post(
            "/api/v1/catalog/items",
            json={
                "category_id": category_id,
                "internal_code": f"PAGE-{i:03d}",
                "names": {"es": f"Item {i}", "en": f"Item {i}"},
                "vat_type": "exempt",
                "vat_rate": 0,
                "treatment_scope": "tooth",
            },
            headers=auth_headers,
        )

    # Test pagination
    response = await client.get(
        "/api/v1/catalog/items?page=1&page_size=2",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) <= 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] >= 5


@pytest.mark.asyncio
async def test_clinic_cannot_hold_the_same_specialty_twice(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """A second row under the same name splits a discipline in two.

    The field was free text with no check, and the form suggested a name that
    already existed. The cost is not an untidy list: professionals get tagged
    with one row and treatments with the other, so "only what my team does"
    silently matches nothing.

    Accents and case do not make a different discipline either.
    """
    first = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Ortodoncia"}},
        headers=auth_headers,
    )
    assert first.status_code == 201

    for attempt in ({"es": "Ortodoncia"}, {"es": "ortodoncia"}, {"es": "ORTODONCIA"}):
        clash = await client.post(
            "/api/v1/catalog/specialties", json={"names": attempt}, headers=auth_headers
        )
        assert clash.status_code == 409, attempt
        if attempt == {"es": "Ortodoncia"}:
            definition = ERROR_CATALOG["catalog.specialty.duplicate"]
            body = clash.json()
            assert body["code"] == definition.code
            assert body["category"] == definition.category.value
            assert body["reference"] == clash.headers["x-request-id"]
            assert "Specialty already exists: Ortodoncia (active)" == body["message"]

    # Another language of the same row is still that row.
    across = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"en": "Ortodoncia"}},
        headers=auth_headers,
    )
    assert across.status_code == 409


@pytest.mark.asyncio
async def test_a_deactivated_specialty_still_blocks_the_name(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Deactivating hides the row, not its treatment assignments.

    So a clinic that switches one off and types the name again would end up
    with the live half empty and the assignments stranded on the invisible
    one. The refusal says the existing row is inactive, which is a different
    instruction: switch it back on.
    """
    created = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Odontología del Sueño"}},
        headers=auth_headers,
    )
    specialty_id = created.json()["data"]["id"]
    await client.delete(f"/api/v1/catalog/specialties/{specialty_id}", headers=auth_headers)

    clash = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Odontologia del Sueno"}},
        headers=auth_headers,
    )
    assert clash.status_code == 409

    # And no second row was created behind the refusal.
    listed = await client.get(
        "/api/v1/catalog/specialties?include_inactive=true", headers=auth_headers
    )
    matching = [
        s
        for s in listed.json()["data"]
        if "sue" in (s["names"].get("es", "").lower().replace("ñ", "n"))
    ]
    assert [s["id"] for s in matching] == [specialty_id]


@pytest.mark.asyncio
async def test_renaming_a_specialty_onto_another_is_refused(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Otherwise the rule only guards the front door."""
    await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Periodoncia"}},
        headers=auth_headers,
    )
    other = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Periodoncia avanzada"}},
        headers=auth_headers,
    )
    other_id = other.json()["data"]["id"]

    clash = await client.put(
        f"/api/v1/catalog/specialties/{other_id}",
        json={"names": {"es": "Periodoncia"}},
        headers=auth_headers,
    )
    assert clash.status_code == 409

    # Renaming onto itself is not a clash.
    same = await client.put(
        f"/api/v1/catalog/specialties/{other_id}",
        json={"names": {"es": "Periodoncia avanzada"}},
        headers=auth_headers,
    )
    assert same.status_code == 200


@pytest.mark.asyncio
async def test_specialty_suggestions_drop_what_the_clinic_already_has(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """The recognised list is what the clinic is missing, not the whole vocabulary.

    Picking one carries its stable key, which is what stops two people typing
    "Radiología" from producing two rows — and what a later seed run would
    match rather than duplicate.
    """
    offered = await client.get("/api/v1/catalog/specialties/suggestions", headers=auth_headers)
    assert offered.status_code == 200
    keys = [s["key"] for s in offered.json()["data"]]
    assert "radiologia" in keys
    assert all(s["names"].get("es") and s["names"].get("en") for s in offered.json()["data"])

    picked = next(s for s in offered.json()["data"] if s["key"] == "radiologia")
    created = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": picked["names"], "key": "radiologia"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["data"]["key"] == "radiologia"

    again = await client.get("/api/v1/catalog/specialties/suggestions", headers=auth_headers)
    assert "radiologia" not in [s["key"] for s in again.json()["data"]]


@pytest.mark.asyncio
async def test_a_client_cannot_mint_a_specialty_key(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """The key is the seeder's matching handle, not a free field.

    An invented one could silently claim a name the product ships later, and
    the clinic would find its own row updated by a seed run it never asked for.
    """
    refused = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Inventada"}, "key": "inventada"},
        headers=auth_headers,
    )
    assert refused.status_code == 400

    # Free text is still allowed; it simply carries no key.
    free = await client.post(
        "/api/v1/catalog/specialties",
        json={"names": {"es": "Inventada"}},
        headers=auth_headers,
    )
    assert free.status_code == 201
    assert free.json()["data"]["key"] is None


@pytest.mark.asyncio
async def test_item_keeps_every_specialty_a_write_does_not_mention(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """``specialty_ids`` replaces the set; omitting it leaves the set alone.

    Both halves matter to the same screen. The catalog form offered one
    discipline where the relation holds many, so it read back the first and
    sent that one — and a crown over an implant, filed under three, came out
    of a price change with one. Whoever sends the key owns the whole set;
    whoever does not send it changes nothing.
    """
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={"key": "disciplines", "names": {"es": "Disciplinas", "en": "Disciplines"}},
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    specialty_ids = []
    for name in ("Implantología", "Rehabilitación Oral", "Odontología General"):
        created = await client.post(
            "/api/v1/catalog/specialties",
            json={"names": {"es": name, "en": name}},
            headers=auth_headers,
        )
        specialty_ids.append(created.json()["data"]["id"])

    item = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "DISC-CROWN-IMPL",
            "names": {"es": "Corona sobre implante", "en": "Crown over implant"},
            "default_price": 750,
            "treatment_scope": "tooth",
            "specialty_ids": specialty_ids,
        },
        headers=auth_headers,
    )
    assert item.status_code == 201
    item_id = item.json()["data"]["id"]
    assert len(item.json()["data"]["specialties"]) == 3

    # A price change that says nothing about disciplines must not touch them.
    priced = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={"default_price": 800},
        headers=auth_headers,
    )
    assert priced.status_code == 200
    assert len(priced.json()["data"]["specialties"]) == 3

    # Sending the key is a replacement, not a merge.
    narrowed = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={"specialty_ids": specialty_ids[:1]},
        headers=auth_headers,
    )
    assert narrowed.status_code == 200
    assert [s["id"] for s in narrowed.json()["data"]["specialties"]] == specialty_ids[:1]


@pytest.mark.asyncio
async def test_items_page_size_cannot_exceed_what_the_service_serves(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """The advertised maximum page and the served one must be the same number.

    They were not: the route accepted ``page_size`` up to 500 while the service
    clamped to 100 and the envelope echoed the 500 back. A caller asking for
    everything was handed a fifth of it and told the page held 500 — the
    management screen drew 100 of a 136-treatment catalog under the heading
    "136", with three categories missing outright.
    """
    declared = inspect.signature(list_items).parameters["page_size"].default
    upper_bound = next(m.le for m in declared.metadata if hasattr(m, "le"))
    assert upper_bound == MAX_PAGE_SIZE

    accepted = await client.get(
        f"/api/v1/catalog/items?page_size={MAX_PAGE_SIZE}", headers=auth_headers
    )
    assert accepted.status_code == 200
    assert accepted.json()["page_size"] == MAX_PAGE_SIZE

    refused = await client.get(
        f"/api/v1/catalog/items?page_size={MAX_PAGE_SIZE + 1}", headers=auth_headers
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_items_envelope_never_promises_more_than_it_returns(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Whatever page size is granted, the rows delivered fill it or exhaust the set.

    This is the invariant a client pages on: a short page means the end. When
    the service silently shrank the page, a client that trusted ``page_size``
    stopped early and never learned there was more.
    """
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={"key": "envelope", "names": {"es": "Sobre", "en": "Envelope"}},
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    for i in range(7):
        await client.post(
            "/api/v1/catalog/items",
            json={
                "category_id": category_id,
                "internal_code": f"ENVELOPE-{i:03d}",
                "names": {"es": f"Envelope {i}", "en": f"Envelope {i}"},
                "treatment_scope": "tooth",
            },
            headers=auth_headers,
        )

    seen: set[str] = set()
    page = 1
    while True:
        response = await client.get(
            f"/api/v1/catalog/items?page={page}&page_size=3", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["page_size"] == 3
        assert len(body["data"]) <= body["page_size"]
        seen.update(item["id"] for item in body["data"])
        if len(body["data"]) < body["page_size"]:
            break
        page += 1

    assert len(seen) == body["total"]


@pytest.mark.asyncio
async def test_catalog_item_vat_types(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test different VAT types for catalog items."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "vat_category",
            "names": {"es": "IVA", "en": "VAT"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create exempt item (healthcare)
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "VAT-EXEMPT",
            "names": {"es": "Exento", "en": "Exempt"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["vat_type_id"] == catalog_clinic_setup["vat_exempt_id"]
    assert data["vat_type"]["rate"] == 0.0
    assert data["vat_type"]["names"]["en"] == "Exempt"

    # Create reduced VAT item
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "VAT-REDUCED",
            "names": {"es": "Reducido", "en": "Reduced"},
            "vat_type_id": catalog_clinic_setup["vat_reduced_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["vat_type_id"] == catalog_clinic_setup["vat_reduced_id"]
    assert data["vat_type"]["rate"] == 10.0

    # Create standard VAT item (cosmetic)
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "VAT-STANDARD",
            "names": {"es": "General", "en": "Standard"},
            "vat_type_id": catalog_clinic_setup["vat_standard_id"],
            "treatment_scope": "tooth",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["vat_type_id"] == catalog_clinic_setup["vat_standard_id"]
    assert data["vat_type"]["rate"] == 21.0


@pytest.mark.asyncio
async def test_catalog_item_treatment_scopes(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test different treatment scopes."""
    # Create category
    cat_response = await client.post(
        "/api/v1/catalog/categories",
        json={
            "key": "scope_category",
            "names": {"es": "Alcance", "en": "Scope"},
        },
        headers=auth_headers,
    )
    category_id = cat_response.json()["data"]["id"]

    # Create whole tooth treatment
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "SCOPE-TOOTH",
            "names": {"es": "Diente Completo", "en": "Whole Tooth"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
            "requires_surfaces": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["data"]["treatment_scope"] == "tooth"
    assert response.json()["data"]["requires_surfaces"] is False

    # Create surface-sensitive tooth treatment (requires_surfaces flag drives per-surface pricing).
    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "SCOPE-SURFACE",
            "names": {"es": "Por Superficie", "en": "Per Surface"},
            "vat_type_id": catalog_clinic_setup["vat_exempt_id"],
            "treatment_scope": "tooth",
            "requires_surfaces": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["data"]["treatment_scope"] == "tooth"
    assert response.json()["data"]["requires_surfaces"] is True


# ============================================================================
# VAT Types Management Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_vat_types(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test listing VAT types."""
    response = await client.get(
        "/api/v1/catalog/vat-types",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert isinstance(data["data"], list)
    # Should have the 3 seeded VAT types
    assert len(data["data"]) >= 3


@pytest.mark.asyncio
async def test_get_default_vat_type(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test getting the default VAT type."""
    response = await client.get(
        "/api/v1/catalog/vat-types/default",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_default"] is True
    assert data["rate"] == 0.0  # Exempt is the default


@pytest.mark.asyncio
async def test_get_vat_type_by_id(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test getting a VAT type by ID."""
    vat_type_id = catalog_clinic_setup["vat_exempt_id"]
    response = await client.get(
        f"/api/v1/catalog/vat-types/{vat_type_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == vat_type_id
    assert data["rate"] == 0.0


@pytest.mark.asyncio
async def test_create_vat_type(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test creating a new VAT type."""
    response = await client.post(
        "/api/v1/catalog/vat-types",
        json={
            "names": {"es": "Super Reducido", "en": "Super Reduced"},
            "rate": 4.0,
            "is_default": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["names"]["es"] == "Super Reducido"
    assert data["rate"] == 4.0
    assert data["is_default"] is False
    assert data["is_system"] is False


@pytest.mark.asyncio
async def test_update_vat_type(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test updating a VAT type."""
    # First create a non-system VAT type
    create_response = await client.post(
        "/api/v1/catalog/vat-types",
        json={
            "names": {"es": "Para Editar", "en": "To Edit"},
            "rate": 5.0,
        },
        headers=auth_headers,
    )
    vat_type_id = create_response.json()["data"]["id"]

    # Update it
    response = await client.put(
        f"/api/v1/catalog/vat-types/{vat_type_id}",
        json={
            "names": {"es": "Editado", "en": "Edited"},
            "rate": 7.0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["names"]["es"] == "Editado"
    assert data["rate"] == 7.0


@pytest.mark.asyncio
async def test_delete_vat_type(client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict):
    """Test deleting (deactivating) a VAT type."""
    # First create a non-system VAT type
    create_response = await client.post(
        "/api/v1/catalog/vat-types",
        json={
            "names": {"es": "Para Eliminar", "en": "To Delete"},
            "rate": 6.0,
        },
        headers=auth_headers,
    )
    vat_type_id = create_response.json()["data"]["id"]

    # Delete it
    response = await client.delete(
        f"/api/v1/catalog/vat-types/{vat_type_id}",
        headers=auth_headers,
    )
    assert response.status_code == 204

    # Verify it's inactive (not visible by default)
    list_response = await client.get(
        "/api/v1/catalog/vat-types",
        headers=auth_headers,
    )
    ids = [vt["id"] for vt in list_response.json()["data"]]
    assert vat_type_id not in ids


@pytest.mark.asyncio
async def test_cannot_delete_system_vat_type(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test that system VAT type cannot be deleted."""
    # System VAT types return 403
    vat_type_id = catalog_clinic_setup["vat_exempt_id"]
    response = await client.delete(
        f"/api/v1/catalog/vat-types/{vat_type_id}",
        headers=auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cannot_delete_default_vat_type(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test that default VAT type cannot be deleted (even non-system ones)."""
    # Create a non-system VAT type and make it default
    create_response = await client.post(
        "/api/v1/catalog/vat-types",
        json={
            "names": {"es": "Nuevo Por Defecto", "en": "New Default"},
            "rate": 8.0,
            "is_default": True,  # This will make it the new default
        },
        headers=auth_headers,
    )
    vat_type_id = create_response.json()["data"]["id"]
    assert create_response.json()["data"]["is_default"] is True

    # Try to delete the default (non-system) VAT type
    response = await client.delete(
        f"/api/v1/catalog/vat-types/{vat_type_id}",
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_setting_new_default_unsets_old(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Test that setting a new default VAT type unsets the old one."""
    # Set reduced as default
    vat_type_id = catalog_clinic_setup["vat_reduced_id"]
    response = await client.put(
        f"/api/v1/catalog/vat-types/{vat_type_id}",
        json={"is_default": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["is_default"] is True

    # Check that exempt is no longer default
    exempt_response = await client.get(
        f"/api/v1/catalog/vat-types/{catalog_clinic_setup['vat_exempt_id']}",
        headers=auth_headers,
    )
    assert exempt_response.json()["data"]["is_default"] is False


# ============================================================================
# Session template (multi-session billing)
# ============================================================================


async def _create_catalog_category(client: AsyncClient, auth_headers: dict, key: str) -> str:
    response = await client.post(
        "/api/v1/catalog/categories",
        json={"key": key, "names": {"es": key, "en": key}},
        headers=auth_headers,
    )
    return response.json()["data"]["id"]


@pytest.mark.asyncio
async def test_create_item_with_session_template(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Sessions whose prices sum to default_price are accepted."""
    category_id = await _create_catalog_category(client, auth_headers, "sessions_ok")

    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "CROWN-SESS",
            "names": {"es": "Corona", "en": "Crown"},
            "default_price": 800.00,
            "sessions": [
                {"labels": {"es": "Toma de medidas"}, "default_price": 200.00},
                {"labels": {"es": "Colocación"}, "default_price": 600.00},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert len(data["sessions"]) == 2
    assert data["sessions"][0]["sequence"] == 1
    assert float(data["sessions"][0]["default_price"]) == 200.00
    assert data["sessions"][1]["labels"]["es"] == "Colocación"


@pytest.mark.asyncio
async def test_create_item_session_sum_mismatch_rejected(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Sessions whose prices don't sum to default_price get 422."""
    category_id = await _create_catalog_category(client, auth_headers, "sessions_mismatch")

    response = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "CROWN-BAD",
            "names": {"es": "Corona", "en": "Crown"},
            "default_price": 800.00,
            "sessions": [
                {"labels": {"es": "Sesión 1"}, "default_price": 100.00},
                {"labels": {"es": "Sesión 2"}, "default_price": 600.00},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_price_on_its_own_cannot_orphan_a_session_template(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Changing only the price of a staged treatment is refused, not absorbed.

    The rule is that the stages add up to the total, and it was checked only
    when a template came with the write. So a plain ``{"default_price": 800}``
    moved a crown off its own stages — "Toma de medidas 250 + Colocación 500"
    still summing to 750 — and the form that drew them could not represent the
    result. The catalog list types prices without knowing an item has stages,
    which is exactly the caller that would have hit it.
    """
    category_id = await _create_catalog_category(client, auth_headers, "sessions_orphan")
    created = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "CROWN-STAGED",
            "names": {"es": "Corona por sesiones"},
            "default_price": 750.00,
            "sessions": [
                {"labels": {"es": "Toma de medidas"}, "default_price": 250.00},
                {"labels": {"es": "Colocación"}, "default_price": 500.00},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    item_id = created.json()["data"]["id"]

    refused = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={"default_price": 800.00},
        headers=auth_headers,
    )
    assert refused.status_code == 422

    unchanged = await client.get(f"/api/v1/catalog/items/{item_id}", headers=auth_headers)
    assert Decimal(unchanged.json()["data"]["default_price"]) == Decimal("750.00")

    # With the stages restated, the same move is fine.
    accepted = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={
            "default_price": 800.00,
            "sessions": [
                {"labels": {"es": "Toma de medidas"}, "default_price": 300.00},
                {"labels": {"es": "Colocación"}, "default_price": 500.00},
            ],
        },
        headers=auth_headers,
    )
    assert accepted.status_code == 200

    # And a treatment without stages is unaffected by any of this.
    plain = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "CROWN-FLAT",
            "names": {"es": "Corona plana"},
            "default_price": 400.00,
        },
        headers=auth_headers,
    )
    repriced = await client.put(
        f"/api/v1/catalog/items/{plain.json()['data']['id']}",
        json={"default_price": 455.00},
        headers=auth_headers,
    )
    assert repriced.status_code == 200
    assert Decimal(repriced.json()["data"]["default_price"]) == Decimal("455.00")


@pytest.mark.asyncio
async def test_update_item_replaces_session_template(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """PUT /items with sessions replaces the stored template atomically."""
    category_id = await _create_catalog_category(client, auth_headers, "sessions_replace")
    create = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "ENDO-SESS",
            "names": {"es": "Endodoncia"},
            "default_price": 300.00,
            "sessions": [
                {"labels": {"es": "Sesión 1"}, "default_price": 150.00},
                {"labels": {"es": "Sesión 2"}, "default_price": 150.00},
            ],
        },
        headers=auth_headers,
    )
    assert create.status_code == 201
    item_id = create.json()["data"]["id"]

    # Replace template with 3 sessions
    update = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={
            "sessions": [
                {"labels": {"es": "S1"}, "default_price": 100.00},
                {"labels": {"es": "S2"}, "default_price": 100.00},
                {"labels": {"es": "S3"}, "default_price": 100.00},
            ],
        },
        headers=auth_headers,
    )
    assert update.status_code == 200
    sessions = update.json()["data"]["sessions"]
    assert len(sessions) == 3
    assert [s["sequence"] for s in sessions] == [1, 2, 3]

    # Empty list clears the template
    clear = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={"sessions": []},
        headers=auth_headers,
    )
    assert clear.status_code == 200
    assert clear.json()["data"]["sessions"] == []


@pytest.mark.asyncio
async def test_update_item_sessions_omitted_preserves_template(
    client: AsyncClient, auth_headers: dict, catalog_clinic_setup: dict
):
    """Omitting `sessions` in PUT leaves the existing template untouched."""
    category_id = await _create_catalog_category(client, auth_headers, "sessions_preserve")
    create = await client.post(
        "/api/v1/catalog/items",
        json={
            "category_id": category_id,
            "internal_code": "BRIDGE-SESS",
            "names": {"es": "Puente"},
            "default_price": 500.00,
            "sessions": [
                {"labels": {"es": "A"}, "default_price": 250.00},
                {"labels": {"es": "B"}, "default_price": 250.00},
            ],
        },
        headers=auth_headers,
    )
    item_id = create.json()["data"]["id"]

    # Update only the cost_price; sessions key absent
    update = await client.put(
        f"/api/v1/catalog/items/{item_id}",
        json={"cost_price": 100.00},
        headers=auth_headers,
    )
    assert update.status_code == 200
    assert len(update.json()["data"]["sessions"]) == 2


# ---------------------------------------------------------------------------
# Removing seeded treatments
# ---------------------------------------------------------------------------


async def _seeded_item(db_session, setup: dict) -> TreatmentCatalogItem:
    """A treatment as the seeder leaves it: ``is_system=True``."""
    category = TreatmentCategory(
        id=uuid4(),
        clinic_id=UUID(setup["clinic_id"]),
        key=f"cat-{uuid4().hex[:6]}",
        names={"es": "Sembrada"},
        is_system=True,
    )
    db_session.add(category)
    await db_session.flush()
    item = TreatmentCatalogItem(
        id=uuid4(),
        clinic_id=UUID(setup["clinic_id"]),
        category_id=category.id,
        vat_type_id=UUID(setup["vat_exempt_id"]),
        internal_code=f"SEED-{uuid4().hex[:6].upper()}",
        names={"es": "Obturación amalgama"},
        default_price=Decimal("60.00"),
        pricing_strategy="flat",
        treatment_scope="tooth",
        is_system=True,
    )
    db_session.add(item)
    await db_session.commit()
    return item


@pytest.mark.asyncio
async def test_admin_can_remove_a_seeded_treatment(
    client, auth_headers, catalog_clinic_setup, db_session
):
    """A clinic does not offer everything the starter catalog ships.

    Refusing to remove seeded treatments left ~130 of them cluttering every
    picker permanently.
    """
    item = await _seeded_item(db_session, catalog_clinic_setup)

    r = await client.delete(f"/api/v1/catalog/items/{item.id}", headers=auth_headers)
    assert r.status_code == 204, r.text

    listed = await client.get(
        f"/api/v1/catalog/items?search={item.internal_code}", headers=auth_headers
    )
    assert listed.json()["data"] == []

    bar = await client.get("/api/v1/catalog/odontogram-treatments", headers=auth_headers)
    assert all(t["internal_code"] != item.internal_code for t in bar.json()["data"])


@pytest.mark.asyncio
async def test_a_removed_treatment_can_be_found_and_restored(
    client, auth_headers, catalog_clinic_setup, db_session
):
    """The deletion is soft, so it must not be a one-way door."""
    item = await _seeded_item(db_session, catalog_clinic_setup)
    await client.delete(f"/api/v1/catalog/items/{item.id}", headers=auth_headers)

    found = await client.get(
        f"/api/v1/catalog/items?search={item.internal_code}&include_deleted=true",
        headers=auth_headers,
    )
    assert len(found.json()["data"]) == 1

    restored = await client.put(
        f"/api/v1/catalog/items/{item.id}",
        headers=auth_headers,
        json={"is_active": True},
    )
    assert restored.status_code == 200, restored.text

    listed = await client.get(
        f"/api/v1/catalog/items?search={item.internal_code}", headers=auth_headers
    )
    assert len(listed.json()["data"]) == 1
    assert listed.json()["data"][0]["is_active"] is True


@pytest.mark.asyncio
async def test_removing_a_treatment_keeps_its_history(
    client, auth_headers, catalog_clinic_setup, db_session
):
    """The row survives: performed treatments and budget lines point at it."""
    item = await _seeded_item(db_session, catalog_clinic_setup)
    await client.delete(f"/api/v1/catalog/items/{item.id}", headers=auth_headers)

    row = (
        await db_session.execute(
            select(TreatmentCatalogItem).where(TreatmentCatalogItem.id == item.id)
        )
    ).scalar_one()
    assert row.deleted_at is not None
    assert row.is_active is False


@pytest.mark.asyncio
async def test_the_internal_code_of_a_seeded_treatment_stays_locked(
    client, auth_headers, catalog_clinic_setup, db_session
):
    """Renaming it would make the next seed run recreate the original.

    Deleting is safe because the seeder matches on ``internal_code`` and
    finds the soft-deleted row; renaming breaks exactly that match.
    """
    item = await _seeded_item(db_session, catalog_clinic_setup)

    r = await client.put(
        f"/api/v1/catalog/items/{item.id}",
        headers=auth_headers,
        json={"internal_code": "OTRO-CODIGO"},
    )
    assert r.status_code == 403
