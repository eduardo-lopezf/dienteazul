"""A whole copy of a deployment, out of one installation and into another
(``/api/v1/ops/snapshot``, ADR 0049 rule 4 amended).

What is pinned here: only the control plane's token opens it; putting a
copy in needs ``confirm=replace``, keeps a copy of what was there first,
and leaves the deployment holding exactly the copy — its clinics and its
files, and nothing it had besides; a copy of another schema is refused.

Everything runs against the suite's own ``*_test`` database: the copy is
taken from, and put into, the database the request's session is bound to.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.models import Clinic
from app.core.ops.snapshot import DATABASE, MANIFEST

from .test_ops_endpoint import SECRET, _token


@pytest.fixture
def ops_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    return tmp_path


def _clinic(name: str) -> Clinic:
    return Clinic(name=name, tax_id="XAXX010101000", account_tier="clinic", timezone="UTC")


async def _clinic_names(db: AsyncSession) -> set[str]:
    return set(await db.scalars(select(Clinic.name)))


async def test_a_copy_needs_the_control_planes_token(
    client: AsyncClient, ops_enabled: None, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/ops/snapshot", headers=auth_headers)).status_code == 401


async def test_a_copy_holds_the_database_and_the_files(
    client: AsyncClient, ops_enabled: None, storage: Path
) -> None:
    (storage / "clinic-a").mkdir()
    (storage / "clinic-a" / "xray.jpg").write_bytes(b"radiografia")
    (storage / "backups").mkdir()
    (storage / "backups" / "old.tar.gz").write_bytes(b"not part of it")

    response = await client.get("/api/v1/ops/snapshot", headers=_token())
    assert response.status_code == 200, response.text
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
        names = tar.getnames()
        manifest = json.load(tar.extractfile(MANIFEST))
    assert DATABASE in names
    assert "files/clinic-a/xray.jpg" in names
    assert not any(name.startswith("files/backups") for name in names)
    assert manifest["format"] == 1


async def test_putting_a_copy_in_replaces_the_deployment(
    client: AsyncClient, ops_enabled: None, storage: Path, db_session: AsyncSession
) -> None:
    db_session.add(_clinic("Clínica que viaja"))
    await db_session.commit()
    (storage / "clinic-a").mkdir()
    (storage / "clinic-a" / "xray.jpg").write_bytes(b"radiografia")
    copy = (await client.get("/api/v1/ops/snapshot", headers=_token())).content

    # What happens here afterwards is what the copy takes away.
    db_session.add(_clinic("Clínica que no estaba"))
    await db_session.commit()
    (storage / "clinic-a" / "xray.jpg").unlink()
    (storage / "stray.txt").write_text("no estaba en la copia")

    refused = await client.put("/api/v1/ops/snapshot", content=copy, headers=_token())
    assert refused.status_code == 422  # no confirm=replace

    response = await client.put(
        "/api/v1/ops/snapshot?confirm=replace", content=copy, headers=_token()
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert (result["clinics"], result["files"]) == (1, 1)

    db_session.expire_all()
    assert await _clinic_names(db_session) == {"Clínica que viaja"}
    assert (storage / "clinic-a" / "xray.jpg").read_bytes() == b"radiografia"
    assert not (storage / "stray.txt").exists()
    # What was here before is kept, in the backups folder the copy skips.
    backup = storage / "backups" / result["backup"]
    with tarfile.open(backup, "r:gz") as tar:
        assert "files/stray.txt" in tar.getnames()
    assert await db_session.scalar(select(func.count()).select_from(Clinic)) == 1


async def test_a_copy_of_another_schema_is_refused(
    client: AsyncClient, ops_enabled: None, storage: Path, db_session: AsyncSession
) -> None:
    db_session.add(_clinic("Se queda"))
    await db_session.commit()

    manifest = json.dumps({"format": 1, "revisions": ["9999"]}).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))

    response = await client.put(
        "/api/v1/ops/snapshot?confirm=replace", content=buffer.getvalue(), headers=_token()
    )
    assert response.status_code == 409
    assert "9999" in response.json()["message"]
    assert await _clinic_names(db_session) == {"Se queda"}

    garbage = await client.put(
        "/api/v1/ops/snapshot?confirm=replace", content=b"not a copy", headers=_token()
    )
    assert garbage.status_code == 409
