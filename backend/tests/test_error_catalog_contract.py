"""A failure has to be able to name its case.

``app/core/errors.py`` makes the bargain explicit: the person gets a
``reference``, the interface gets a ``category``, and whoever debugs
gets a ``code``. The code only means anything while every module keeps
its ``errors.json`` and the code that raises them in step, and nothing
enforced that: the catalogues were spot-checked from
``test_error_envelope.py`` by importing three of them by hand.

Two ways they drift, both found by reading the tree rather than by a
failing request:

- **A code that is raised and not defined.** ``<module>_error`` does
  ``ERROR_CATALOG[code]``, so the miss is a ``KeyError`` — an unhandled
  500 carrying ``internal.unhandled``, which is the one answer the
  catalogue exists to prevent. The risk is not hypothetical: three
  modules build their fallback code with an f-string
  (``f"billing.{resource}.invalid"``), so whether it resolves depends on
  what every call site passes, which no reader checks.
- **A code that is defined and unreachable.** Dead weight that reads
  like a contract. Eighteen of them predate this test and sit in
  ``_UNREACHABLE`` below.

Same shape as ``test_pii_redaction_contract.py``: the rule is checked
against the source, and an exception costs an allowlist line somebody
had to write on purpose.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import NamedTuple

import pytest

MODULES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules"

# The shape ``ErrorDefinition`` enforces on a code. Used here to tell a
# whole code from the prefix half of an f-string (``"billing."``), which
# shares the module name and is not one.
_CODE_SHAPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

# Modules that have not been through the error-catalogue refactor. They
# still raise bare ``HTTPException``, which stays valid — core
# categorises it from the status — it just carries no code. Removing an
# entry here is the last step of giving that module a catalogue, not a
# precondition for it.
_WITHOUT_CATALOG: frozenset[str] = frozenset({"copilot", "verifactu"})

# Defined, and nothing can reach it. Each entry is a decision: either
# the raise it belonged to is gone and the line should follow, or the
# code is about to be used and the author left it. They are grouped by
# why they are here, because the two groups want different fixes.
_UNREACHABLE: frozenset[str] = frozenset(
    {
        # Payload-shape refusals that Pydantic now answers before the
        # route runs, so the hand-written code never fires. Delete with
        # the schema work, not before — the validators are what has to
        # be shown to cover every case first.
        "cashbox.closing.amount_invalid",
        "cashbox.closing.reopen_reason_invalid",
        "cashbox.late_entry.kind_invalid",
        "cashbox.late_entry.resolution_invalid",
        "cashbox.movement.amount_invalid",
        "cashbox.movement.concept_invalid",
        "cashbox.movement.enum_invalid",
        "schedules.clinic_override.closed_with_shifts",
        "schedules.clinic_override.custom_hours_without_shifts",
        "schedules.override.invalid_date_range",
        "schedules.override.invalid_kind",
        "schedules.override.reason_too_long",
        "schedules.professional_override.custom_hours_without_shifts",
        "schedules.professional_override.unavailable_with_shifts",
        "schedules.shift.invalid_time_range",
        "schedules.weekday.out_of_range",
        "payments.payment.create_failed",
        # Not an error anybody raises: the string is the prefix of a log
        # line in ``record/service.py``. A catalogue entry that is really
        # a log tag — it belongs in one place or the other.
        "record.section.collection_failed",
    }
)


class Dynamic(NamedTuple):
    """A code assembled at runtime, e.g. ``f"billing.{resource}.invalid"``."""

    function: str
    parameter: str
    position: int | None
    prefix: str
    suffix: str


def _modules() -> list[Path]:
    return sorted(
        path
        for path in MODULES_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    )


def _with_catalog() -> list[Path]:
    return [m for m in _modules() if m.name not in _WITHOUT_CATALOG]


def _defined(module: Path) -> set[str]:
    payload = json.loads((module / "errors.json").read_text(encoding="utf-8"))
    return {entry["code"] for entry in payload["errors"]}


def _sources(module: Path) -> list[tuple[Path, ast.Module]]:
    trees = []
    for path in sorted(module.rglob("*.py")):
        try:
            trees.append((path, ast.parse(path.read_text(encoding="utf-8"))))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
    return trees


def _dynamic_codes(module: Path) -> list[Dynamic]:
    """The f-string code builders in a module's ``errors.py``."""
    tree = ast.parse((module / "errors.py").read_text(encoding="utf-8"))
    found: list[Dynamic] = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        params = [a.arg for a in func.args.args] + [a.arg for a in func.args.kwonlyargs]
        for node in ast.walk(func):
            if not isinstance(node, ast.JoinedStr) or len(node.values) != 3:
                continue
            head, slot, tail = node.values
            if not (isinstance(head, ast.Constant) and isinstance(tail, ast.Constant)):
                continue
            if not isinstance(slot, ast.FormattedValue) or not isinstance(slot.value, ast.Name):
                continue
            name = slot.value.id
            if name not in params or not head.value.startswith(f"{module.name}."):
                continue
            positional = [a.arg for a in func.args.args]
            found.append(
                Dynamic(
                    function=func.name,
                    parameter=name,
                    position=positional.index(name) if name in positional else None,
                    prefix=head.value,
                    suffix=tail.value,
                )
            )
    return found


def _literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _code_literal(node: ast.expr | None, module: str) -> str | None:
    """A string that is this module's code, not just text that starts like one."""
    value = _literal(node)
    if value and value.startswith(f"{module}.") and _CODE_SHAPE.match(value):
        return value
    return None


def _called_name(call: ast.Call) -> str:
    func = call.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")


def _raised_codes(module: Path) -> list[tuple[Path, int, str]]:
    """Every code a call site hands to an error helper, literal or built.

    ``errors.py`` itself is read too: its translation tables are where
    most codes are named, and a typo there is the same 500.
    """
    dynamic = {d.function: d for d in _dynamic_codes(module)}
    raised: list[tuple[Path, int, str]] = []
    for path, tree in _sources(module):
        if path.name == "errors.py":
            for node in ast.walk(tree):
                code = _code_literal(node, module.name) if isinstance(node, ast.Constant) else None
                if code:
                    raised.append((path, node.lineno, code))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            builder = dynamic.get(name)
            if builder is not None:
                value = next(
                    (_literal(kw.value) for kw in node.keywords if kw.arg == builder.parameter),
                    None,
                )
                if value is None and builder.position is not None:
                    if len(node.args) > builder.position:
                        value = _literal(node.args[builder.position])
                if value is not None:
                    raised.append((path, node.lineno, f"{builder.prefix}{value}{builder.suffix}"))
                continue
            if name.endswith("_error") and node.args:
                code = _literal(node.args[0])
                if code:
                    raised.append((path, node.lineno, code))
    return raised


@pytest.mark.parametrize("module", _with_catalog(), ids=lambda m: m.name)
def test_a_module_ships_its_error_catalogue(module: Path) -> None:
    """Both halves, or the module cannot name any failure it has."""
    assert (module / "errors.json").is_file(), (
        f"{module.name} has no errors.json. Add one, or record the module in "
        "_WITHOUT_CATALOG with the reason."
    )
    assert (module / "errors.py").is_file(), f"{module.name} has no errors.py loader"


@pytest.mark.parametrize("module", _with_catalog(), ids=lambda m: m.name)
def test_a_code_says_which_module_it_came_from(module: Path) -> None:
    """``<module>.<resource>.<case>`` — the prefix is what makes it findable."""
    foreign = sorted(c for c in _defined(module) if not c.startswith(f"{module.name}."))
    assert not foreign, f"{module.name}/errors.json defines codes of another module: {foreign}"


@pytest.mark.parametrize("module", _with_catalog(), ids=lambda m: m.name)
def test_every_raised_code_is_in_the_catalogue(module: Path) -> None:
    """The ``KeyError`` case: a code nobody defined is an unhandled 500."""
    defined = _defined(module)
    missing = [
        f"{path.relative_to(MODULES_ROOT)}:{line} raises {code!r}"
        for path, line, code in _raised_codes(module)
        if code not in defined
    ]
    assert not missing, (
        f"{module.name}: codes raised but not defined in errors.json — each is a "
        "KeyError, i.e. a 500 carrying internal.unhandled:\n  " + "\n  ".join(missing)
    )


@pytest.mark.parametrize("module", _with_catalog(), ids=lambda m: m.name)
def test_every_defined_code_can_be_reached(module: Path) -> None:
    """A catalogue entry nothing raises is a contract that is not one.

    Reachability is deliberately generous: a code counts as reachable if
    its literal appears anywhere in the module, or if a dynamic builder
    could produce it. That over-approximates — a dead
    ``treatment_plan.x.invalid`` hides behind the builder's shape — and
    it is the right way round, because this test's job is to catch the
    entry nobody wired up at all, not to adjudicate every branch.
    """
    defined = _defined(module)
    literals = {code for _, _, code in _raised_codes(module)}
    for path, tree in _sources(module):
        for node in ast.walk(tree):
            code = _literal(node) if isinstance(node, ast.Constant) else None
            if code in defined:
                literals.add(code)
    for builder in _dynamic_codes(module):
        literals |= {
            code
            for code in defined
            if code.startswith(builder.prefix) and code.endswith(builder.suffix)
        }
    unreachable = sorted(defined - literals - _UNREACHABLE)
    assert not unreachable, (
        f"{module.name}: defined in errors.json and raised by nothing — delete them, "
        f"or record them in _UNREACHABLE with the reason:\n  " + "\n  ".join(unreachable)
    )


@pytest.mark.parametrize("module", _with_catalog(), ids=lambda m: m.name)
def test_a_module_with_a_catalogue_does_not_raise_a_bare_httpexception(module: Path) -> None:
    """Bare ``HTTPException`` is valid core-side, but it carries no code.

    Inside a module that has a catalogue it is a regression: the case was
    nameable and the raise did not name it.
    """
    bare: list[str] = []
    for path, tree in _sources(module):
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                if _called_name(node.exc) == "HTTPException":
                    bare.append(f"{path.relative_to(MODULES_ROOT)}:{node.lineno}")
    assert not bare, (
        f"{module.name} raises HTTPException directly, so the failure reaches the "
        f"caller with no code. Use the module's error helper:\n  " + "\n  ".join(bare)
    )
