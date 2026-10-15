"""Undoing an import: removing exactly what it created, while nothing has
been built on it (ADR 0055).

**What it created** is known from a ledger, not guessed. While a job runs,
``CreatedRowsRecorder`` listens to its session and writes down every row
inserted through it — patients, their treatments, the accounts made for
professionals, a tooth's record, a budget's lines, a document. The mapping
table cannot answer this: it also names rows an import only *linked* to (a
cabinet matched by name, a catalogue item, the existing patient an
appointments sheet was attached to), and those are not the import's to
remove.

**What hangs from it** is found through the schema: any row whose foreign
key — or polymorphic ``owner_id`` — points at a row being removed. One
made by the import itself, or by a module reacting to it (a timeline
entry), goes too. One made **after** the import finished means the clinic
worked on the imported data — an appointment booked, a note written — and
the undo is refused, saying what was found: removing it would lose work
that is not the import's.

Undoing is the one hard delete of clinical rows the product does: rows
that should never have been there, removed before anyone relied on them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Table, delete, event, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

from .models import (
    EntityMapping,
    FileStaging,
    ImportCreatedRow,
    ImportJob,
    ImportWarning,
    RawEntity,
)

logger = logging.getLogger(__name__)

#: This module's own staging tables: not what an import brings.
_OWN_TABLES = frozenset(
    model.__tablename__
    for model in (ImportJob, EntityMapping, FileStaging, ImportWarning, RawEntity, ImportCreatedRow)
)
#: Rows reacting to the import (a timeline entry written by a handler)
#: land a little after it ends; past this, a new row is the clinic's work.
REACTION_WINDOW = timedelta(minutes=2)
_CHUNK = 1000


# --- The ledger -------------------------------------------------------------


class CreatedRowsRecorder:
    """Writes down every row its session inserts, until detached."""

    def __init__(self, job_id: UUID) -> None:
        self._job_id = job_id
        self._pending: list[dict[str, str | UUID]] = []

    def attach(self, db: AsyncSession) -> None:
        self._session = db.sync_session
        event.listen(self._session, "after_flush", self._after_flush)
        event.listen(self._session, "before_commit", self._before_commit)

    def detach(self) -> None:
        event.remove(self._session, "after_flush", self._after_flush)
        event.remove(self._session, "before_commit", self._before_commit)

    def _after_flush(self, session: Any, _context: Any) -> None:
        for obj in session.new:
            table = getattr(obj, "__table__", None)
            if table is None or table.name in _OWN_TABLES:
                continue
            keys = list(table.primary_key.columns)
            if len(keys) != 1:
                continue
            value = getattr(obj, keys[0].key, None)
            if value is None:
                continue
            self._pending.append(
                {
                    "job_id": self._job_id,
                    "table_name": table.name,
                    "pk_column": keys[0].name,
                    "row_key": str(value),
                }
            )

    def _before_commit(self, session: Any) -> None:
        if self._pending:
            rows, self._pending = self._pending, []
            session.connection().execute(insert(ImportCreatedRow.__table__), rows)


# --- Planning ---------------------------------------------------------------


@dataclass
class UndoPlan:
    #: table → keys of the rows to remove (created and hanging from them).
    rows: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    #: table → how many rows made after the import hang from it.
    blockers: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def count(self) -> int:
        return sum(len(keys) for keys in self.rows.values())


def _tables() -> dict[str, Table]:
    return {table.name: table for table in Base.metadata.sorted_tables}


def _pk(table: Table) -> Any:
    keys = list(table.primary_key.columns)
    return keys[0] if len(keys) == 1 else None


def _typed(column: Any, keys: set[str] | list[str]) -> list[Any]:
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        python_type = str
    if python_type is UUID:
        return [UUID(key) for key in keys]
    if python_type is int:
        return [int(key) for key in keys]
    return list(keys)


def _chunks(values: list[Any]) -> list[list[Any]]:
    return [values[i : i + _CHUNK] for i in range(0, len(values), _CHUNK)]


async def plan_undo(db: AsyncSession, job: ImportJob) -> UndoPlan:
    tables = _tables()
    plan = UndoPlan()
    ledger = await db.execute(
        select(ImportCreatedRow.table_name, ImportCreatedRow.row_key).where(
            ImportCreatedRow.job_id == job.id
        )
    )
    for table_name, key in ledger.all():
        if table_name in tables:
            plan.rows[table_name].add(key)

    cutoff = (job.completed_at or datetime.now(UTC)) + REACTION_WINDOW
    frontier = {name: set(keys) for name, keys in plan.rows.items()}
    while frontier:
        found: dict[str, set[str]] = defaultdict(set)
        every_key = {key for keys in frontier.values() for key in keys}
        for table in tables.values():
            pk = _pk(table)
            if pk is None or table.name in _OWN_TABLES:
                continue
            links: list[tuple[Any, set[str]]] = []
            for fk in table.foreign_keys:
                target = fk.column.table.name
                if target in frontier and fk.column is _pk(fk.column.table):
                    links.append((fk.parent, frontier[target]))
            if "owner_id" in table.c:  # polymorphic owners (notes, attachments)
                links.append((table.c.owner_id, every_key))
            for column, keys in links:
                for chunk in _chunks(_typed(column, keys)):
                    columns = [pk] + ([table.c.created_at] if "created_at" in table.c else [])
                    result = await db.execute(select(*columns).where(column.in_(chunk)))
                    for row in result.all():
                        key = str(row[0])
                        if key in plan.rows[table.name] or key in found[table.name]:
                            continue
                        made = row[1] if len(row) > 1 else None
                        if made is not None and made > cutoff:
                            plan.blockers[table.name] += 1
                        else:
                            found[table.name].add(key)
        for name, keys in found.items():
            plan.rows[name] |= keys
        frontier = {name: keys for name, keys in found.items() if keys}
    return plan


_LABELS = {
    "appointments": "citas",
    "clinical_notes": "notas clínicas",
    "treatments": "tratamientos",
    "treatment_plans": "planes",
    "planned_treatment_items": "tratamientos de un plan",
    "budgets": "presupuestos",
    "payments": "pagos",
    "invoices": "facturas",
    "documents": "documentos",
    "media_attachments": "adjuntos",
    "recalls": "recordatorios",
    "patients_clinical_allergy": "alergias",
    "consents_consent": "consentimientos",
}


def describe_blockers(plan: UndoPlan) -> str:
    found = ", ".join(
        f"{count} {_LABELS.get(table, table)}" for table, count in sorted(plan.blockers.items())
    )
    return (
        "No se puede deshacer: después de la importación se registraron datos nuevos sobre lo "
        f"importado ({found}). Deshacerla los borraría. Si vienen de otra importación, "
        "deshaz primero esa."
    )


# --- Removing ---------------------------------------------------------------


async def apply_undo(db: AsyncSession, job: ImportJob, plan: UndoPlan) -> list[str]:
    """Remove the plan's rows. Returns the storage paths of removed documents,
    to delete once the transaction has committed."""
    tables = _tables()
    files: list[str] = []
    if "documents" in plan.rows:
        documents = tables["documents"]
        for chunk in _chunks(_typed(_pk(documents), plan.rows["documents"])):
            result = await db.execute(
                select(documents.c.storage_path).where(_pk(documents).in_(chunk))
            )
            files += [path for (path,) in result.all() if path]

    # A row pointing at another of the same table (a credit note at its
    # invoice, a budget version at its parent): let go first.
    for name, keys in plan.rows.items():
        table = tables[name]
        pk = _pk(table)
        for fk in table.foreign_keys:
            if fk.column.table is table and fk.parent.nullable:
                for chunk in _chunks(_typed(pk, keys)):
                    await db.execute(
                        update(table).where(pk.in_(chunk)).values({fk.parent.name: None})
                    )

    # Children before parents: the schema's own dependency order, reversed.
    for table in reversed(Base.metadata.sorted_tables):
        keys = plan.rows.get(table.name)
        if not keys:
            continue
        pk = _pk(table)
        for chunk in _chunks(_typed(pk, keys)):
            await db.execute(delete(table).where(pk.in_(chunk)))

    # What named the removed rows — this job's and any other's — goes too.
    removed = [UUID(key) for keys in plan.rows.values() for key in keys if _is_uuid(key)]
    for chunk in _chunks(removed):
        await db.execute(
            delete(EntityMapping).where(
                EntityMapping.clinic_id == job.clinic_id, EntityMapping.dienteazul_id.in_(chunk)
            )
        )
    await db.execute(delete(EntityMapping).where(EntityMapping.job_id == job.id))
    await db.execute(delete(ImportCreatedRow).where(ImportCreatedRow.job_id == job.id))
    return files


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


async def remove_files(paths: list[str]) -> None:
    """Best effort, after the commit: a file left behind wastes space; a
    row left pointing at no file would break the gallery."""
    from app.modules.media.storage import get_storage_backend
    from app.modules.media.thumbnails import MEDIUM_SUFFIX, THUMB_SUFFIX

    storage = get_storage_backend()
    for path in paths:
        for variant in (path, f"{path}{THUMB_SUFFIX}", f"{path}{MEDIUM_SUFFIX}"):
            try:
                await storage.delete(variant)
            except Exception:  # noqa: BLE001 — a missing derivative is fine
                logger.info("undo: could not delete %s", variant)
