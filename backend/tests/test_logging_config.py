"""Where the logs go, and how much of them, is configuration.

``setup_logging`` took a level nobody passed — ``main.py`` called it bare,
so every deployment ran at ``INFO`` and wrote to stdout alone. ``LOG_LEVEL``
and ``LOG_DIR`` in ``app/config.py`` are what an operator turns; these are
the four behaviours those two settings promise.

The file is a copy, never a replacement: a deployment that gains a log
file must not lose ``docker-compose logs``, which is what the platform's
collector reads.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.log_context import setup_logging


@pytest.fixture
def isolated_root() -> Iterator[logging.Logger]:
    """Hand back the root logger as it was: these tests mutate it."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield root
    for handler in list(root.handlers):
        if handler not in handlers:
            handler.close()
            root.removeHandler(handler)
    root.handlers = handlers
    root.setLevel(level)


def _file_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if isinstance(h, RotatingFileHandler)]


def test_without_a_directory_nothing_is_written_to_disk(
    isolated_root: logging.Logger, tmp_path: Path
) -> None:
    """The default stays what it was: stdout and nothing else."""
    setup_logging("INFO")

    assert not _file_handlers(isolated_root)
    assert not list(tmp_path.iterdir())


def test_a_directory_is_created_and_receives_the_lines(
    isolated_root: logging.Logger, tmp_path: Path
) -> None:
    """``LOG_DIR`` may name a directory that does not exist yet."""
    target = tmp_path / "nested" / "logs"
    setup_logging("DEBUG", log_dir=target)

    logging.getLogger("test.logging").debug("a line that must land on disk")

    written = (target / "dienteazul.log").read_text(encoding="utf-8")
    assert "a line that must land on disk" in written
    # The context filter reaches the file too, not just stdout.
    assert "req=-" in written


def test_the_file_is_rolled_over_and_the_set_stays_bounded(
    isolated_root: logging.Logger, tmp_path: Path
) -> None:
    """Unbounded growth is the failure mode of logging at DEBUG."""
    setup_logging("DEBUG", log_dir=tmp_path, max_bytes=500, backup_count=2)

    log = logging.getLogger("test.logging")
    for index in range(40):
        log.debug("line %d, padded enough to cross the rollover threshold", index)

    rolled = sorted(p.name for p in tmp_path.iterdir())
    assert rolled == ["dienteazul.log", "dienteazul.log.1", "dienteazul.log.2"]


def test_a_second_call_does_not_stack_handlers_on_one_file(
    isolated_root: logging.Logger, tmp_path: Path
) -> None:
    """Reload and lifespan both call it; twice must mean once."""
    setup_logging("INFO", log_dir=tmp_path)
    setup_logging("INFO", log_dir=tmp_path)

    assert len(_file_handlers(isolated_root)) == 1


def test_an_unwritable_directory_warns_instead_of_taking_the_backend_down(
    isolated_root: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """An operator's typo in LOG_DIR must not stop a clinic working."""
    with caplog.at_level(logging.WARNING):
        setup_logging("INFO", log_dir="/proc/cannot-exist/logs")

    assert not _file_handlers(isolated_root)
    assert "logging to stdout only" in caplog.text


def test_a_level_nobody_recognises_is_refused_at_boot() -> None:
    """``getLevelName`` would accept it and log nothing. Say so instead."""
    with pytest.raises(ValidationError, match="is not a logging level"):
        Settings(LOG_LEVEL="VERBOSE")


def test_a_level_is_read_however_it_is_spelled() -> None:
    assert Settings(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"
    assert Settings(LOG_LEVEL=" warning ").LOG_LEVEL == "WARNING"
