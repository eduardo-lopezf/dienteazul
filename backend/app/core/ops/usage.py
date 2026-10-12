"""What each clinic consumes, and what happened in it, for an operator.

Everything here answers to the control plane (ADR 0049 rule 4), so it
returns **sizes, counts and identifiers, never content**: how many bytes,
which user id signed in, which table gained a row. No name of a person,
no contact detail, no clinical text.

The tables are found by asking the database which ones carry a
``clinic_id``, not by importing models: core may not import a module
(ADR 0039), and a module that was uninstalled has no table to count.

A database has no per-clinic size — clinics share its tables — so a
clinic's figure is a share: each table's size on disk, split by how many
of its rows belong to each clinic. What no clinic owns (tables without a
``clinic_id``, the catalogue, empty tables' overhead) is the rest.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import AuthSession, Clinic, ClinicMembership
from app.core.auth.privacy_agreement import PRIVACY_AGREEMENT_VERSION
from app.core.tenancy.usage import FileUsage, cached_file_usage, file_usage

#: How long a measurement is good for. Counting every clinic's rows in
#: every table is a scan of the database; the answer barely moves in ten
#: minutes, and ``refresh`` measures again now.
USAGE_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class ClinicUsage:
    id: UUID
    name: str
    created_at: datetime
    #: What its limits go by.
    account_tier: str
    #: Its own limits, over its tier's; a key absent inherits.
    limits: dict[str, int | None]
    #: Apps chosen for it at creation; ``None`` means all of them.
    apps: list[str] | None
    users: int
    database_bytes: int
    database_rows: int
    storage_bytes: int
    storage_files: int


@dataclass(frozen=True, slots=True)
class DeploymentUsage:
    database_bytes: int
    #: The part of the database no clinic owns.
    shared_database_bytes: int
    storage_bytes: int
    storage_files: int
    measured_at: datetime
    clinics: list[ClinicUsage] = field(default_factory=list)


#: A session counts as current while its last token is this fresh. The
#: app swaps tokens every quarter of an hour while someone uses it and
#: ends a session left idle for an hour (ADR 0030); a refresh token on
#: its own lives a week, long after its tab was closed.
SESSION_WINDOW = timedelta(hours=1)
#: Without a sign-in for this long, a clinic has no recent activity.
RECENT_WINDOW = timedelta(days=15)
#: How long a clinic stays deactivated before it may be deleted for good.
DELETION_WAIT = timedelta(days=10)


@dataclass(frozen=True, slots=True)
class ClinicState:
    """Where a clinic stands right now. Never cached, unlike its sizes."""

    #: ``deactivated`` | ``active`` (someone is signed in) | ``offline`` |
    #: ``inactive`` (no sign-in within ``RECENT_WINDOW``, or ever)
    status: str
    last_access_at: datetime | None
    deactivated_at: datetime | None
    #: From when a deactivated clinic may be deleted for good.
    deletable_from: datetime | None
    #: Where its holder stands with the privacy agreement: ``accepted`` |
    #: ``outdated`` (accepted a version that is no longer in force, and is
    #: being asked again) | ``declined`` | ``pending`` (the welcome is not
    #: over) | ``not_asked``
    #: (a clinic nobody took through the welcome).
    privacy: str = "not_asked"
    #: When it was accepted or declined.
    privacy_at: datetime | None = None
    #: The version of the agreement that was accepted, where one was kept.
    privacy_version: str | None = None


async def clinic_states(db: AsyncSession) -> dict[UUID, ClinicState]:
    now = datetime.now(UTC)
    members = select(ClinicMembership.clinic_id, AuthSession).join(
        AuthSession, AuthSession.user_id == ClinicMembership.user_id
    )
    # A session belongs to a user, not to a clinic: someone who works in
    # two clinics counts in both.
    last_access = dict(
        (
            await db.execute(
                select(ClinicMembership.clinic_id, func.max(AuthSession.created_at))
                .join(AuthSession, AuthSession.user_id == ClinicMembership.user_id)
                .group_by(ClinicMembership.clinic_id)
            )
        ).all()
    )
    signed_in = set(
        await db.scalars(
            members.with_only_columns(ClinicMembership.clinic_id)
            .where(
                AuthSession.revoked_at.is_(None),
                AuthSession.rotated_at.is_(None),
                AuthSession.expires_at > now,
                AuthSession.created_at >= now - SESSION_WINDOW,
            )
            .distinct()
        )
    )

    states: dict[UUID, ClinicState] = {}
    clinics = await db.execute(
        select(
            Clinic.id,
            Clinic.deactivated_at,
            Clinic.onboarding_pending,
            Clinic.privacy_accepted_at,
            Clinic.privacy_declined_at,
            Clinic.privacy_accepted_version,
        )
    )
    for clinic_id, deactivated_at, pending, accepted_at, declined_at, version in clinics:
        if declined_at is not None:
            privacy, privacy_at = "declined", declined_at
        elif accepted_at is not None:
            current = version == PRIVACY_AGREEMENT_VERSION
            privacy, privacy_at = ("accepted" if current else "outdated"), accepted_at
        else:
            privacy, privacy_at = ("pending" if pending else "not_asked"), None
        last = last_access.get(clinic_id)
        if deactivated_at is not None:
            status = "deactivated"
        elif clinic_id in signed_in:
            status = "active"
        elif last is None or last < now - RECENT_WINDOW:
            status = "inactive"
        else:
            status = "offline"
        states[clinic_id] = ClinicState(
            status=status,
            last_access_at=last,
            deactivated_at=deactivated_at,
            deletable_from=deactivated_at + DELETION_WAIT if deactivated_at else None,
            privacy=privacy,
            privacy_at=privacy_at,
            privacy_version=version if privacy in ("accepted", "outdated") else None,
        )
    return states


@dataclass(frozen=True, slots=True)
class LogEntry:
    at: datetime
    #: ``login`` | ``logout`` | ``session_revoked`` | ``record_created``
    kind: str
    user_id: UUID | None = None
    role: str | None = None
    #: The table that gained a row, for ``record_created``.
    area: str | None = None


def _quoted(table: str) -> str:
    return '"' + table.replace('"', '""') + '"'


async def _tables_with(db: AsyncSession, *columns: str) -> list[str]:
    """Tables of the application that have every one of ``columns``."""
    rows = await db.execute(
        text(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = current_schema() AND t.table_type = 'BASE TABLE' "
            "  AND c.column_name = ANY(:columns) "
            "GROUP BY c.table_name HAVING count(*) = :wanted ORDER BY c.table_name"
        ),
        {"columns": list(columns), "wanted": len(columns)},
    )
    return list(rows.scalars())


async def _database_shares(db: AsyncSession) -> dict[UUID, tuple[int, int]]:
    """``{clinic_id: (bytes, rows)}`` — each clinic's share of the tables
    that hold a ``clinic_id``."""
    shares: dict[UUID, tuple[int, int]] = {}
    for table in await _tables_with(db, "clinic_id"):
        name = _quoted(table)
        rows = (
            await db.execute(
                # The table name reaches the query twice, and only one of
                # those is an identifier: `FROM` needs it spelled out,
                # `pg_total_relation_size` takes it as a *value*, so it
                # binds. Interpolating it there put a catalog name inside a
                # string literal that `_quoted` does not escape for.
                # `CAST(... AS regclass)` and not `:relation::regclass`:
                # the colons of a Postgres cast swallow the parameter, and
                # `text()` sends the name through as literal SQL.
                text(
                    f"SELECT clinic_id, count(*), pg_total_relation_size(CAST(:relation AS regclass)) "  # noqa: S608
                    f"FROM {name} GROUP BY clinic_id"
                ),
                {"relation": name},
            )
        ).all()
        total = sum(count for _, count, _ in rows)
        for clinic_id, count, size in rows:
            if clinic_id is None:  # a row every clinic shares
                continue
            held_bytes, held_rows = shares.get(clinic_id, (0, 0))
            shares[clinic_id] = (held_bytes + size * count // total, held_rows + count)
    return shares


def _clinic_folders(root: Path, clinic_ids: list[UUID]) -> dict[UUID, FileUsage]:
    """What each clinic's folder holds. Files are stored under
    ``<clinic_id>/…``; blocking, so it is called off the event loop."""
    return {clinic_id: file_usage(root / str(clinic_id)) for clinic_id in clinic_ids}


async def measure(db: AsyncSession, storage_root: Path, *, refresh: bool) -> DeploymentUsage:
    clinics = list(await db.scalars(select(Clinic).order_by(Clinic.name)))
    users = dict(
        (
            await db.execute(
                select(ClinicMembership.clinic_id, func.count()).group_by(
                    ClinicMembership.clinic_id
                )
            )
        ).all()
    )
    shares = await _database_shares(db)
    database_bytes = await db.scalar(text("SELECT pg_database_size(current_database())"))
    files = await cached_file_usage(storage_root, refresh=refresh)
    folders = await asyncio.to_thread(_clinic_folders, storage_root, [c.id for c in clinics])

    return DeploymentUsage(
        database_bytes=database_bytes,
        shared_database_bytes=max(0, database_bytes - sum(b for b, _ in shares.values())),
        storage_bytes=files.usage.total_bytes,
        storage_files=files.usage.file_count,
        measured_at=datetime.now(UTC),
        clinics=[
            ClinicUsage(
                id=clinic.id,
                name=clinic.name,
                created_at=clinic.created_at,
                account_tier=clinic.account_tier,
                limits=clinic.limits or {},
                apps=clinic.apps,
                users=users.get(clinic.id, 0),
                database_bytes=shares.get(clinic.id, (0, 0))[0],
                database_rows=shares.get(clinic.id, (0, 0))[1],
                storage_bytes=folders[clinic.id].total_bytes,
                storage_files=folders[clinic.id].file_count,
            )
            for clinic in clinics
        ],
    )


# Per process, like the file count it builds on: a cache, never the only
# copy of anything (ADR 0051).
_measured: dict[Path, DeploymentUsage] = {}
_measuring = asyncio.Lock()


async def cached_measure(
    db: AsyncSession, storage_root: Path, *, refresh: bool = False
) -> DeploymentUsage:
    """``measure``, at most once per ``USAGE_TTL`` unless ``refresh``."""
    async with _measuring:
        known = _measured.get(storage_root)
        if known is None or refresh or datetime.now(UTC) - known.measured_at >= USAGE_TTL:
            known = _measured[storage_root] = await measure(db, storage_root, refresh=refresh)
        return known


async def _accesses(db: AsyncSession, clinic_id: UUID, limit: int) -> list[LogEntry]:
    """Sign-ins and sign-outs of the clinic's members, newest first.

    A login opens a family of refresh tokens (``auth.sessions``); the
    family's first row is the login, and a row revoked by ``logout`` or
    ``reuse`` is how it ended.
    """
    members = (
        select(ClinicMembership.user_id, ClinicMembership.role)
        .where(ClinicMembership.clinic_id == clinic_id)
        .subquery()
    )
    logins = await db.execute(
        select(func.min(AuthSession.created_at).label("at"), AuthSession.user_id, members.c.role)
        .join(members, members.c.user_id == AuthSession.user_id)
        .group_by(AuthSession.family_id, AuthSession.user_id, members.c.role)
        .order_by(text("at DESC"))
        .limit(limit)
    )
    endings = await db.execute(
        select(
            func.max(AuthSession.revoked_at).label("at"),
            AuthSession.user_id,
            members.c.role,
            AuthSession.revoked_reason,
        )
        .join(members, members.c.user_id == AuthSession.user_id)
        .where(AuthSession.revoked_reason.in_(("logout", "reuse")))
        .group_by(
            AuthSession.family_id, AuthSession.user_id, members.c.role, AuthSession.revoked_reason
        )
        .order_by(text("at DESC"))
        .limit(limit)
    )
    return [
        *(
            LogEntry(at=at, kind="login", user_id=user_id, role=role)
            for at, user_id, role in logins
        ),
        *(
            LogEntry(
                at=at,
                kind="logout" if reason == "logout" else "session_revoked",
                user_id=user_id,
                role=role,
            )
            for at, user_id, role, reason in endings
        ),
    ]


async def _activity(db: AsyncSession, clinic_id: UUID, limit: int) -> list[LogEntry]:
    """The clinic's newest rows, as *when* and *in which table* — nothing
    of what they say, and not who wrote them: few tables record that."""
    tables = await _tables_with(db, "clinic_id", "created_at")
    if not tables:
        return []
    # `FROM` needs the identifier written out; the same name as the `area`
    # label is a value and binds. It used to be interpolated into a string
    # literal, which `_quoted` does not escape for. The cast is explicit
    # because a bare parameter inside a UNION leaves the server with no
    # type to infer.
    newest = " UNION ALL ".join(
        f"(SELECT created_at AS at, CAST(:area_{index} AS text) AS area FROM {_quoted(table)} "  # noqa: S608
        f"WHERE clinic_id = :clinic_id AND created_at IS NOT NULL "
        f"ORDER BY created_at DESC LIMIT :limit)"
        for index, table in enumerate(tables)
    )
    rows = await db.execute(
        text(f"SELECT at, area FROM ({newest}) AS newest ORDER BY at DESC LIMIT :limit"),
        {
            "clinic_id": clinic_id,
            "limit": limit,
            **{f"area_{index}": table for index, table in enumerate(tables)},
        },
    )
    return [LogEntry(at=at, kind="record_created", area=area) for at, area in rows]


async def clinic_log(db: AsyncSession, clinic_id: UUID, limit: int) -> list[LogEntry]:
    """Accesses and activity of one clinic, newest first."""
    entries = [*await _accesses(db, clinic_id, limit), *await _activity(db, clinic_id, limit)]
    return sorted(entries, key=lambda entry: entry.at, reverse=True)[:limit]
