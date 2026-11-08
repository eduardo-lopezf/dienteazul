"""What each professional is paid, treatment by treatment.

A general percentage plus a different one for specific treatments of the
catalogue. The settlement in `liquidations` reads them through the
``CommissionRates`` contract, so the expensive tests are the ones where a
period mixes treatments paid at different percentages.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.plugins.registry import module_registry
from app.modules.catalog.models import TreatmentCatalogItem, TreatmentCategory
from app.modules.patients.models import Patient
from app.modules.payments.models import PatientEarnedEntry
from app.modules.professionals.models import Professional

BASE = "/api/v1/commissions"
FROM, TO = date(2026, 9, 1), date(2026, 9, 15)


@contextmanager
def off(name: str) -> Iterator[None]:
    was_active = module_registry.is_installed(name)
    module_registry.deactivate(name)
    try:
        yield
    finally:
        if was_active:
            module_registry.activate(name)


@pytest.fixture
async def ctx(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    category = TreatmentCategory(
        clinic_id=test_clinic.id, key="com", names={"es": "C"}, is_system=True
    )
    db_session.add(category)
    await db_session.flush()
    implant, cleaning = (
        TreatmentCatalogItem(
            clinic_id=test_clinic.id,
            category_id=category.id,
            internal_code=code,
            names={"es": name},
            pricing_strategy="flat",
            treatment_scope="global_mouth",
        )
        for code, name in (("IMPL", "Implante"), ("LIMP", "Limpieza"))
    )
    ana = Professional(
        id=uuid4(),
        clinic_id=test_clinic.id,
        first_name="Ana",
        last_name="Asociada",
        professional_type="dentist",
    )
    patient = Patient(id=uuid4(), clinic_id=test_clinic.id, first_name="Com", last_name="Prueba")
    # An optional module of the Professionals App: off until switched on.
    test_clinic.modules = ["commissions"]
    db_session.add_all([implant, cleaning, ana, patient])
    await db_session.commit()
    return {
        "clinic": test_clinic,
        "ana": ana.id,
        "patient_id": patient.id,
        "implant": implant.id,
        "cleaning": cleaning.id,
    }


async def _put(client: AsyncClient, headers: dict, professional_id: UUID, body: dict):
    return await client.put(f"{BASE}/professionals/{professional_id}", json=body, headers=headers)


async def _earn(db: AsyncSession, ctx: dict, amount: str, catalog_item_id: UUID) -> None:
    db.add(
        PatientEarnedEntry(
            id=uuid4(),
            clinic_id=ctx["clinic"].id,
            patient_id=ctx["patient_id"],
            treatment_id=uuid4(),
            catalog_item_id=catalog_item_id,
            description="Trabajo",
            amount=Decimal(amount),
            performed_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
            professional_id=ctx["ana"],
            source_event="test",
        )
    )
    await db.commit()


async def _preview(client: AsyncClient, headers: dict, professional_id: UUID) -> dict:
    response = await client.get(
        "/api/v1/liquidations/preview",
        params={
            "professional_id": str(professional_id),
            "date_from": FROM.isoformat(),
            "date_to": TO.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- The agreement ----------------------------------------------------


async def test_a_professional_starts_with_nothing_agreed(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    response = await client.get(f"{BASE}/professionals/{ctx['ana']}", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["configured"] is False
    assert data["default_percent"] is None
    assert data["rates"] == []


async def test_a_general_percentage_with_treatment_exceptions(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    saved = await _put(
        client,
        auth_headers,
        ctx["ana"],
        {
            "basis": "earned",
            "default_percent": "40",
            "rates": [{"catalog_item_id": str(ctx["implant"]), "percent": "50"}],
            "notes": "  Acordado en marzo  ",
        },
    )

    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["configured"] is True
    assert data["basis"] == "earned"
    assert Decimal(data["default_percent"]) == Decimal("40")
    assert data["notes"] == "Acordado en marzo"
    [rate] = data["rates"]
    assert rate["catalog_item_id"] == str(ctx["implant"])
    assert Decimal(rate["percent"]) == Decimal("50")
    # Named from the catalogue, without importing it.
    assert rate["internal_code"] == "IMPL"
    assert rate["names"] == {"es": "Implante"}


async def test_saving_replaces_the_whole_agreement(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    await _put(
        client,
        auth_headers,
        ctx["ana"],
        {
            "default_percent": "40",
            "rates": [
                {"catalog_item_id": str(ctx["implant"]), "percent": "50"},
                {"catalog_item_id": str(ctx["cleaning"]), "percent": "30"},
            ],
        },
    )
    saved = await _put(
        client,
        auth_headers,
        ctx["ana"],
        {
            "default_percent": "45",
            "rates": [{"catalog_item_id": str(ctx["implant"]), "percent": "55"}],
        },
    )

    data = saved.json()["data"]
    assert Decimal(data["default_percent"]) == Decimal("45")
    assert [(r["catalog_item_id"], Decimal(r["percent"])) for r in data["rates"]] == [
        (str(ctx["implant"]), Decimal("55"))
    ]


async def test_no_percentage_and_no_rates_clears_the_agreement(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    await _put(client, auth_headers, ctx["ana"], {"default_percent": "40"})

    cleared = await _put(client, auth_headers, ctx["ana"], {"default_percent": None})

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["configured"] is False


async def test_a_treatment_takes_one_percentage(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    rate = {"catalog_item_id": str(ctx["implant"]), "percent": "50"}
    response = await _put(client, auth_headers, ctx["ana"], {"rates": [rate, rate]})

    assert response.status_code == 422
    assert response.json()["code"] == "commissions.rate.duplicate"


async def test_a_rate_names_a_treatment_of_this_clinic(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    response = await _put(
        client,
        auth_headers,
        ctx["ana"],
        {"rates": [{"catalog_item_id": str(uuid4()), "percent": "50"}]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "commissions.treatment.not_found"


async def test_percentages_stay_between_zero_and_a_hundred(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    response = await _put(client, auth_headers, ctx["ana"], {"default_percent": "101"})

    assert response.status_code == 422


async def test_a_professional_of_another_clinic_is_not_found(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    response = await _put(client, auth_headers, uuid4(), {"default_percent": "40"})

    assert response.status_code == 404
    assert response.json()["code"] == "commissions.professional.not_found"


async def test_an_individual_practice_has_no_commissions(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    ctx["clinic"].account_tier = "basic"
    await db_session.commit()

    response = await client.get(f"{BASE}/professionals/{ctx['ana']}", headers=auth_headers)

    # Switched on or not, only a clinic may have it (`tiers` in apps.json):
    # for anyone else it is outside, as a module of an App it lacks.
    assert response.status_code == 404


async def test_the_picker_lists_the_catalogue(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    response = await client.get(f"{BASE}/treatments", headers=auth_headers)

    assert response.status_code == 200, response.text
    codes = {t["internal_code"] for t in response.json()["data"]}
    assert {"IMPL", "LIMP"} <= codes


async def test_with_the_treatments_app_off_rates_are_kept_but_none_added(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    implant = {"catalog_item_id": str(ctx["implant"]), "percent": "50"}
    await _put(client, auth_headers, ctx["ana"], {"rates": [implant]})

    with off("catalog"):
        kept = await _put(
            client, auth_headers, ctx["ana"], {"default_percent": "40", "rates": [implant]}
        )
        added = await _put(
            client,
            auth_headers,
            ctx["ana"],
            {"rates": [implant, {"catalog_item_id": str(ctx["cleaning"]), "percent": "30"}]},
        )
        treatments = await client.get(f"{BASE}/treatments", headers=auth_headers)

    assert kept.status_code == 200, kept.text
    [rate] = kept.json()["data"]["rates"]
    assert rate["internal_code"] is None
    assert added.status_code == 422
    assert added.json()["code"] == "commissions.apps.unavailable"
    assert treatments.json()["data"] == []


# --- What the settlement makes of it -----------------------------------


async def test_the_settlement_pays_each_treatment_at_its_own_percentage(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    await _earn(db_session, ctx, "1000.00", ctx["implant"])
    await _earn(db_session, ctx, "200.00", ctx["cleaning"])
    await _put(
        client,
        auth_headers,
        ctx["ana"],
        {
            "basis": "earned",
            "default_percent": "40",
            "rates": [{"catalog_item_id": str(ctx["implant"]), "percent": "50"}],
        },
    )

    preview = await _preview(client, auth_headers, ctx["ana"])

    assert preview["rates_source"] == "commissions"
    assert preview["missing_commission"] is False
    by_item = {line["catalog_item_id"]: line for line in preview["lines"]}
    assert Decimal(by_item[str(ctx["implant"])]["percent"]) == Decimal("50")
    assert Decimal(by_item[str(ctx["implant"])]["share"]) == Decimal("500.00")
    assert Decimal(by_item[str(ctx["cleaning"])]["percent"]) == Decimal("40")
    assert Decimal(by_item[str(ctx["cleaning"])]["share"]) == Decimal("80.00")
    assert Decimal(preview["amount_due"]) == Decimal("580.00")


async def test_a_treatment_with_no_percentage_blocks_the_settlement(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    """Only implants agreed: the cleaning has no percentage, not a zero one."""
    await _earn(db_session, ctx, "1000.00", ctx["implant"])
    await _earn(db_session, ctx, "200.00", ctx["cleaning"])
    await _put(
        client,
        auth_headers,
        ctx["ana"],
        {"basis": "earned", "rates": [{"catalog_item_id": str(ctx["implant"]), "percent": "50"}]},
    )

    preview = await _preview(client, auth_headers, ctx["ana"])
    issued = await client.post(
        "/api/v1/liquidations",
        json={
            "professional_id": str(ctx["ana"]),
            "date_from": FROM.isoformat(),
            "date_to": TO.isoformat(),
        },
        headers=auth_headers,
    )

    assert preview["missing_commission"] is True
    by_item = {line["catalog_item_id"]: line for line in preview["lines"]}
    assert by_item[str(ctx["cleaning"])]["percent"] is None
    assert Decimal(preview["amount_due"]) == Decimal("500.00")
    assert issued.status_code == 422
    assert issued.json()["code"] == "liquidations.commission.required"


async def test_the_old_percentage_is_not_written_while_commissions_runs(
    client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    response = await client.put(
        f"/api/v1/liquidations/commissions/{ctx['ana']}",
        json={"basis": "collected", "percent": "40"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "liquidations.commission.managed_by_commissions"


# --- Switching on over existing liquidations -----------------------------


async def test_switching_on_keeps_the_percentages_agreed_in_liquidations(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    """A clinic settling at 40 % must not find "nothing agreed" after switching it on."""
    from app.modules.commissions.service import adopt_liquidation_percentages
    from app.modules.liquidations.models import ProfessionalCommission

    db_session.add(
        ProfessionalCommission(
            clinic_id=ctx["clinic"].id,
            professional_id=ctx["ana"],
            basis="earned",
            percent=Decimal("40"),
            notes="Desde 2025",
        )
    )
    await db_session.commit()

    assert await adopt_liquidation_percentages(db_session, ctx["clinic"].id) == 1
    # Twice is a no-op: the agreement now exists here.
    assert await adopt_liquidation_percentages(db_session, ctx["clinic"].id) == 0
    await db_session.commit()

    data = (await client.get(f"{BASE}/professionals/{ctx['ana']}", headers=auth_headers)).json()[
        "data"
    ]
    assert data["configured"] is True
    assert data["basis"] == "earned"
    assert Decimal(data["default_percent"]) == Decimal("40")
    assert data["notes"] == "Desde 2025"


# --- Switched on and off per clinic (ADR 0066) -----------------------------

APP = "/api/v1/apps/professionals/modules/commissions"


def _switch(apps: list[dict]) -> dict:
    professionals = next(app for app in apps if app["name"] == "professionals")
    return next(m for m in professionals["optional_modules"] if m["name"] == "commissions")


async def test_a_clinic_starts_with_commissions_off(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    assert test_clinic.modules is None

    apps = (await client.get("/api/v1/apps", headers=auth_headers)).json()["data"]
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["data"]
    route = await client.get(f"{BASE}/treatments", headers=auth_headers)

    assert _switch(apps) == {"name": "commissions", "enabled": False, "available": True}
    assert not any(p.startswith("commissions.") for p in me["permissions"])
    assert route.status_code == 404


async def test_switching_off_leaves_professionals_and_the_agreements_intact(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    await _earn(db_session, ctx, "1000.00", ctx["implant"])
    await _put(client, auth_headers, ctx["ana"], {"basis": "earned", "default_percent": "40"})

    off_resp = await client.post(f"{APP}/disable", headers=auth_headers)
    assert off_resp.status_code == 200, off_resp.text
    assert off_resp.json()["data"]["enabled"] is False

    # Professionals carries on: the directory, the professional, the card.
    listed = await client.get("/api/v1/professionals", headers=auth_headers)
    one = await client.get(f"/api/v1/professionals/{ctx['ana']}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert str(ctx["ana"]) in {p["id"] for p in listed.json()["data"]}
    assert one.status_code == 200
    assert one.json()["data"]["first_name"] == "Ana"
    # Commissions is outside the clinic, and liquidations settles on its own.
    assert (
        await client.get(f"{BASE}/professionals/{ctx['ana']}", headers=auth_headers)
    ).status_code == 404
    preview = await _preview(client, auth_headers, ctx["ana"])
    assert preview["rates_source"] == "liquidations"
    own = await client.put(
        f"/api/v1/liquidations/commissions/{ctx['ana']}",
        json={"basis": "earned", "percent": "30"},
        headers=auth_headers,
    )
    assert own.status_code == 200, own.text

    on_resp = await client.post(f"{APP}/enable", headers=auth_headers)
    assert on_resp.status_code == 200, on_resp.text

    # Back on, the agreement set here is where it was.
    data = (await client.get(f"{BASE}/professionals/{ctx['ana']}", headers=auth_headers)).json()[
        "data"
    ]
    assert Decimal(data["default_percent"]) == Decimal("40")
    assert (await _preview(client, auth_headers, ctx["ana"]))["rates_source"] == "commissions"


async def test_switching_on_twice_or_off_twice_changes_nothing(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    for _ in range(2):
        assert (await client.post(f"{APP}/enable", headers=auth_headers)).status_code == 200
    await db_session.refresh(test_clinic)
    assert test_clinic.modules == ["commissions"]

    for _ in range(2):
        assert (await client.post(f"{APP}/disable", headers=auth_headers)).status_code == 200
    await db_session.refresh(test_clinic)
    assert test_clinic.modules == []


@pytest.mark.parametrize("tier", ["basic", "advanced", "clinic_pro", "hospital"])
async def test_only_a_clinic_tier_may_switch_it_on(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    tier: str,
) -> None:
    test_clinic.account_tier = tier
    test_clinic.modules = None
    await db_session.commit()

    response = await client.post(f"{APP}/enable", headers=auth_headers)
    apps = (await client.get("/api/v1/apps", headers=auth_headers)).json()["data"]

    assert response.status_code == 403
    await db_session.refresh(test_clinic)
    assert test_clinic.modules is None
    assert _switch(apps)["available"] is False


async def test_a_switch_kept_from_a_clinic_tier_counts_as_off_elsewhere(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, ctx: dict
) -> None:
    ctx["clinic"].account_tier = "clinic_pro"
    await db_session.commit()

    apps = (await client.get("/api/v1/apps", headers=auth_headers)).json()["data"]

    assert _switch(apps)["enabled"] is False
    assert (await client.get(f"{BASE}/treatments", headers=auth_headers)).status_code == 404


async def test_only_an_optional_module_can_be_switched(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    core = await client.post(
        "/api/v1/apps/professionals/modules/professionals/disable", headers=auth_headers
    )
    stranger = await client.post(
        "/api/v1/apps/patients/modules/commissions/enable", headers=auth_headers
    )

    assert core.status_code == 404
    assert stranger.status_code == 404


async def test_switching_on_announces_it(
    db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    from app.core.events import EventType, event_bus

    seen: list[dict] = []

    async def record(data: dict) -> None:
        seen.append(data)

    event_bus.subscribe(EventType.CLINIC_MODULE_ENABLED, record)
    try:
        await client.post(f"{APP}/enable", headers=auth_headers)
        await client.post(f"{APP}/enable", headers=auth_headers)
    finally:
        event_bus.unsubscribe(EventType.CLINIC_MODULE_ENABLED, record)

    # Once: the second call found it already on.
    assert seen == [{"clinic_id": str(test_clinic.id), "module": "commissions"}]
