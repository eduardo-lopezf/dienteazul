"""Specialty packs: a discipline's reference catalogue, switched per clinic.

What these pin: every recognised discipline arrives with treatments; a
clinic only gets the ones it enabled; enabling never touches what the
clinic made its own; disabling deletes nothing and enabling again brings
exactly that back; restoring only puts back what is missing or deleted
and never overwrites what the clinic has; each clinic's catalogue is its
own; and the plan templates of a discipline follow it.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.catalog.models import TreatmentCatalogItem
from app.modules.catalog.reference import BY_CODE
from app.modules.catalog.seed import (
    SPECIALTIES,
    all_specialties,
    reference_items,
    seed_catalog,
)
from app.modules.treatment_plan.models import PlanTemplate
from app.modules.treatment_plan.templates_seed import PLAN_TEMPLATES
from app.modules.treatment_plan.templates_service import PlanTemplateService

PACKS = "/api/v1/catalog/specialty-packs"


@pytest.fixture
async def clinic(db_session: AsyncSession, test_clinic: Clinic) -> UUID:
    """The id of a clinic with its baseline catalogue. The id, not the row:
    the helpers below expire the session to read what the API wrote."""
    clinic_id = test_clinic.id
    await seed_catalog(db_session, clinic_id)
    # As `clinic.created` leaves a new clinic: catalogue, then its templates.
    await PlanTemplateService.seed(db_session, clinic_id)
    await db_session.commit()
    return clinic_id


async def _item(db: AsyncSession, clinic: UUID, code: str) -> TreatmentCatalogItem | None:
    db.expire_all()
    result = await db.execute(
        select(TreatmentCatalogItem).where(
            TreatmentCatalogItem.clinic_id == clinic,
            TreatmentCatalogItem.internal_code == code,
        )
    )
    return result.scalar_one_or_none()


async def _templates(db: AsyncSession, clinic: UUID) -> dict[str, PlanTemplate]:
    db.expire_all()
    result = await db.execute(
        select(PlanTemplate).where(PlanTemplate.clinic_id == clinic, PlanTemplate.key.is_not(None))
    )
    return {template.key: template for template in result.scalars()}


def test_every_recognised_discipline_comes_with_a_catalogue() -> None:
    """A discipline offered with nothing behind it is worse than not offering it."""
    assert len(all_specialties()) == 17
    for spec in all_specialties():
        assert len(reference_items(spec["key"])) >= 9, spec["key"]
    # Orthodontics is the full range, not a handful.
    assert len(reference_items("ortodoncia")) >= 45
    # And every template names a discipline that exists.
    keys = {spec["key"] for spec in all_specialties()}
    assert {template["specialty"] for template in PLAN_TEMPLATES} <= keys


@pytest.mark.asyncio
async def test_a_clinic_starts_with_the_baseline_and_none_of_the_other_packs(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    packs = {p["key"]: p for p in (await client.get(PACKS, headers=auth_headers)).json()["data"]}
    assert len(packs) == 17
    assert packs["ortodoncia"]["enabled"] and packs["general"]["enabled"]
    assert packs["ortodoncia"]["installed_count"] == packs["ortodoncia"]["reference_count"]
    assert not packs["radiologia"]["enabled"]
    # A radiograph filed under Diagnóstico is Radiology's, not every clinic's.
    assert await _item(db_session, clinic, "RX-BITEWING") is None
    assert await _item(db_session, clinic, "DOF-SPLINT-STAB") is None


@pytest.mark.asyncio
async def test_enabling_adds_the_reference_and_leaves_the_clinics_own_alone(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    # The clinic already made the shared panoramic its own.
    shared = await _item(db_session, clinic, "DX-RXPAN")
    shared.default_price = Decimal("777.00")
    await db_session.commit()

    enabled = await client.post(f"{PACKS}/radiologia/enable", headers=auth_headers)
    assert enabled.status_code == 200, enabled.text
    pack = enabled.json()["data"]
    assert pack["enabled"] and pack["installed_count"] == pack["reference_count"]
    assert pack["customised_count"] == 1

    assert (await _item(db_session, clinic, "RX-BITEWING")).is_active
    assert (await _item(db_session, clinic, "DX-RXPAN")).default_price == Decimal("777.00")
    # Its plan template arrived with it.
    templates = await _templates(db_session, clinic)
    assert "imaging_study" in templates
    # The baseline brought the full orthodontic set, not one generic shape.
    assert {"ortho_fixed", "ortho_aligners", "ortho_interceptive"} <= set(templates)

    assert pack["missing_count"] == 0
    # Again changes nothing.
    again = await client.post(f"{PACKS}/radiologia/enable", headers=auth_headers)
    assert again.json()["data"]["installed_count"] == pack["installed_count"]


@pytest.mark.asyncio
async def test_disabling_deletes_nothing_and_enabling_brings_it_back(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    # Retired by hand before: not the pack's to bring back.
    retired = await _item(db_session, clinic, "ORTO-LINGUAL")
    retired.is_active = False
    await db_session.commit()

    off = await client.post(f"{PACKS}/ortodoncia/disable", headers=auth_headers)
    assert off.status_code == 200, off.text
    # What stays belongs first to a discipline that is still enabled.
    shared = [
        t
        for owner, t in BY_CODE.values()
        if owner != "ortodoncia" and "ortodoncia" in t.specialties
    ]
    assert off.json()["data"]["enabled"] is False
    assert off.json()["data"]["installed_count"] == len(shared)

    braces = await _item(db_session, clinic, "ORTO-METAL")
    assert braces is not None and not braces.is_active and braces.disabled_by_specialty
    # A general treatment is untouched.
    assert (await _item(db_session, clinic, "DX-VISIT")).is_active
    assert not (await _templates(db_session, clinic))["ortho_fixed"].is_active

    on = await client.post(f"{PACKS}/ortodoncia/enable", headers=auth_headers)
    assert on.json()["data"]["enabled"] is True
    assert (await _item(db_session, clinic, "ORTO-METAL")).is_active
    assert not (await _item(db_session, clinic, "ORTO-LINGUAL")).is_active
    assert (await _templates(db_session, clinic))["ortho_fixed"].is_active


@pytest.mark.asyncio
async def test_a_treatment_two_disciplines_share_stays_while_one_is_enabled(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    await client.post(f"{PACKS}/radiologia/enable", headers=auth_headers)
    await client.post(f"{PACKS}/radiologia/disable", headers=auth_headers)

    # General dentistry still claims the panoramic; nothing claims the bitewing.
    assert (await _item(db_session, clinic, "DX-RXPAN")).is_active
    assert not (await _item(db_session, clinic, "RX-BITEWING")).is_active


@pytest.mark.asyncio
async def test_restoring_puts_back_what_is_missing_and_overwrites_nothing(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    braces = await _item(db_session, clinic, "ORTO-METAL")
    category_id = braces.category_id
    braces.default_price = Decimal("9999.00")
    braces.names = {"es": "Brackets de la casa"}
    own = TreatmentCatalogItem(
        clinic_id=clinic,
        category_id=category_id,
        internal_code="MIO-ORTO",
        names={"es": "Mi tratamiento de ortodoncia"},
        default_price=Decimal("50.00"),
        is_system=False,
    )
    db_session.add(own)
    await db_session.commit()
    # A reference treatment the clinic deleted, after editing it.
    [(_, other)] = [
        (c, i)
        for c, i in reference_items("ortodoncia")
        if i["internal_code"] not in ("ORTO-METAL",)
    ][:1]
    deleted = await _item(db_session, clinic, other["internal_code"])
    deleted.default_price = Decimal("123.00")
    deleted.is_active = False
    deleted.deleted_at = datetime.now(UTC)
    await db_session.commit()
    templates = await _templates(db_session, clinic)
    ortho_keys = {t["key"] for t in PLAN_TEMPLATES if t["specialty"] == "ortodoncia"}
    ortho = next(t for t in templates.values() if t.key in ortho_keys)
    ortho.name = "Mi plantilla de ortodoncia"
    await db_session.commit()

    restored = await client.post(f"{PACKS}/ortodoncia/restore", headers=auth_headers)
    assert restored.status_code == 200, restored.text

    # What the clinic edited stays as it is.
    braces = await _item(db_session, clinic, "ORTO-METAL")
    assert braces.default_price == Decimal("9999.00")
    assert braces.names["es"] == "Brackets de la casa"
    # What it created is untouched.
    mine = await _item(db_session, clinic, "MIO-ORTO")
    assert mine is not None and mine.default_price == Decimal("50.00")
    # What it deleted comes back, as it left it.
    back = await _item(db_session, clinic, other["internal_code"])
    assert back.deleted_at is None and back.is_active
    assert back.default_price == Decimal("123.00")
    # Its edited plan template is not overwritten.
    templates = await _templates(db_session, clinic)
    assert templates[ortho.key].name == "Mi plantilla de ortodoncia"


@pytest.mark.asyncio
async def test_an_admin_edits_the_clinics_own_copy_and_another_clinic_never_sees_it(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    other_clinic = Clinic(
        id=uuid4(), name="Otra", tax_id="B00000000", settings={}, account_tier="clinic"
    )
    db_session.add(other_clinic)
    await db_session.flush()
    await seed_catalog(db_session, other_clinic.id)
    await db_session.commit()
    other_id = other_clinic.id
    theirs = await _item(db_session, other_id, "ORTO-METAL")
    their_id, their_price = theirs.id, theirs.default_price
    my_id = (await _item(db_session, clinic, "ORTO-METAL")).id
    assert their_id != my_id, "each clinic has its own copy of the reference"

    # The administrator edits the clinic's copy…
    edited = await client.put(
        f"/api/v1/catalog/items/{my_id}",
        json={"default_price": "777.00", "names": {"es": "Brackets A"}},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    # …and the other clinic's copy, and the reference file, are unchanged.
    theirs = await _item(db_session, other_id, "ORTO-METAL")
    assert theirs.default_price == their_price
    [reference] = [
        i for _, i in reference_items("ortodoncia") if i["internal_code"] == "ORTO-METAL"
    ]
    assert reference["names"]["es"] != "Brackets A"

    # The other clinic's catalogue is neither listed, read nor written.
    listed = await client.get(
        "/api/v1/catalog/items", params={"search": "ORTO-METAL"}, headers=auth_headers
    )
    assert str(their_id) not in {row["id"] for row in listed.json()["data"]}
    assert str(my_id) in {row["id"] for row in listed.json()["data"]}
    assert (
        await client.get(f"/api/v1/catalog/items/{their_id}", headers=auth_headers)
    ).status_code == 404
    refused = await client.put(
        f"/api/v1/catalog/items/{their_id}",
        json={"default_price": "1.00"},
        headers=auth_headers,
    )
    assert refused.status_code == 404


@pytest.mark.asyncio
async def test_a_disabled_discipline_is_not_restored_through_the_side_door(
    client: AsyncClient, auth_headers: dict, clinic: UUID
) -> None:
    refused = await client.post(f"{PACKS}/radiologia/restore", headers=auth_headers)
    assert refused.status_code == 409, refused.text
    unknown = await client.post(f"{PACKS}/astrologia/enable", headers=auth_headers)
    assert unknown.status_code == 404, unknown.text


@pytest.mark.asyncio
async def test_a_reference_that_grew_is_added_without_touching_the_clinics_catalogue(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    """A clinic seeded before the reference grew lacks the new treatments;
    enabling again adds exactly those."""
    await db_session.delete(await _item(db_session, clinic, "ORTO-STUDY"))
    await db_session.commit()
    braces = await _item(db_session, clinic, "ORTO-METAL")
    braces.default_price = Decimal("9999.00")
    await db_session.commit()

    packs = {p["key"]: p for p in (await client.get(PACKS, headers=auth_headers)).json()["data"]}
    assert packs["ortodoncia"]["missing_count"] == 1

    completed = await client.post(f"{PACKS}/ortodoncia/enable", headers=auth_headers)
    assert completed.json()["data"]["missing_count"] == 0
    assert await _item(db_session, clinic, "ORTO-STUDY") is not None
    assert (await _item(db_session, clinic, "ORTO-METAL")).default_price == Decimal("9999.00")


@pytest.mark.asyncio
async def test_a_discipline_reads_by_subarea_with_where_the_clinic_stands(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    braces = await _item(db_session, clinic, "ORTO-METAL")
    reference_price = braces.default_price
    braces.default_price = Decimal("9999.00")
    await db_session.commit()

    detail = (await client.get(f"{PACKS}/ortodoncia", headers=auth_headers)).json()["data"]
    assert detail["enabled"] is True and detail["customised_count"] == 1
    # In reading order, from the study to retention.
    order = [group["key"] for group in detail["subareas"]]
    assert order[0] == "diagnostico" and order[-1] == "retencion"
    listed = {t["code"]: t for group in detail["subareas"] for t in group["treatments"]}
    shared = [t for group in detail["shared"] for t in group["treatments"]]
    assert len(listed) + len(shared) == detail["reference_count"]
    assert listed["ORTO-METAL"]["customised"] is True
    assert Decimal(listed["ORTO-METAL"]["clinic_price"]) == Decimal("9999.00")
    assert Decimal(listed["ORTO-METAL"]["reference_price"]) == reference_price
    assert listed["ORTO-CERAM"]["customised"] is False
    assert {t["state"] for t in listed.values()} == {"active"}
    # Surgery's file holds the exposure of an impacted tooth; orthodontics uses it.
    assert "cirugia" in {group["specialty_key"] for group in detail["shared"]}

    # A discipline the clinic has not enabled shows its reference as missing,
    # and apart what another discipline's file shares with it.
    radiology = (await client.get(f"{PACKS}/radiologia", headers=auth_headers)).json()["data"]
    own = [t for group in radiology["subareas"] for t in group["treatments"]]
    assert {t["state"] for t in own} == {"missing"}
    assert all(t["clinic_price"] is None for t in own)
    [shared] = radiology["shared"]
    assert shared["specialty_key"] == "general"
    assert {t["code"]: t["state"] for t in shared["treatments"]} == {
        "DX-RXPA": "active",
        "DX-RXPAN": "active",
        "DX-CBCT": "active",
    }

    unknown = await client.get(f"{PACKS}/astrologia", headers=auth_headers)
    assert unknown.status_code == 404


def test_every_discipline_brings_plan_templates_a_clinic_can_fully_use() -> None:
    keys = [template["key"] for template in PLAN_TEMPLATES]
    assert len(keys) == len(set(keys))
    assert {template["specialty"] for template in PLAN_TEMPLATES} == {
        spec["key"] for spec in all_specialties()
    }
    baseline = {spec["key"] for spec in SPECIALTIES}
    for template in PLAN_TEMPLATES:
        codes = [item["code"] for item in template["items"]]
        assert len(codes) >= 2 and len(codes) == len(set(codes)), template["key"]
        for code in codes:
            assert code in BY_CODE, (template["key"], code)
            # In the catalogue of a clinic that enabled the discipline: the
            # discipline's own, or one every clinic starts with. A line from
            # some other optional pack would be dropped on most clinics.
            claimed = set(BY_CODE[code][1].specialties)
            assert claimed & (baseline | {template["specialty"]}), (template["key"], code)


@pytest.mark.asyncio
async def test_a_template_says_which_discipline_it_belongs_to(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, clinic: UUID
) -> None:
    braces = await _item(db_session, clinic, "ORTO-METAL")
    own = await client.post(
        "/api/v1/treatment_plan/plan-templates",
        json={"name": "La nuestra", "items": [{"catalog_item_id": str(braces.id)}]},
        headers=auth_headers,
    )
    assert own.status_code == 201, own.text
    # Saved by the clinic: it belongs to no discipline.
    assert own.json()["data"]["specialty"] is None

    listed = await client.get("/api/v1/treatment_plan/plan-templates", headers=auth_headers)
    by_key = {t["key"]: t for t in listed.json()["data"] if t["key"]}
    assert by_key["ortho_fixed"]["specialty"]["key"] == "ortodoncia"
    assert by_key["ortho_fixed"]["specialty"]["names"]["es"] == "Ortodoncia"
    assert by_key["single_crown"]["specialty"]["key"] == "rehabilitacion"
    assert all(t["specialty"] for t in by_key.values())


@pytest.mark.asyncio
async def test_a_search_hit_is_shown_under_one_discipline(
    client: AsyncClient, auth_headers: dict, clinic: UUID
) -> None:
    async def hits(query: str) -> dict[str, dict]:
        found = await client.get(
            f"/api/v1/catalog/items/search?q={query}&limit=50", headers=auth_headers
        )
        assert found.status_code == 200, found.text
        return {item["internal_code"]: item for item in found.json()["data"]}

    assert (await hits("ORTO-METAL"))["ORTO-METAL"]["specialty"]["names"]["es"] == "Ortodoncia"
    # Surgery and implantology both claim it; implantology's file holds it.
    implant = (await hits("SURG-IMP-TI"))["SURG-IMP-TI"]
    assert implant["specialty"]["names"]["es"] == "Implantología"

    # With its own discipline switched off it falls to the other that claims it.
    await client.post(f"{PACKS}/implantologia/disable", headers=auth_headers)
    implant = (await hits("SURG-IMP-TI"))["SURG-IMP-TI"]
    assert implant["specialty"]["names"]["es"] == "Cirugía Oral y Maxilofacial"
