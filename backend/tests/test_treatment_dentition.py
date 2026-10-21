"""A catalog treatment says which teeth it can be done on, and the odontogram
keeps to it (phase 3 of the age-aware odontogram).

No implant on a primary tooth, no primary pulpotomy on a permanent one.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.catalog.models import (
    TreatmentCatalogItem,
    TreatmentCategory,
    TreatmentOdontogramMapping,
    VatType,
    dentition_fits,
)
from app.modules.catalog.reference import BY_CODE, seed_item
from app.modules.catalog.seed import seed_catalog
from app.modules.patients.models import Patient


def test_a_treatment_fits_the_teeth_of_its_dentition() -> None:
    assert dentition_fits("both", 16) and dentition_fits("both", 54)
    assert dentition_fits("deciduous", 84) and not dentition_fits("deciduous", 46)
    assert dentition_fits("permanent", 11) and not dentition_fits("permanent", 51)


def test_the_reference_says_it_and_the_seed_copies_it() -> None:
    def dentition(code: str) -> str:
        return BY_CODE[code][1].dentition

    assert dentition("PED-PULPOTOMY") == "deciduous"
    assert dentition("PED-HALL") == "deciduous"
    assert dentition("SURG-IMP-TI") == "permanent"
    assert dentition("REST-VEN-PORC") == "permanent"
    # A young permanent tooth is still a permanent one.
    assert dentition("PED-FILL-PERM") == "permanent"
    # Most work suits any tooth.
    assert dentition("REST-COMP") == "both"
    assert dentition("PREV-SEAL") == "both"
    assert seed_item(BY_CODE["PED-PULPOTOMY"][1])["dentition"] == "deciduous"


@pytest.mark.asyncio
async def test_a_seeded_clinic_carries_the_reference_dentition(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    await seed_catalog(db_session, test_clinic.id)
    await db_session.commit()
    rows = (
        await db_session.execute(
            select(TreatmentCatalogItem.internal_code, TreatmentCatalogItem.dentition).where(
                TreatmentCatalogItem.clinic_id == test_clinic.id
            )
        )
    ).all()
    assert rows
    assert {code: d for code, d in rows} == {
        code: BY_CODE[code][1].dentition for code, _ in rows if code in BY_CODE
    }


async def _items(db: AsyncSession, clinic: Clinic) -> dict[str, str]:
    vat = VatType(clinic_id=clinic.id, names={"es": "Exento"}, rate=0.0, is_default=True)
    category = TreatmentCategory(clinic_id=clinic.id, key="mix", names={"es": "M"})
    db.add_all([vat, category])
    await db.flush()

    made: dict[str, str] = {}
    for code, dentition, chart_type, clinical in (
        ("T-IMPLANT", "permanent", "implant", "cirugia"),
        ("T-PULPOTOMY", "deciduous", "root_canal_half", "pediatrica"),
        ("T-FILLING", "both", "filling_composite", "restauradora"),
    ):
        item = TreatmentCatalogItem(
            clinic_id=clinic.id,
            category_id=category.id,
            internal_code=code,
            names={"es": code},
            default_price=Decimal("100.00"),
            pricing_strategy="flat",
            treatment_scope="tooth",
            dentition=dentition,
            vat_type_id=vat.id,
        )
        db.add(item)
        await db.flush()
        db.add(
            TreatmentOdontogramMapping(
                clinic_id=clinic.id,
                catalog_item_id=item.id,
                odontogram_treatment_type=chart_type,
                clinical_category=clinical,
                visualization_rules=[],
                visualization_config={},
            )
        )
        made[code] = str(item.id)
    patient = Patient(id=uuid4(), clinic_id=clinic.id, first_name="Leo", last_name="Gil")
    db.add(patient)
    await db.commit()
    made["patient"] = str(patient.id)
    return made


@pytest.mark.asyncio
async def test_the_odontogram_refuses_a_treatment_on_a_tooth_of_the_other_dentition(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    made = await _items(db_session, test_clinic)
    url = f"/api/v1/odontogram/patients/{made['patient']}/treatments"

    async def put(code: str, tooth: int):
        return await client.post(
            url,
            headers=auth_headers,
            json={
                "catalog_item_id": made[code],
                "tooth_numbers": [tooth],
                "status": "planned",
                "scope": "tooth",
            },
        )

    refused = await put("T-IMPLANT", 54)
    assert refused.status_code == 400
    assert "permanent teeth only" in refused.json()["message"]
    assert (await put("T-IMPLANT", 16)).status_code == 201

    refused = await put("T-PULPOTOMY", 46)
    assert refused.status_code == 400
    assert "primary teeth only" in refused.json()["message"]
    assert (await put("T-PULPOTOMY", 84)).status_code == 201

    assert (await put("T-FILLING", 54)).status_code == 201
    assert (await put("T-FILLING", 16)).status_code == 201


@pytest.mark.asyncio
async def test_the_bar_is_told_each_treatments_dentition(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    await _items(db_session, test_clinic)
    listed = await client.get("/api/v1/catalog/odontogram-treatments", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    by_code = {t["internal_code"]: t["dentition"] for t in listed.json()["data"]}
    assert by_code == {"T-IMPLANT": "permanent", "T-PULPOTOMY": "deciduous", "T-FILLING": "both"}


@pytest.mark.asyncio
async def test_an_admin_says_which_teeth_a_treatment_is_for(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_clinic: Clinic
) -> None:
    made = await _items(db_session, test_clinic)
    url = f"/api/v1/catalog/items/{made['T-FILLING']}"

    changed = await client.put(url, headers=auth_headers, json={"dentition": "deciduous"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["dentition"] == "deciduous"

    # Something else changes: the dentition stays.
    renamed = await client.put(url, headers=auth_headers, json={"names": {"es": "Otro"}})
    assert renamed.json()["data"]["dentition"] == "deciduous"

    refused = await client.put(url, headers=auth_headers, json={"dentition": "adult"})
    assert refused.status_code == 422
