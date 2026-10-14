"""SQL is not built by pasting strings together.

ADR 0029, invariant 4. Injection is closed by construction here — every
query in request-handling code goes through SQLAlchemy with bound
parameters — so this file is not a scanner hunting for a hole. It is a
ratchet: it makes the *next* f-string in a SQL call an explicit decision
instead of a diff nobody looked at twice.

The scan is an AST walk rather than a grep, because the thing that
matters is not that ``text()`` appears but that its argument was
assembled from parts. ``sa.text("... WHERE id = :id")`` is exactly right
and must not be flagged; ``sa.text(f"... {table}")`` must be, even when
``table`` is a literal three lines up.

Entries in the allowlist are promises, in the shape
``"path/to/file.py::function"``. Keyed by function rather than by line
so an unrelated edit above does not invalidate them, and rather than by
file so a *new* interpolation somewhere else in an already-listed file
is still caught — ``treatment_plan/service.py`` is 1500 lines, and
listing the whole file would exempt most of the module's SQL.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# Calls whose first argument is executed as SQL.
SQL_CALLS = frozenset({"text", "sa_text", "execute", "exec_driver_sql", "scalar", "scalars"})

ALLOWED: dict[str, str] = {
    # --- Runtime code ----------------------------------------------------
    # The interpolated fragments (tab_where, extra_where, order_by) come
    # from a closed if/elif of literals a few lines above; every value
    # that originates with the caller travels as a bound :param. Safe,
    # and one wired-up `?sort=` away from not being — which is the whole
    # reason this file exists.
    "modules/treatment_plan/service.py::list_pipeline": (
        "tab_where / extra_where / order_by are literals from a closed if/elif; "
        "user values are bound parameters"
    ),
    # SQLite, over the uploaded import file, on a throwaway connection.
    # An identifier cannot be bound, so the entity table name is
    # interpolated — after `is_safe_identifier`, which is the guard, not
    # the comment.
    "modules/migration_import/dpmf/reader.py::entity_iter": (
        "SQLite identifier cannot be bound; validated by is_safe_identifier first"
    ),
    "modules/migration_import/dpmf/integrity.py::compute_logical_hash": (
        "SQLite identifier cannot be bound; validated by is_safe_identifier first"
    ),
    # The export's writer names a table after the entity type it holds —
    # a constant of `export.py`, checked by is_safe_identifier all the same.
    "modules/migration_import/dpmf/writer.py::add": (
        "SQLite identifier cannot be bound; validated by is_safe_identifier first"
    ),
    # The usage report sweeps every table that carries a `clinic_id`,
    # so the table name is the query. It comes from `information_schema`
    # of the current schema — never from a request — and reaches the SQL
    # through `_quoted`, which doubles any embedded quote, so it is a
    # quoted identifier and nothing else. Where the same name is a
    # *value* (the `pg_total_relation_size` argument, the `area` label)
    # it is bound: interpolating it there put a catalog name inside a
    # string literal, which `_quoted` does not escape for.
    # Deleting a clinic walks the foreign keys down from `clinics`, so
    # every table and column it names comes from the catalog, and the
    # quoting is done there rather than here: table names arrive as
    # `conrelid::regclass::text` and columns through `quote_ident`, both
    # of which quote whatever needs it. The one `where` that is not built
    # from those is the literal `id = :clinic_id` the walk starts with,
    # and the clinic id travels bound all the way down.
    "core/ops/purge.py::_delete": (
        "table and column names come quoted from the catalog (regclass::text, quote_ident); "
        "the clinic id is a bound parameter"
    ),
    "core/ops/usage.py::_database_shares": (
        "table name from information_schema, quoted by _quoted; the size argument is bound"
    ),
    "core/ops/usage.py::_activity": (
        "table name from information_schema, quoted by _quoted; the area label is bound"
    ),
    # --- Migrations ------------------------------------------------------
    # Alembic runs these with no request and no user input; each
    # interpolates a table name or an enum value from a literal in the
    # same file. They are listed rather than exempted wholesale because a
    # data migration is where this codebase has already been hurt once
    # (sch_0002 took a deploy down over constraint ordering).
    "modules/agenda/migrations/versions/ag_0002_status_lifecycle.py::upgrade": (
        "status values joined from the module-level STATUSES literal"
    ),
    "modules/schedules/migrations/versions/"
    "sch_0002_use_directory_professionals.py::_reverse_migrate_profiles": (
        "table name from a literal tuple; clinic_id and user_id are bound"
    ),
    "modules/treatment_plan/migrations/versions/"
    "tp_0007_use_directory_professionals.py::_migrate_column": (
        "table name is a literal argument from upgrade(); everything else is bound"
    ),
}


def _dynamic_kind(node: ast.expr) -> str | None:
    """Name the way ``node`` was assembled, or None if it is a plain literal."""
    if isinstance(node, ast.JoinedStr):
        return "f-string"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return "+ concatenation"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return "%-formatting"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return ".format()"
    return None


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _offenders() -> dict[str, str]:
    """Map ``"path::function"`` to a description of what it builds."""
    found: dict[str, str] = {}

    for path in sorted(APP_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue

        relative = str(path.relative_to(APP_ROOT))

        # Walk each scope separately so a hit can be attributed to the
        # function that contains it. Nested defs report under their own
        # name, which is precise enough and keeps the walk trivial.
        scopes: list[tuple[str, ast.AST]] = [("<module>", tree)]
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                scopes.append((node.name, node))

        for scope_name, scope in scopes:
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                if _called_name(node) not in SQL_CALLS:
                    continue
                for arg in node.args:
                    kind = _dynamic_kind(arg)
                    if kind:
                        found[f"{relative}::{scope_name}"] = f"line {node.lineno}, {kind}"

    # A hit inside a function is also reachable from the module walk;
    # prefer the function attribution and drop the duplicate.
    attributed = {key.split("::")[0] for key in found if not key.endswith("::<module>")}
    return {
        key: why
        for key, why in found.items()
        if not (key.endswith("::<module>") and key.split("::")[0] in attributed)
    }


def test_no_new_sql_is_built_from_parts() -> None:
    offenders = _offenders()
    unlisted = {key: why for key, why in offenders.items() if key not in ALLOWED}

    assert not unlisted, (
        "SQL assembled from string parts. Bind the values as parameters "
        "(:name) instead. If the fragment is an identifier — which cannot "
        "be bound — validate it and add an entry to ALLOWED in this file "
        f"saying why it is safe: {sorted(unlisted.items())}"
    )


def test_the_allowlist_has_no_stale_entries() -> None:
    """An exemption that outlives its code is an exemption nobody reviews."""
    stale = sorted(set(ALLOWED) - set(_offenders()))

    assert not stale, f"Allowlisted call sites that no longer build SQL from parts: {stale}"


def test_the_scan_would_notice_a_new_offender() -> None:
    """The assertions above are negatives; prove the walk actually sees one."""
    tree = ast.parse('table = "patients"\ndb.execute(f"SELECT * FROM {table}")\n')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))

    assert _called_name(call) == "execute"
    assert _dynamic_kind(call.args[0]) == "f-string"


def test_a_bound_parameter_is_not_flagged() -> None:
    """And that it does not fire on the form everything should be using."""
    tree = ast.parse('sa.text("SELECT * FROM patients WHERE id = :id")\n')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))

    assert _dynamic_kind(call.args[0]) is None
