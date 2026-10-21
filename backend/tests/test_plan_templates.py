"""Plan templates: the shape of a plan, applied to a patient.

The interesting behaviour is the apply rule, because it is the one thing a
dentist has to be able to predict: every per-tooth treatment is created once
per tooth supplied, and everything whole-mouth is created once.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.modules.catalog.models import (
    TreatmentCatalogItem,
    TreatmentCategory,
    TreatmentOdontogramMapping,
    VatType,
)

BASE = "/api/v1/treatment_plan"


async def _clinic_and_patient(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict[str, str]
) -> dict:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]

    clinic = Clinic(
        id=uuid4(),
        name="Template Clinic",
        tax_id="B22222222",
        address={"street": "a", "city": "b"},
        settings={"slot_duration_min": 15},
        account_tier="clinic",
    )
    db_session.add(clinic)
    await db_session.flush()
    db_session.add(
        ClinicMembership(id=uuid4(), user_id=user_id, clinic_id=clinic.id, role="dentist")
    )
    await db_session.commit()

    patient = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "Ana", "last_name": "Ruiz", "phone": "+34666111222"},
    )
    return {
        "clinic_id": clinic.id,
        "user_id": user_id,
        "patient_id": patient.json()["data"]["id"],
    }


async def _catalog(db_session: AsyncSession, clinic_id) -> dict[str, str]:
    """A per-tooth item with a chart mapping, and two without one.

    The unmapped pair is the realistic case, not an edge case: over half a
    seeded dental catalog (cleanings, radiographs, dentures) draws nothing on
    a tooth chart.
    """
    vat = VatType(clinic_id=clinic_id, names={"es": "Exento"}, rate=0.0, is_default=True)
    db_session.add(vat)
    await db_session.flush()
    category = TreatmentCategory(clinic_id=clinic_id, key="mix", names={"es": "M"}, is_system=True)
    db_session.add(category)
    await db_session.flush()

    def item(code: str, scope: str, phase: str) -> TreatmentCatalogItem:
        return TreatmentCatalogItem(
            clinic_id=clinic_id,
            category_id=category.id,
            internal_code=code,
            names={"es": code},
            default_price=Decimal("100.00"),
            pricing_strategy="flat",
            treatment_scope=scope,
            default_phase=phase,
            vat_type_id=vat.id,
        )

    crown = item("T-CROWN", "tooth", "rehabilitacion")
    cleaning = item("T-CLEAN", "global_mouth", "preventivo")
    retainer = item("T-RETAINER", "global_arch", "mantenimiento")
    db_session.add_all([crown, cleaning, retainer])
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
    return {
        "crown": str(crown.id),
        "cleaning": str(cleaning.id),
        "retainer": str(retainer.id),
    }


@pytest.fixture
async def setup(
    db_session: AsyncSession, auth_headers: dict[str, str], client: AsyncClient
) -> dict:
    ctx = await _clinic_and_patient(db_session, client, auth_headers)
    ctx["catalog"] = await _catalog(db_session, ctx["clinic_id"])
    return ctx


async def _plan(client: AsyncClient, auth_headers: dict, setup: dict) -> str:
    r = await client.post(
        f"{BASE}/treatment-plans",
        headers=auth_headers,
        json={"patient_id": setup["patient_id"], "title": "Plan"},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def _template(client: AsyncClient, auth_headers: dict, items: list[dict]) -> str:
    r = await client.post(
        f"{BASE}/plan-templates",
        headers=auth_headers,
        json={"name": "Shape", "items": items},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


@pytest.mark.asyncio
async def test_whole_mouth_template_needs_no_teeth(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["cleaning"]}]
    )

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": []},
    )
    assert r.status_code == 201, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["treatment"]["scope"] == "global_mouth"
    # Seeded from the catalog item's default_phase.
    assert items[0]["phase"] == "preventivo"


@pytest.mark.asyncio
async def test_per_tooth_template_creates_one_item_per_tooth(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["crown"]}]
    )

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": [16, 26, 36]},
    )
    assert r.status_code == 201, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 3
    teeth = sorted(i["treatment"]["teeth"][0]["tooth_number"] for i in items)
    assert teeth == [16, 26, 36]


@pytest.mark.asyncio
async def test_per_tooth_template_without_teeth_says_which_treatments(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["crown"]}]
    )

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": []},
    )
    assert r.status_code == 422
    # The blocked treatment is named, so the UI can ask for the right thing
    # instead of showing a bare validation error.
    assert "T-CROWN" in r.text


@pytest.mark.asyncio
async def test_arch_item_expands_to_both_arches_when_no_teeth(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["retainer"]}]
    )

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": []},
    )
    assert r.status_code == 201, r.text
    arches = sorted(i["treatment"]["arch"] for i in r.json()["data"]["items"])
    assert arches == ["lower", "upper"]


@pytest.mark.asyncio
async def test_unmapped_catalog_item_is_plannable(client, auth_headers, setup):
    """A cleaning has no chart mapping and must still reach a plan.

    Requiring one made over half a real catalog impossible to plan at all.
    """
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["cleaning"]}]
    )

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": []},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["items"][0]["treatment"]["clinical_type"] == "procedure"


@pytest.mark.asyncio
async def test_template_phase_overrides_the_catalog_default(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client,
        auth_headers,
        [{"catalog_item_id": setup["catalog"]["crown"], "phase": "urgencia"}],
    )

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": [16]},
    )
    assert r.status_code == 201, r.text
    # The catalog says rehabilitacion; this template says otherwise.
    assert r.json()["data"]["items"][0]["phase"] == "urgencia"


@pytest.mark.asyncio
async def test_save_plan_as_template_drops_teeth(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)
    source = await _template(client, auth_headers, [{"catalog_item_id": setup["catalog"]["crown"]}])
    await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": source, "tooth_numbers": [16, 26]},
    )

    r = await client.post(
        f"{BASE}/plan-templates/from-plan/{plan_id}",
        headers=auth_headers,
        json={"name": "Saved shape"},
    )
    assert r.status_code == 201, r.text
    saved = r.json()["data"]
    # Two plan items on two teeth collapse to one template line: a template
    # carries the treatment, never the teeth.
    assert len(saved["items"]) == 1
    assert saved["items"][0]["catalog_item_id"] == setup["catalog"]["crown"]
    assert saved["key"] is None


@pytest.mark.asyncio
async def test_template_rejects_a_catalog_item_from_another_clinic(client, auth_headers, setup):
    r = await client.post(
        f"{BASE}/plan-templates",
        headers=auth_headers,
        json={"name": "Cross tenant", "items": [{"catalog_item_id": str(uuid4())}]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_hides_the_template_without_dropping_it(client, auth_headers, setup):
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["cleaning"]}]
    )

    assert (
        await client.delete(f"{BASE}/plan-templates/{template_id}", headers=auth_headers)
    ).status_code == 204

    listed = await client.get(f"{BASE}/plan-templates", headers=auth_headers)
    assert all(t["id"] != template_id for t in listed.json()["data"])

    with_inactive = await client.get(
        f"{BASE}/plan-templates?include_inactive=true", headers=auth_headers
    )
    assert any(t["id"] == template_id for t in with_inactive.json()["data"])


# ---------------------------------------------------------------------------
# Proposals from the chart
# ---------------------------------------------------------------------------


async def _finding(
    client: AsyncClient, auth_headers: dict, setup: dict, clinical_type: str, tooth: int
) -> str:
    """Chart a finding the way diagnosis mode does: performed, no catalog link."""
    r = await client.post(
        f"/api/v1/odontogram/patients/{setup['patient_id']}/treatments",
        headers=auth_headers,
        json={
            "clinical_type": clinical_type,
            "tooth_numbers": [tooth],
            "status": "performed",
            "scope": "tooth",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def _suggestable_item(db_session: AsyncSession, setup: dict, code: str) -> None:
    """Put a code the suggestion table knows into this clinic's catalog.

    `SUGGESTIONS` resolves by `internal_code`, so nothing is proposed until
    the clinic actually offers the treatment.
    """
    vat = (
        (await db_session.execute(select(VatType).where(VatType.clinic_id == setup["clinic_id"])))
        .scalars()
        .first()
    )
    category = (
        (
            await db_session.execute(
                select(TreatmentCategory).where(TreatmentCategory.clinic_id == setup["clinic_id"])
            )
        )
        .scalars()
        .first()
    )
    db_session.add(
        TreatmentCatalogItem(
            clinic_id=setup["clinic_id"],
            category_id=category.id,
            internal_code=code,
            names={"es": "Obturación composite"},
            default_price=Decimal("60.00"),
            pricing_strategy="flat",
            treatment_scope="tooth",
            default_phase="estabilizacion",
            vat_type_id=vat.id,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_findings_are_proposed_with_a_suggested_treatment(
    client, auth_headers, setup, db_session
):
    await _suggestable_item(db_session, setup, "REST-COMP")

    plan_id = await _plan(client, auth_headers, setup)
    await _finding(client, auth_headers, setup, "caries", 16)

    r = await client.get(f"{BASE}/treatment-plans/{plan_id}/proposals", headers=auth_headers)
    assert r.status_code == 200, r.text
    proposals = r.json()["data"]
    assert len(proposals) == 1
    assert proposals[0]["clinical_type"] == "caries"
    assert proposals[0]["tooth_number"] == 16
    assert proposals[0]["suggested_catalog_item"]["internal_code"] == "REST-COMP"

    accepted = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/proposals",
        headers=auth_headers,
        json={"finding_ids": [proposals[0]["finding_id"]]},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["data"][0]["treatment"]["teeth"][0]["tooth_number"] == 16

    # The tooth now has planned work, so the finding stops being proposed —
    # and the finding itself is untouched, because the caries is still there.
    again = await client.get(f"{BASE}/treatment-plans/{plan_id}/proposals", headers=auth_headers)
    assert again.json()["data"] == []


@pytest.mark.asyncio
async def test_finding_without_a_catalog_match_is_listed_but_not_actionable(
    client, auth_headers, setup
):
    """The clinic has no REST-COMP, so nothing can be proposed for a caries.

    It is still listed: a dentist wants to know the finding is unaddressed
    even when the app has nothing to offer for it.
    """
    plan_id = await _plan(client, auth_headers, setup)
    await _finding(client, auth_headers, setup, "caries", 16)

    r = await client.get(f"{BASE}/treatment-plans/{plan_id}/proposals", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1
    assert r.json()["data"][0]["suggested_catalog_item"] is None


@pytest.mark.asyncio
async def test_planned_work_is_not_a_finding(client, auth_headers, setup):
    """A crown already planned on 16 is not a finding and must not be proposed."""
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["crown"]}]
    )
    await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": [16]},
    )

    r = await client.get(f"{BASE}/treatment-plans/{plan_id}/proposals", headers=auth_headers)
    assert r.json()["data"] == []


# ---------------------------------------------------------------------------
# Optional lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optional_line_can_be_excluded(client, auth_headers, setup):
    """The orthodontics of an orthognathic case: the clinic may refer it out."""
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client,
        auth_headers,
        [
            {"catalog_item_id": setup["catalog"]["cleaning"]},
            {"catalog_item_id": setup["catalog"]["retainer"], "is_optional": True},
        ],
    )
    listed = await client.get(f"{BASE}/plan-templates", headers=auth_headers)
    template = next(t for t in listed.json()["data"] if t["id"] == template_id)
    optional = next(i for i in template["items"] if i["is_optional"])

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={
            "template_id": template_id,
            "tooth_numbers": [],
            "excluded_template_item_ids": [optional["id"]],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert len(body["items"]) == 1
    assert body["items"][0]["treatment"]["catalog_item"]["internal_code"] == "T-CLEAN"
    assert body["skipped"] == []


@pytest.mark.asyncio
async def test_required_line_cannot_be_excluded(client, auth_headers, setup):
    """A template whose required steps can be dropped is not a shape any more."""
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["cleaning"]}]
    )
    listed = await client.get(f"{BASE}/plan-templates", headers=auth_headers)
    template = next(t for t in listed.json()["data"] if t["id"] == template_id)

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={
            "template_id": template_id,
            "tooth_numbers": [],
            "excluded_template_item_ids": [template["items"][0]["id"]],
        },
    )
    assert r.status_code == 400
    assert "T-CLEAN" in r.text


@pytest.mark.asyncio
async def test_excluding_the_only_per_tooth_line_stops_asking_for_teeth(
    client, auth_headers, setup
):
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client,
        auth_headers,
        [
            {"catalog_item_id": setup["catalog"]["cleaning"]},
            {"catalog_item_id": setup["catalog"]["crown"], "is_optional": True},
        ],
    )
    listed = await client.get(f"{BASE}/plan-templates", headers=auth_headers)
    template = next(t for t in listed.json()["data"] if t["id"] == template_id)
    optional = next(i for i in template["items"] if i["is_optional"])

    # With the crown in, no teeth is a 422; with it out, it applies cleanly.
    blocked = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": []},
    )
    assert blocked.status_code == 422

    ok = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={
            "template_id": template_id,
            "tooth_numbers": [],
            "excluded_template_item_ids": [optional["id"]],
        },
    )
    assert ok.status_code == 201, ok.text
    assert len(ok.json()["data"]["items"]) == 1


@pytest.mark.asyncio
async def test_retired_treatment_is_reported_not_swallowed(client, auth_headers, setup, db_session):
    """A clinic that stops offering a treatment still gets the rest of the plan.

    Silently one treatment short is worse than saying so.
    """
    plan_id = await _plan(client, auth_headers, setup)
    template_id = await _template(
        client,
        auth_headers,
        [
            {"catalog_item_id": setup["catalog"]["cleaning"]},
            {"catalog_item_id": setup["catalog"]["retainer"]},
        ],
    )

    retainer = (
        await db_session.execute(
            select(TreatmentCatalogItem).where(
                TreatmentCatalogItem.id == UUID(setup["catalog"]["retainer"])
            )
        )
    ).scalar_one()
    retainer.is_active = False
    await db_session.commit()

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/apply-template",
        headers=auth_headers,
        json={"template_id": template_id, "tooth_numbers": []},
    )
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert len(body["items"]) == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["name"] == "T-RETAINER"
    assert body["skipped"][0]["reason"] == "not_in_catalog"


@pytest.mark.asyncio
async def test_update_answers_with_the_lines_it_just_wrote(client, auth_headers, setup):
    """A PUT that reports the previous line-up is worse than no response."""
    template_id = await _template(
        client, auth_headers, [{"catalog_item_id": setup["catalog"]["cleaning"]}]
    )
    r = await client.put(
        f"{BASE}/plan-templates/{template_id}",
        headers=auth_headers,
        json={
            "items": [
                {"catalog_item_id": setup["catalog"]["cleaning"]},
                {"catalog_item_id": setup["catalog"]["retainer"], "is_optional": True},
            ]
        },
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 2
    assert [i["is_optional"] for i in items] == [False, True]


# ---------------------------------------------------------------------------
# Treatments picked one by one
#
# The other half of "start from a template". A plan is often a known shape
# plus the two treatments this patient happens to need, and those two used to
# be addable only after the plan existed, from the chart — which is why the
# create form on a tablet sent everyone to the odontogram.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_line_carries_its_own_teeth(client, auth_headers, setup):
    """A plan drawn on a chart is per tooth, not one tooth list for everything."""
    plan_id = await _plan(client, auth_headers, setup)

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/catalog-items",
        headers=auth_headers,
        json={
            "lines": [
                {"catalog_item_id": setup["catalog"]["cleaning"], "tooth_numbers": []},
                {"catalog_item_id": setup["catalog"]["crown"], "tooth_numbers": [16]},
                {"catalog_item_id": setup["catalog"]["crown"], "tooth_numbers": [24, 25]},
            ]
        },
    )
    assert r.status_code == 201, r.text
    items = r.json()["data"]["items"]
    # The cleaning once, the first crown on 16, the second crown once per tooth.
    assert len(items) == 4
    assert items[0]["treatment"]["scope"] == "global_mouth"
    assert [i["treatment"]["teeth"][0]["tooth_number"] for i in items[1:]] == [16, 24, 25]
    # Phase comes from the catalog item; there is no template to override it.
    assert items[0]["phase"] == "preventivo"


@pytest.mark.asyncio
async def test_a_line_can_name_the_surfaces_it_treats(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/catalog-items",
        headers=auth_headers,
        json={
            "lines": [
                {
                    "catalog_item_id": setup["catalog"]["crown"],
                    "tooth_numbers": [16],
                    "surfaces": ["O", "M"],
                    "notes": "Cara distal respetada",
                }
            ]
        },
    )
    assert r.status_code == 201, r.text
    item = r.json()["data"]["items"][0]
    assert sorted(item["treatment"]["teeth"][0]["surfaces"]) == ["M", "O"]


@pytest.mark.asyncio
async def test_a_line_without_its_tooth_says_which_treatment(client, auth_headers, setup):
    plan_id = await _plan(client, auth_headers, setup)

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/catalog-items",
        headers=auth_headers,
        json={
            "lines": [
                {"catalog_item_id": setup["catalog"]["cleaning"], "tooth_numbers": []},
                {"catalog_item_id": setup["catalog"]["crown"], "tooth_numbers": []},
            ]
        },
    )
    assert r.status_code == 422
    # Only the per-tooth one is named, and nothing at all is created.
    assert "T-CROWN" in r.text
    assert "T-CLEAN" not in r.text


@pytest.mark.asyncio
async def test_a_line_from_another_clinic_is_skipped_not_applied(client, auth_headers, setup):
    """Nothing is created for it, and the caller is told — never silently."""
    plan_id = await _plan(client, auth_headers, setup)

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/catalog-items",
        headers=auth_headers,
        json={
            "lines": [
                {"catalog_item_id": setup["catalog"]["cleaning"], "tooth_numbers": []},
                {"catalog_item_id": str(uuid4()), "tooth_numbers": []},
            ]
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert len(body["items"]) == 1
    assert [s["reason"] for s in body["skipped"]] == ["not_in_catalog"]


@pytest.mark.asyncio
async def test_a_patient_with_no_plan_still_has_proposals(client, auth_headers, setup, db_session):
    """The builder's case: findings read before any plan exists.

    `/treatment-plans/{plan_id}/proposals` cannot answer here — there is no
    plan until the dentist presses *Crear* — and that is exactly the moment
    the chart's findings are worth something, because otherwise they are
    redrawn by hand.
    """
    await _suggestable_item(db_session, setup, "REST-COMP")
    await _finding(client, auth_headers, setup, "caries", 16)

    patient_id = setup["patient_id"]
    r = await client.get(
        f"{BASE}/treatment-plans/patient/{patient_id}/proposals", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    proposals = r.json()["data"]

    assert len(proposals) == 1
    assert proposals[0]["clinical_type"] == "caries"
    assert proposals[0]["tooth_number"] == 16
    assert proposals[0]["suggested_catalog_item"]["internal_code"] == "REST-COMP"


@pytest.mark.asyncio
async def test_a_tooth_already_planned_is_not_proposed_again(
    client, auth_headers, setup, db_session
):
    """The same coarse rule the plan-scoped endpoint applies.

    Splitting the read out must not have quietly dropped it: a finding on a
    tooth that already carries planned work is left out, because proposing it
    again is how a plan grows a duplicate line.
    """
    await _suggestable_item(db_session, setup, "REST-COMP")
    await _finding(client, auth_headers, setup, "caries", 16)

    patient_id = setup["patient_id"]
    before = await client.get(
        f"{BASE}/treatment-plans/patient/{patient_id}/proposals", headers=auth_headers
    )
    assert len(before.json()["data"]) == 1

    plan_id = await _plan(client, auth_headers, setup)
    accepted = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/proposals",
        headers=auth_headers,
        json={"finding_ids": [before.json()["data"][0]["finding_id"]]},
    )
    assert accepted.status_code == 201, accepted.text

    after = await client.get(
        f"{BASE}/treatment-plans/patient/{patient_id}/proposals", headers=auth_headers
    )
    assert after.json()["data"] == []


@pytest.mark.asyncio
async def test_a_dismissed_finding_is_not_proposed_to_that_plan_again(
    client, auth_headers, setup, db_session
):
    """Deleting a seeded line is a judgement, and it has to stick.

    The builder seeds its draft from the chart, so deleting one of those lines
    means *this plan is not for that caries*. Without recording it the plan's
    own proposals list offers the finding straight back and asks the dentist
    the same question twice.
    """
    await _suggestable_item(db_session, setup, "REST-COMP")
    finding_id = await _finding(client, auth_headers, setup, "caries", 16)
    plan_id = await _plan(client, auth_headers, setup)

    offered = await client.get(f"{BASE}/treatment-plans/{plan_id}/proposals", headers=auth_headers)
    assert [p["finding_id"] for p in offered.json()["data"]] == [finding_id]

    dismissed = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/dismissed-findings",
        headers=auth_headers,
        json={"finding_ids": [finding_id]},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["data"]["dismissed"] == 1

    after = await client.get(f"{BASE}/treatment-plans/{plan_id}/proposals", headers=auth_headers)
    assert after.json()["data"] == []

    # Twice is one decision, not two rows.
    again = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/dismissed-findings",
        headers=auth_headers,
        json={"finding_ids": [finding_id]},
    )
    assert again.json()["data"]["dismissed"] == 0


@pytest.mark.asyncio
async def test_dismissing_binds_to_the_plan_not_to_the_finding(
    client, auth_headers, setup, db_session
):
    """The guarantee that makes dismissing safe.

    A dismissal says only that *this* plan does not answer the finding. The
    chart keeps showing the caries, and the patient's next plan proposes it
    again — a decision about one plan must never become a decision to leave a
    tooth alone forever.
    """
    await _suggestable_item(db_session, setup, "REST-COMP")
    finding_id = await _finding(client, auth_headers, setup, "caries", 16)

    first_plan = await _plan(client, auth_headers, setup)
    await client.post(
        f"{BASE}/treatment-plans/{first_plan}/dismissed-findings",
        headers=auth_headers,
        json={"finding_ids": [finding_id]},
    )

    second_plan = await _plan(client, auth_headers, setup)
    offered = await client.get(
        f"{BASE}/treatment-plans/{second_plan}/proposals", headers=auth_headers
    )
    assert [p["finding_id"] for p in offered.json()["data"]] == [finding_id]

    # And the builder, which knows no plan at all, still offers it.
    patient_id = setup["patient_id"]
    fresh = await client.get(
        f"{BASE}/treatment-plans/patient/{patient_id}/proposals", headers=auth_headers
    )
    assert [p["finding_id"] for p in fresh.json()["data"]] == [finding_id]


# ---------------------------------------------------------------------------
# Dentition: a treatment for primary teeth is not planned on a permanent one
# ---------------------------------------------------------------------------


async def _dentition_item(
    db_session: AsyncSession, setup: dict, code: str, dentition: str, scope: str = "tooth"
) -> str:
    category = (
        (
            await db_session.execute(
                select(TreatmentCategory).where(TreatmentCategory.clinic_id == setup["clinic_id"])
            )
        )
        .scalars()
        .first()
    )
    item = TreatmentCatalogItem(
        clinic_id=setup["clinic_id"],
        category_id=category.id,
        internal_code=code,
        names={"es": code},
        default_price=Decimal("80.00"),
        pricing_strategy="flat",
        treatment_scope=scope,
        default_phase="estabilizacion",
        dentition=dentition,
    )
    db_session.add(item)
    await db_session.commit()
    return str(item.id)


@pytest.mark.asyncio
async def test_a_line_goes_on_the_teeth_its_dentition_fits(client, auth_headers, setup, db_session):
    """A paediatric pulpotomy drawn on 84 and 16 lands on 84; 16 is reported."""
    pulpotomy = await _dentition_item(db_session, setup, "PED-PULPOTOMY", "deciduous")
    splint = await _dentition_item(db_session, setup, "T-BRIDGE", "permanent", "multi_tooth")
    plan_id = await _plan(client, auth_headers, setup)

    r = await client.post(
        f"{BASE}/treatment-plans/{plan_id}/catalog-items",
        headers=auth_headers,
        json={
            "lines": [
                {"catalog_item_id": pulpotomy, "tooth_numbers": [84, 16]},
                # One piece of work: a primary tooth in it leaves it all out.
                {"catalog_item_id": splint, "tooth_numbers": [13, 53]},
            ]
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert [i["treatment"]["teeth"][0]["tooth_number"] for i in data["items"]] == [84]
    assert data["skipped"] == [
        {"name": "PED-PULPOTOMY (16)", "reason": "wrong_dentition"},
        {"name": "T-BRIDGE (53)", "reason": "wrong_dentition"},
    ]


@pytest.mark.asyncio
async def test_a_primary_tooth_is_proposed_its_own_pulp_treatment(
    client, auth_headers, setup, db_session
):
    """Pulpitis on a primary molar is not an adult molar endodontics."""
    await _dentition_item(db_session, setup, "ENDO-MULTI", "permanent")
    await _dentition_item(db_session, setup, "PED-PULPOTOMY", "deciduous")
    await _finding(client, auth_headers, setup, "pulpitis", 84)
    await _finding(client, auth_headers, setup, "pulpitis", 46)

    r = await client.get(
        f"{BASE}/treatment-plans/patient/{setup['patient_id']}/proposals", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    suggested = {
        p["tooth_number"]: p["suggested_catalog_item"]["internal_code"] for p in r.json()["data"]
    }
    assert suggested == {84: "PED-PULPOTOMY", 46: "ENDO-MULTI"}
