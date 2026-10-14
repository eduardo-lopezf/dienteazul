"""DPMF writer — the export side of the reader in this package.

Writes the same layout the reader opens and dental-bridge produces: a
SQLite file with ``_meta``, ``_entities``, one table per entity type,
``_files`` and ``_warnings``, its logical integrity hash in ``_meta``,
then zstd-compressed and, with a passphrase, wrapped in a DPME envelope.
What it writes is checked by reading it back with :func:`open_dpmf`.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .compress import compress_to
from .crypto import encrypt_to
from .integrity import compute_logical_hash, is_safe_identifier

FORMAT_VERSION = "0.1"
#: Version of each entity table's row shape, hashed with ``_entities``.
SCHEMA_VERSION = "1"


def _json(value: Any) -> str:
    # Sorted keys: the same row always serialises — and hashes — the same.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class DpmfWriter:
    """Accumulates rows into a plain SQLite DPMF at ``path``."""

    def __init__(self, path: Path, *, source_system: str) -> None:
        self._conn = sqlite3.connect(path)
        self._source_system = source_system
        self._counts: dict[str, int] = {}
        self._blobs = 0
        self._conn.executescript(
            """
            CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE _entities (
                entity_type TEXT PRIMARY KEY,
                row_count INTEGER NOT NULL,
                schema_version TEXT NOT NULL
            );
            CREATE TABLE _files (
                canonical_uuid TEXT PRIMARY KEY,
                parent_entity_type TEXT,
                parent_canonical_uuid TEXT,
                relative_path TEXT,
                declared_size_bytes INTEGER,
                sha256 TEXT,
                mime_hint TEXT
            );
            CREATE TABLE _warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT,
                source_id TEXT,
                severity TEXT NOT NULL,
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                raw_data TEXT
            );
            """
        )

    def add(
        self,
        entity_type: str,
        *,
        canonical_uuid: str,
        source_id: str,
        payload: dict[str, Any],
        raw: dict[str, Any] | None = None,
    ) -> None:
        if not is_safe_identifier(entity_type):
            raise ValueError(f"unsafe entity_type identifier: {entity_type!r}")
        if entity_type not in self._counts:
            self._conn.execute(
                f'CREATE TABLE "{entity_type}" ('
                "canonical_uuid TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
                "source_system TEXT NOT NULL, payload TEXT NOT NULL, "
                "raw_source_data TEXT NOT NULL, extracted_at TEXT NOT NULL)"
            )
            self._counts[entity_type] = 0
        self._conn.execute(
            f'INSERT INTO "{entity_type}" VALUES (?, ?, ?, ?, ?, ?)',
            (
                canonical_uuid,
                source_id,
                self._source_system,
                _json(payload),
                _json(raw or {}),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._counts[entity_type] += 1

    def add_blob(self, canonical_uuid: str, data: bytes) -> None:
        """Embed a file's bytes. Not part of dental-bridge's layout — whose
        files travel apart, through the sync agent — and not hashed with
        the rest: the row that names the file carries its sha256, and the
        importer checks the bytes against it."""
        if not self._blobs:
            self._conn.execute(
                "CREATE TABLE _blobs (canonical_uuid TEXT PRIMARY KEY, data BLOB NOT NULL)"
            )
        self._conn.execute("INSERT INTO _blobs VALUES (?, ?)", (canonical_uuid, data))
        self._blobs += 1

    def warn(self, entity_type: str | None, source_id: str | None, code: str, message: str) -> None:
        self._conn.execute(
            "INSERT INTO _warnings (entity_type, source_id, severity, code, message, raw_data) "
            "VALUES (?, ?, 'warn', ?, ?, NULL)",
            (entity_type, source_id, code, message),
        )

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def finish(self, meta: dict[str, str]) -> str:
        """Close the file: counts, ``_meta`` and the integrity hash. Returns it."""
        self._conn.executemany(
            "INSERT INTO _entities VALUES (?, ?, ?)",
            [(name, count, SCHEMA_VERSION) for name, count in sorted(self._counts.items())],
        )
        integrity = compute_logical_hash(self._conn)
        rows = {
            **meta,
            "format_version": FORMAT_VERSION,
            "source_system": self._source_system,
            "created_at": datetime.now(UTC).isoformat(),
            "integrity_hash": integrity,
            "embedded_files": str(self._blobs),
        }
        self._conn.executemany("INSERT INTO _meta VALUES (?, ?)", sorted(rows.items()))
        self._conn.commit()
        self._conn.close()
        return integrity


def package(plain: Path, destination: Path, *, passphrase: str) -> None:
    """Compress the finished SQLite and seal it with ``passphrase``."""
    with tempfile.TemporaryDirectory(prefix="dpmf-out-") as tmp:
        compressed = Path(tmp) / "inner.zst"
        compress_to(plain, compressed)
        encrypt_to(compressed, destination, passphrase=passphrase, inner_layout="zstd")
