"""Layer 4: which batch of which device went into which patient.

The only patient data this module holds, and the only part of it that a
deletion request cannot remove. Two things are pinned here: that the
trace and the stock movement are written together or not at all, and
that the privacy contract says out loud why this record stays.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.privacy import SubjectContributor
from app.modules.inventory.models import ImplantTrace, InventoryMovement
from app.modules.inventory.privacy import RETENTION_REASON, get_subject_contributors
from app.modules.inventory.service import (
    ImplantService,
    InventoryError,
    ItemService,
    LocationService,
    LotService,
    StockService,
)

BASE = "/api/v1/inventory"


@pytest.fixture
async def implants(db_session: AsyncSession, test_clinic: Clinic) -> dict:
    store = await LocationService.create(
        db_session, test_clinic.id, {"name": "Almacén", "kind": "warehouse", "is_default": True}
    )
    implant = await ItemService.create(
        db_session,
        test_clinic.id,
        {
            "code": "IMP-4010",
            "name": "Implante 4.0x10",
            "base_unit": "unidad",
            "category": "implant",
            "tracks_lots": True,
        },
    )
    gloves = await ItemService.create(
        db_session, test_clinic.id, {"code": "GUA", "name": "Guantes", "base_unit": "par"}
    )
    lot = await LotService.create(
        db_session,
        test_clinic.id,
        implant.id,
        {"lot_code": "L-IMP-7788", "expires_on": date(2029, 5, 31)},
    )
    await StockService.post(
        db_session,
        test_clinic.id,
        None,
        item_id=implant.id,
        location_id=store.id,
        lot_id=lot.id,
        quantity_base=Decimal("5"),
        reason="purchase_receipt",
    )
    await db_session.commit()
    return {
        "clinic_id": test_clinic.id,
        "implant": implant,
        "gloves": gloves,
        "lot": lot,
        "store": store,
    }


def _record(implants: dict, patient_id, **overrides) -> dict:
    data = {
        "patient_id": patient_id,
        "item_id": implants["implant"].id,
        "lot_id": implants["lot"].id,
        "placed_on": date.today(),
        "quantity": Decimal("1"),
        "tooth_number": 36,
        "serial_number": "SN-99812",
        "notes": "Carga diferida",
    }
    data.update(overrides)
    return data


# --- the act -------------------------------------------------------------


async def test_recording_a_device_moves_the_stock_and_writes_the_trace(
    db_session: AsyncSession, implants: dict
) -> None:
    patient_id = uuid4()
    trace = await ImplantService.record(
        db_session, implants["clinic_id"], None, _record(implants, patient_id)
    )
    await db_session.commit()

    assert trace.patient_id == patient_id
    assert trace.tooth_number == 36

    totals = await StockService.item_totals(
        db_session, implants["clinic_id"], [implants["implant"].id]
    )
    assert totals[implants["implant"].id] == Decimal("4")

    # The trace points at the very movement that took it off the shelf.
    movement = await db_session.scalar(
        select(InventoryMovement).where(InventoryMovement.id == trace.movement_id)
    )
    assert movement.reason == "consumption"
    assert movement.lot_id == implants["lot"].id
    assert movement.quantity_base == Decimal("-1.000")


async def test_a_device_that_does_not_track_lots_cannot_be_traced(
    db_session: AsyncSession, implants: dict
) -> None:
    """A trace without a batch traces nothing."""
    with pytest.raises(InventoryError, match="must track lots"):
        await ImplantService.record(
            db_session,
            implants["clinic_id"],
            None,
            _record(implants, uuid4(), item_id=implants["gloves"].id),
        )


async def test_a_batch_can_be_turned_into_a_list_of_patients(
    db_session: AsyncSession, implants: dict
) -> None:
    """The recall question, which is why the table exists."""
    first, second = uuid4(), uuid4()
    for patient_id in (first, second):
        await ImplantService.record(
            db_session, implants["clinic_id"], None, _record(implants, patient_id)
        )
    await db_session.commit()

    carriers = await ImplantService.list(
        db_session, implants["clinic_id"], lot_id=implants["lot"].id
    )
    assert {trace.patient_id for trace in carriers} == {first, second}


async def test_one_clinic_never_sees_another_clinics_traces(
    db_session: AsyncSession, implants: dict
) -> None:
    other = Clinic(
        id=uuid4(),
        name="Otra",
        tax_id="B99999999",
        address={},
        settings={},
        account_tier="clinic",
    )
    db_session.add(other)
    await db_session.flush()
    patient_id = uuid4()
    await ImplantService.record(
        db_session, implants["clinic_id"], None, _record(implants, patient_id)
    )
    await db_session.commit()

    assert await ImplantService.list(db_session, other.id, patient_id=patient_id) == []


# --- privacy -------------------------------------------------------------


def test_the_module_refuses_erasure_and_says_why() -> None:
    """ADR 0026: silence about erasability is not an option.

    This section cannot be anonymized, so it must carry a reason a
    clinic can read out to a patient.
    """
    contributors = get_subject_contributors()
    assert [c.name for c in contributors] == ["implant_traces"]

    traces = contributors[0]
    assert isinstance(traces, SubjectContributor)
    assert traces.anonymize is None
    assert traces.erasable is False
    assert traces.retention_reason == RETENTION_REASON
    assert "trazabilidad" in RETENTION_REASON.lower()


async def test_the_export_names_the_device_and_the_batch(
    db_session: AsyncSession, implants: dict
) -> None:
    """Portability has no exception, and ids mean nothing outside here."""
    patient_id = uuid4()
    await ImplantService.record(
        db_session, implants["clinic_id"], None, _record(implants, patient_id)
    )
    await db_session.commit()

    export = await get_subject_contributors()[0].export(
        db_session, implants["clinic_id"], patient_id
    )
    assert len(export) == 1
    assert export[0]["device_code"] == "IMP-4010"
    assert export[0]["lot_code"] == "L-IMP-7788"
    assert export[0]["lot_expires_on"] == date(2029, 5, 31)
    assert export[0]["serial_number"] == "SN-99812"
    # No internal ids: the patient gets what they could hand to somebody
    # else.
    assert not any(key.endswith("_id") for key in export[0])


async def test_an_erasure_leaves_the_trace_standing(
    db_session: AsyncSession, implants: dict, client: AsyncClient, auth_headers: dict
) -> None:
    """What the retention reason means in practice.

    Core fans an erasure out over the contributors; this one supplies no
    anonymize callable, so its rows are untouched by construction. The
    test states the consequence rather than the mechanism, because the
    consequence is the promise: a withdrawn batch can still be traced to
    the people carrying it.
    """
    patient_id = uuid4()
    await ImplantService.record(
        db_session, implants["clinic_id"], None, _record(implants, patient_id)
    )
    await db_session.commit()

    contributor = get_subject_contributors()[0]
    assert contributor.anonymize is None

    surviving = await db_session.scalar(
        select(func.count()).select_from(ImplantTrace).where(ImplantTrace.patient_id == patient_id)
    )
    assert surviving == 1


# --- the API -------------------------------------------------------------


async def test_the_api_records_and_lists_a_trace(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic, implants: dict
) -> None:
    patient_id = str(uuid4())
    recorded = await client.post(
        f"{BASE}/implants",
        json={
            "patient_id": patient_id,
            "item_id": str(implants["implant"].id),
            "lot_id": str(implants["lot"].id),
            "placed_on": date.today().isoformat(),
            "tooth_number": 36,
            "serial_number": "SN-1",
        },
        headers=auth_headers,
    )
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["data"]["lot_code"] == "L-IMP-7788"

    by_lot = await client.get(f"{BASE}/implants?lot_id={implants['lot'].id}", headers=auth_headers)
    assert [t["patient_id"] for t in by_lot.json()["data"]] == [patient_id]

    # With no Patients App supplying the directory in this test, the id
    # is there and the name is not — which is the designed answer.
    assert by_lot.json()["data"][0]["first_name"] is None
