"""The application log, read by the control panel at ``/api/v1/ops/logs``.

The lines are written by the real ``setup_logging`` into this test's own
``LOG_DIR`` and read back through the endpoint, so the reader is checked
against the format the writer actually uses."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.log_context import bind, setup_logging

from .test_ops_endpoint import SECRET, _token


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point ``LOG_DIR`` at this test, and leave the root logger as it was."""
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path))
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    setup_logging("DEBUG", log_dir=tmp_path, max_bytes=2000, backup_count=3)
    yield tmp_path
    for handler in list(root.handlers):
        if handler not in handlers:
            handler.close()
            root.removeHandler(handler)
    root.handlers = handlers
    root.setLevel(level)


async def _read(client: AsyncClient, **params: str | int) -> dict:
    response = await client.get("/api/v1/ops/logs", headers=_token(), params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_only_the_control_plane_reads_it(
    client: AsyncClient, log_dir: Path, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/ops/logs", headers=auth_headers)).status_code == 401


async def test_without_a_directory_it_says_there_is_nothing_to_read(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CONTROL_PLANE_SECRET", SECRET)
    monkeypatch.setattr(settings, "LOG_DIR", "")

    assert await _read(client) == {"configured": False, "entries": []}


async def test_records_come_newest_first_with_their_ids(client: AsyncClient, log_dir: Path) -> None:
    log = logging.getLogger("test.app_log")
    log.info("first")
    with bind(request_id="rastreo-9", clinic_id="c1"):
        log.warning("second")

    data = await _read(client, q="test.app_log")

    assert data["configured"] is True
    first, second = data["entries"][1], data["entries"][0]
    assert (second["level"], second["message"]) == ("WARNING", "second")
    assert (second["request_id"], second["clinic_id"]) == ("rastreo-9", "c1")
    assert (first["message"], first["request_id"]) == ("first", None)
    assert second["logger"] == "test.app_log"


async def test_a_traceback_stays_with_its_line_and_loses_the_values(
    client: AsyncClient, log_dir: Path
) -> None:
    log = logging.getLogger("test.app_log")
    try:
        raise ValueError("no row for 'ana.perez@example.com' phone 5512345678")
    except ValueError:
        log.exception("Unhandled exception")
    log.info("after")

    [entry] = (await _read(client, level="ERROR"))["entries"]

    assert entry["message"].startswith("Unhandled exception\nTraceback")
    assert "ValueError" in entry["message"]
    assert "ana.perez" not in entry["message"]
    assert "5512345678" not in entry["message"]


async def test_level_and_search_filter_and_rotated_files_are_read(
    client: AsyncClient, log_dir: Path
) -> None:
    log = logging.getLogger("test.app_log")
    for index in range(30):
        log.debug("filler %d, long enough to roll the file over a few times", index)
    log.error("the one that matters")

    assert (log_dir / "dienteazul.log.1").is_file()
    errors = (await _read(client, level="ERROR"))["entries"]
    assert [e["message"] for e in errors] == ["the one that matters"]
    # The oldest surviving filler sits in a rotated copy.
    found = (await _read(client, q="filler", limit=2000))["entries"]
    assert len(found) > 3
    assert found[0]["message"].startswith("filler 29")
