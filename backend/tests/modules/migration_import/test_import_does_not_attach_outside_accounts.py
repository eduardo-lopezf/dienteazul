"""An import may not make another clinic's account into this clinic's staff.

`users.email` is unique across the deployment and an account is global
(ADR 0057), so looking a person up by email reaches accounts belonging to
clinics the importer has nothing to do with. Both the user and
professional mappers did that and then added a `ClinicMembership` — which
silently turned another tenant's staff into this clinic's, handing them
its patient data, with nobody on either side asked.

The rule now: reuse an account only when it is already this clinic's
staff (the idempotent re-run every mapper relies on). Otherwise import
the person under an account of this clinic's own and say so.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth.models import Clinic, ClinicMembership, User
from app.modules.migration_import.mappers.base import MapperContext, MappingResolver
from app.modules.migration_import.mappers.professional import ProfessionalMapper
from app.modules.migration_import.mappers.user import UserMapper
from app.modules.migration_import.models import ImportJob, ImportWarning

SHARED = "compartido@example.com"


@pytest.mark.asyncio
async def test_an_outside_account_is_not_given_a_membership(db_session) -> None:
    """The leak: importing a file that names somebody else's address."""
    clinic, admin = await _bootstrap(db_session)
    outsider = await _outsider(db_session, SHARED)
    ctx = await _ctx(db_session, clinic.id, admin.id)

    await UserMapper().apply(
        ctx,
        entity_type="user",
        payload={"email": SHARED, "given_name": "Ana", "family_name": "Ruiz"},
        raw={},
        canonical_uuid=str(uuid4()),
        source_id="1",
        source_system="gesden",
    )
    await db_session.flush()

    memberships = (
        (
            await db_session.execute(
                select(ClinicMembership).where(ClinicMembership.user_id == outsider.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(memberships) == 1, "the outside account gained a membership here"
    assert memberships[0].clinic_id != clinic.id


@pytest.mark.asyncio
async def test_the_person_still_arrives_under_a_local_account(db_session) -> None:
    """Skipping the row would drop staff — and the rows pointing at them.

    So the import proceeds, under an address of this clinic's own. The
    account is inert until an admin sends a password reset: every mapper
    writes a sentinel hash bcrypt cannot match.
    """
    clinic, admin = await _bootstrap(db_session)
    await _outsider(db_session, SHARED)
    ctx = await _ctx(db_session, clinic.id, admin.id)

    await UserMapper().apply(
        ctx,
        entity_type="user",
        payload={"email": SHARED, "given_name": "Ana", "family_name": "Ruiz"},
        raw={},
        canonical_uuid=str(uuid4()),
        source_id="1",
        source_system="gesden",
    )
    await db_session.flush()

    here = (
        (
            await db_session.execute(
                select(User)
                .join(ClinicMembership, ClinicMembership.user_id == User.id)
                .where(ClinicMembership.clinic_id == clinic.id, User.id != admin.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(here) == 1
    assert here[0].email != SHARED
    assert here[0].password_hash.startswith("!migration_disabled:")


@pytest.mark.asyncio
async def test_the_collision_is_reported_rather_than_silent(db_session) -> None:
    clinic, admin = await _bootstrap(db_session)
    await _outsider(db_session, SHARED)
    ctx = await _ctx(db_session, clinic.id, admin.id)

    await UserMapper().apply(
        ctx,
        entity_type="user",
        payload={"email": SHARED, "given_name": "Ana", "family_name": "Ruiz"},
        raw={},
        canonical_uuid=str(uuid4()),
        source_id="1",
        source_system="gesden",
    )
    await db_session.flush()

    warnings = (
        (await db_session.execute(select(ImportWarning).where(ImportWarning.job_id == ctx.job_id)))
        .scalars()
        .all()
    )
    assert any("another_clinic" in w.code for w in warnings), [w.code for w in warnings]


@pytest.mark.asyncio
async def test_a_professional_is_covered_too(db_session) -> None:
    """The professional mapper resolves to `users.id`, so it is an account."""
    clinic, admin = await _bootstrap(db_session)
    outsider = await _outsider(db_session, SHARED)
    ctx = await _ctx(db_session, clinic.id, admin.id)

    await ProfessionalMapper().apply(
        ctx,
        entity_type="professional",
        payload={
            "email": SHARED,
            "given_name": "Ana",
            "family_name": "Ruiz",
            "role": "dentist",
        },
        raw={},
        canonical_uuid=str(uuid4()),
        source_id="1",
        source_system="gesden",
    )
    await db_session.flush()

    memberships = (
        (
            await db_session.execute(
                select(ClinicMembership).where(
                    ClinicMembership.user_id == outsider.id,
                    ClinicMembership.clinic_id == clinic.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert memberships == []


@pytest.mark.asyncio
async def test_this_clinics_own_account_is_still_reused(db_session) -> None:
    """The positive control: re-running an import must stay idempotent.

    Refusing every known address would create a duplicate account on
    every re-run, which is the failure the reuse exists to avoid.
    """
    clinic, admin = await _bootstrap(db_session)
    mine = User(
        id=uuid4(),
        email=SHARED,
        password_hash="x",
        first_name="Ana",
        last_name="Ruiz",
    )
    db_session.add(mine)
    await db_session.flush()
    db_session.add(ClinicMembership(user_id=mine.id, clinic_id=clinic.id, role="assistant"))
    await db_session.flush()
    ctx = await _ctx(db_session, clinic.id, admin.id)

    mapped = await UserMapper().apply(
        ctx,
        entity_type="user",
        payload={"email": SHARED, "given_name": "Ana", "family_name": "Ruiz"},
        raw={},
        canonical_uuid=str(uuid4()),
        source_id="1",
        source_system="gesden",
    )
    await db_session.flush()

    assert mapped == mine.id, "an account already on this clinic's staff is reused"


async def _bootstrap(db_session):
    clinic = Clinic(
        id=uuid4(), name="Mine", tax_id=f"B{uuid4().int % 10**8:08d}", account_tier="clinic"
    )
    admin = User(
        id=uuid4(),
        email=f"admin-{uuid4().hex[:8]}@test.local",
        password_hash="x",
        first_name="A",
        last_name="A",
    )
    db_session.add_all([clinic, admin])
    await db_session.flush()
    db_session.add(ClinicMembership(user_id=admin.id, clinic_id=clinic.id, role="admin"))
    await db_session.flush()
    return clinic, admin


async def _outsider(db_session, email: str) -> User:
    """An account holding `email`, belonging to a clinic far away."""
    other = Clinic(
        id=uuid4(), name="Theirs", tax_id=f"B{uuid4().int % 10**8:08d}", account_tier="clinic"
    )
    user = User(id=uuid4(), email=email, password_hash="x", first_name="Ana", last_name="Ruiz")
    db_session.add_all([other, user])
    await db_session.flush()
    db_session.add(ClinicMembership(user_id=user.id, clinic_id=other.id, role="dentist"))
    await db_session.flush()
    return user


async def _ctx(db_session, clinic_id, admin_id):
    job = ImportJob(
        clinic_id=clinic_id,
        created_by=admin_id,
        status="executing",
        original_filename="t.dpm",
        file_path="/tmp/t.dpm",
        file_size=0,
    )
    db_session.add(job)
    await db_session.flush()
    return MapperContext(
        db=db_session,
        clinic_id=clinic_id,
        job_id=job.id,
        resolver=MappingResolver(db=db_session, clinic_id=clinic_id, job_id=job.id),
        import_fiscal_compliance=False,
        created_by=admin_id,
    )
