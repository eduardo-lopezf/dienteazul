"""A whole copy of a deployment — its database and its uploaded files —
taken from one installation and put into another (ADR 0049 rule 4,
amended 2026-10-15).

The copy is one ``tar.gz``: a ``manifest.json``, the database as a
``pg_dump`` archive, and the storage folder under ``files/``. Putting it
into an installation **replaces** that installation: first a copy of what
it held is kept in its own backups folder, then the database is replaced
in one transaction — a failure leaves it as it was — and only then the
files.

Both installations must be on the same schema: the copy carries the
revisions it was taken at, and one taken at others is refused. Values
encrypted with an installation's ``SECRET_KEY`` (mail, VeriFactu and
WhatsApp credentials) travel as they are and do not open on the other
side; they are entered again there.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.tenancy.usage import BACKUPS_FOLDER

FORMAT = 1
MANIFEST = "manifest.json"
DATABASE = "database.dump"
FILES = "files"

#: A dump or a restore of a large deployment takes minutes, not hours.
_TIMEOUT_SECONDS = 1800


class SnapshotRefusedError(Exception):
    """The copy cannot go into this installation; the message says why."""


def libpq_dsn(sqlalchemy_url: str) -> str:
    """What ``pg_dump`` and ``psql`` accept for the URL a session uses."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")


def build(dsn: str, root: Path, dest: Path, manifest: dict) -> None:
    """Write the copy of the database at ``dsn`` and of the files under
    ``root`` to ``dest``. Blocking: call it off the event loop."""
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / DATABASE
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "-f", str(dump), dsn],
            check=True,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
        with tarfile.open(dest, "w:gz") as tar:
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(data)
            info.mtime = int(datetime.now(UTC).timestamp())
            tar.addfile(info, io.BytesIO(data))
            tar.add(dump, arcname=DATABASE)
            for child in sorted(root.iterdir()) if root.is_dir() else []:
                if child.name != BACKUPS_FOLDER:  # copies of earlier states stay behind
                    tar.add(child, arcname=f"{FILES}/{child.name}")


def read_manifest(archive: Path) -> dict:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.extractfile(MANIFEST)
            manifest = json.load(member) if member else None
    except (tarfile.TarError, OSError, KeyError, ValueError) as exc:
        raise SnapshotRefusedError("This is not a copy of a Diente Azul deployment") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise SnapshotRefusedError("This is not a copy of a Diente Azul deployment")
    return manifest


def check_versions(manifest: dict, current: list[str]) -> None:
    """Refuse a copy taken at other schema revisions than this one's."""
    theirs, ours = set(manifest.get("revisions", [])), set(current)
    if theirs != ours:
        raise SnapshotRefusedError(
            "Schema versions differ — only in the copy: "
            + (", ".join(sorted(theirs - ours)) or "none")
            + "; only here: "
            + (", ".join(sorted(ours - theirs)) or "none")
        )


def restore(dsn: str, root: Path, archive: Path) -> int:
    """Replace the database at ``dsn`` and the files under ``root`` with
    the copy in ``archive``. Returns how many files it put back. Blocking:
    call it off the event loop, with no transaction of the caller open on
    that database — replacing the schema would wait for it."""
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "r:gz") as tar:
        tar.extract(DATABASE, tmp, filter="data")
        _replace_database(dsn, Path(tmp) / DATABASE)

        # The database is the copy's now; the files follow it.
        if root.is_dir():
            for child in root.iterdir():
                if child.name == BACKUPS_FOLDER:
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        root.mkdir(parents=True, exist_ok=True)
        files = 0
        prefix = f"{FILES}/"
        for member in tar.getmembers():
            if not member.name.startswith(prefix):
                continue
            member.name = member.name.removeprefix(prefix)
            if not member.name or member.name.split("/", 1)[0] == BACKUPS_FOLDER:
                continue
            tar.extract(member, root, filter="data")
            files += member.isfile()
        return files


#: Run before the dump is loaded, in the same transaction: the schema is
#: emptied so the installation ends up holding the copy and nothing else.
_EMPTY_SCHEMA = b"SET lock_timeout = '60s';\nDROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n"


def _replace_database(dsn: str, dump: Path) -> None:
    """Empty the ``public`` schema and load the dump, in one transaction:
    if any statement fails, nothing was replaced."""
    to_sql = subprocess.Popen(
        ["pg_restore", "--no-owner", "--no-privileges", "-f", "-", str(dump)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    psql = subprocess.Popen(
        ["psql", "--no-psqlrc", "--quiet", "-v", "ON_ERROR_STOP=1", "--single-transaction", dsn],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert to_sql.stdout is not None and psql.stdin is not None
    try:
        psql.stdin.write(_EMPTY_SCHEMA)
        for line in to_sql.stdout:
            # A newer pg_dump writes a setting an older server does not know.
            if line.startswith(b"SET transaction_timeout"):
                continue
            psql.stdin.write(line)
        psql.stdin.close()
        dumped = to_sql.wait(timeout=_TIMEOUT_SECONDS)
        loaded = psql.wait(timeout=_TIMEOUT_SECONDS)
    except BaseException:
        to_sql.kill()
        psql.kill()
        raise
    if dumped != 0:
        raise RuntimeError(f"pg_restore failed: {to_sql.stderr.read().decode()[-500:]}")
    if loaded != 0:
        raise RuntimeError(f"psql failed: {psql.stderr.read().decode()[-500:]}")
