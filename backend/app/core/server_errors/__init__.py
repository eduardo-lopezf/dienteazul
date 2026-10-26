"""The requests that ended in a server error, kept for the operator.

An exception nothing handled becomes a ``500`` ("Error del servidor") for
whoever made the request. This keeps one JSON line per occurrence in
``<ERROR_LOG_DIR>/errors.log``, which the operator's control panel reads
(``GET /api/v1/ops/errors``, ADR 0049 rule 4), so the origin of a failure
can be found from the panel, in development and in production alike.

They used to be rows in ``server_errors``. They are a log — written once,
read in order, never updated, aged out — and a log belongs in a file an
operator can also tail, ship or grep without a database client
(ADR 0060).

What a line holds is **where** it failed, never what it was working on:
the route, the exception's type, its message with any values taken out,
and the chain of calls — file, line and function, no local variables —
plus the request, clinic and user identifiers (ADR 0049 rule 5). A
database error's message names the values that broke a constraint; those
are replaced before the line is written.

Retention is the rotation: ``ERROR_LOG_MAX_BYTES`` per file and
``ERROR_LOG_BACKUP_COUNT`` kept beside it. Recording never raises: a
failure to record a failure is logged and dropped.

**One writer per directory.** The handler rotates from this process, so
several backends (ADR 0051) sharing one directory roll the file over on
top of each other, and the panel only reads what its own process can
see. With replicas, ship the files instead.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The file the panel reads, and the stem its rotated copies share.
LOG_FILE_NAME = "errors.log"

_MESSAGE_LIMIT = 1000
_FRAMES_LIMIT = 40

#: Built once per process, then reused. A cache, not shared state
#: (ADR 0051) — the file on disk is what outlives the process.
_writer: logging.Logger | None = None
_writer_dir: Path | None = None
_lock = threading.Lock()


# What a message may quote that is somebody's: the parameters SQLAlchemy
# appends, the values PostgreSQL names in a constraint's DETAIL, e-mail
# addresses, quoted strings and long digit runs.
_SCRUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\[parameters: .*?\]", re.S), "[parameters: …]"),
    (re.compile(r"\(Background on this error at: [^)]*\)"), ""),
    (
        re.compile(r"\)=\((.*?)\)( already exists| is not present| is still referenced)?"),
        r")=(…)\2",
    ),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "…@…"),
    (re.compile(r"'[^']{3,}'"), "'…'"),
    (re.compile(r"\b\d{6,}\b"), "…"),
)


def scrub(message: str) -> str:
    """``message`` without the values it quoted."""
    for pattern, replacement in _SCRUBS:
        message = pattern.sub(replacement, message)
    return message.strip()[:_MESSAGE_LIMIT]


def frames_of(exc: BaseException) -> str:
    """The calls that led to ``exc``: where, never with what."""
    summary = traceback.extract_tb(exc.__traceback__)[-_FRAMES_LIMIT:]
    lines = [f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in summary]
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        lines.append(f"caused by {type(cause).__module__}.{type(cause).__qualname__}")
    return "\n".join(lines)


def log_dir() -> Path:
    """Where the occurrences are kept, as configured."""
    from app.config import settings

    return Path(settings.ERROR_LOG_DIR)


def _rebind(directory: Path) -> logging.Logger | None:
    """A logger that writes raw lines to ``directory``, or ``None``.

    Its own logger, detached from the root: these lines are JSON and must
    not reach the formatters that decorate everything else, nor stdout,
    where they would be a second copy of the traceback already logged.
    """
    from app.config import settings

    global _writer, _writer_dir
    if _writer is not None and _writer_dir == directory:
        return _writer

    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / LOG_FILE_NAME,
            maxBytes=settings.ERROR_LOG_MAX_BYTES,
            backupCount=settings.ERROR_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Cannot write server errors to %s", directory)
        return None

    handler.setFormatter(logging.Formatter("%(message)s"))
    writer = logging.getLogger("dienteazul.server_errors")
    writer.setLevel(logging.ERROR)
    writer.propagate = False
    for old in list(writer.handlers):
        old.close()
        writer.removeHandler(old)
    writer.addHandler(handler)

    _writer, _writer_dir = writer, directory
    return writer


def record(
    exc: BaseException,
    *,
    method: str,
    path: str,
    request_id: str | None,
    clinic_id: str | None,
    user_id: str | None,
) -> None:
    """Keep one occurrence as a JSON line. Never raises."""
    try:
        with _lock:
            writer = _rebind(log_dir())
        if writer is None:
            return
        writer.error(
            json.dumps(
                {
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "method": method[:10],
                    "path": path[:300],
                    "status_code": 500,
                    "error_type": f"{type(exc).__module__}.{type(exc).__qualname__}"[:200],
                    "message": scrub(str(exc)) or type(exc).__name__,
                    "frames": frames_of(exc),
                    "request_id": request_id,
                    "clinic_id": clinic_id,
                    "user_id": user_id,
                },
                ensure_ascii=False,
            )
        )
    except Exception:  # noqa: BLE001 — recording must never be the next failure
        logger.exception("Could not record a server error")


def _files_newest_first(directory: Path) -> list[Path]:
    """``errors.log`` then its rotated copies, newest first.

    ``RotatingFileHandler`` numbers backups by age: ``.log.1`` is the one
    rolled most recently, so the numeric order is the chronological one.
    """
    live = directory / LOG_FILE_NAME
    backups = sorted(
        (p for p in directory.glob(f"{LOG_FILE_NAME}.*") if p.suffix.lstrip(".").isdigit()),
        key=lambda p: int(p.suffix.lstrip(".")),
    )
    return [p for p in [live, *backups] if p.is_file()]


def read(limit: int) -> list[dict[str, Any]]:
    """The most recent occurrences, newest first.

    A line that is not JSON is skipped rather than failing the read: a
    half-written last line is what a crash mid-write leaves behind, and
    the panel should still show the rest.
    """
    directory = log_dir()
    out: list[dict[str, Any]] = []
    try:
        for path in _files_newest_first(directory):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(out) >= limit:
                    return out
    except OSError:
        logger.exception("Cannot read server errors from %s", directory)
    return out


def clear() -> None:
    """Forget every occurrence — once their causes are fixed.

    The live file is truncated through its handler rather than deleted,
    so the process keeps writing to the same open descriptor.
    """
    directory = log_dir()
    try:
        with _lock:
            if _writer is not None and _writer_dir == directory:
                for handler in _writer.handlers:
                    if isinstance(handler, RotatingFileHandler):
                        handler.close()
                        handler.stream = handler._open()  # noqa: SLF001 — truncate in place
            for path in _files_newest_first(directory):
                if path.name != LOG_FILE_NAME:
                    path.unlink(missing_ok=True)
            live = directory / LOG_FILE_NAME
            if live.is_file():
                live.write_text("", encoding="utf-8")
    except OSError:
        logger.exception("Cannot clear server errors in %s", directory)


def reset_writer() -> None:
    """Drop the cached handler so the next write re-reads the setting.

    For tests, which point ``ERROR_LOG_DIR`` at a directory of their own.
    """
    global _writer, _writer_dir
    with _lock:
        if _writer is not None:
            for handler in list(_writer.handlers):
                handler.close()
                _writer.removeHandler(handler)
        _writer, _writer_dir = None, None
