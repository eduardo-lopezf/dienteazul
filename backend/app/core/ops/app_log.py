"""The application log, as the control panel reads it.

``setup_logging`` appends every line to ``<LOG_DIR>/dienteazul.log`` when
``LOG_DIR`` is set, rotated by size. This reads that file and its rotated
copies back, newest first, one entry per record: a traceback's lines stay
with the line that logged it.

What the panel shows holds identifiers, never what a request was working
on (ADR 0049 rule 5), so every line goes through the same ``scrub`` the
server-error log uses. Like that log, it covers the process that answers
(ADR 0051, ADR 0060).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.log_context import LOG_FILE_NAME
from app.core.server_errors import scrub

logger = logging.getLogger(__name__)

#: ``_DEFAULT_FORMAT`` in ``log_context``, read back.
_RECORD = re.compile(
    r"^(?P<at>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) (?P<level>[A-Z]+)\s+"
    r"\[req=(?P<request_id>\S+) clinic=(?P<clinic_id>\S+)\] (?P<logger>[^:]+): (?P<message>.*)$"
)
_UNBOUND = "-"

#: A traceback longer than this keeps its last lines: the innermost
#: frames and the exception are where it failed.
_ENTRY_LINES = 80


@dataclass(slots=True)
class Entry:
    at: datetime
    level: str
    logger: str
    request_id: str | None
    clinic_id: str | None
    message: str


def _bound(value: str) -> str | None:
    return None if value == _UNBOUND else value


def _files_newest_first(directory: Path) -> list[Path]:
    """``dienteazul.log`` then its rotated copies; ``.1`` is the newest."""
    backups = sorted(
        (p for p in directory.glob(f"{LOG_FILE_NAME}.*") if p.suffix.lstrip(".").isdigit()),
        key=lambda p: int(p.suffix.lstrip(".")),
    )
    return [p for p in [directory / LOG_FILE_NAME, *backups] if p.is_file()]


def _parse(text: str) -> list[Entry]:
    """The records of one file, oldest first.

    A line that does not open a record continues the previous one — a
    traceback, or a message with line breaks. Lines before the first
    record (the tail of one cut by a rollover) are dropped.
    """
    entries: list[Entry] = []
    lines: list[str] = []

    def close() -> None:
        if entries and lines:
            kept = lines[-_ENTRY_LINES:]
            entries[-1].message = "\n".join(scrub(line) for line in kept)

    for line in text.splitlines():
        match = _RECORD.match(line)
        if match is None:
            if entries:
                lines.append(line)
            continue
        close()
        # ``asctime`` is the writing process's local time, which is this one.
        at = datetime.strptime(match["at"], "%Y-%m-%d %H:%M:%S,%f").astimezone()
        entries.append(
            Entry(
                at=at,
                level=match["level"],
                logger=match["logger"],
                request_id=_bound(match["request_id"]),
                clinic_id=_bound(match["clinic_id"]),
                message="",
            )
        )
        lines = [match["message"]]
    close()
    return entries


def read(
    directory: Path, limit: int, *, min_level: str | None = None, query: str | None = None
) -> list[Entry]:
    """The most recent records, newest first.

    ``min_level`` keeps that level and the ones above it; ``query`` keeps
    the records whose logger, ids or scrubbed message contain it, ignoring
    case. Each file is read whole: they are bounded by ``LOG_MAX_BYTES``,
    and an older one is only opened while ``limit`` is not yet reached.
    """
    threshold = logging.getLevelName(min_level) if min_level else logging.NOTSET
    term = query.strip().lower() if query else ""
    out: list[Entry] = []
    try:
        for path in _files_newest_first(directory):
            text = path.read_text(encoding="utf-8", errors="replace")
            for entry in reversed(_parse(text)):
                level = logging.getLevelName(entry.level)
                if isinstance(level, int) and level < threshold:
                    continue
                if term:
                    haystack = " ".join(
                        [entry.logger, entry.request_id or "", entry.clinic_id or "", entry.message]
                    ).lower()
                    if term not in haystack:
                        continue
                out.append(entry)
                if len(out) >= limit:
                    return out
    except OSError:
        logger.exception("Cannot read the application log from %s", directory)
    return out
