"""A session may not end in a way nobody can explain.

The incident this comes from: users thrown out mid-task, told their
session had expired, and nothing in the deployment able to say why.
``POST /auth/refresh`` answered 401 for seven different causes and logged
exactly one of them, so there was no line to find and no code to tell
them apart (ADR 0062).

Three rules, checked against the source rather than by hitting a route,
because what has to hold is a property of *every* refusal — including the
one somebody adds next year:

1. **Every 401 in the auth core goes through ``refusals.refuse``**, which
   cannot answer without logging. A bare ``HTTPException(401)`` is a
   refusal with no code and no line.
2. **Every code belongs to exactly one group.** The group decides the
   sentence the person reads, and an unclassified code would inherit
   "your session expired" — the wrong answer, silently.
3. **Every session endpoint is rate-limited per user**, never on the
   socket peer the BFF collapses everyone onto. That lives in
   ``test_rate_limit_storage.py``, next to the limiter it is about.

Same shape as ``test_pii_redaction_contract.py`` and
``test_error_catalog_contract.py``: the rule is read off the tree, and an
exception costs an allowlist entry somebody had to write on purpose.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.auth import refusals

pytestmark = pytest.mark.contract

AUTH_ROOT = Path(__file__).resolve().parents[1] / "app" / "core" / "auth"

# Names that may still raise a bare 401, each for a reason.
#
# ``credentials_exception`` is the token itself not holding up — missing,
# undecodable, the wrong type, a version that no longer matches. It is
# raised from eight branches of one dependency and carries no session
# facts worth a line; more to the point, an access token expiring after
# its fifteen minutes is the single most common 401 this API answers, and
# a WARNING per occurrence would bury the ones that mean something.
_BARE_401_ALLOWED: frozenset[str] = frozenset({"credentials_exception"})

# What the rule is actually about: refusing a session that **exists**.
# Refusing to *open* one is a different answer with a different reader —
# the person typing a password, who is told on the spot — so the login
# endpoint keeps its own 401. Adding a function here is a claim that its
# 401 can never leave somebody wondering why they were signed out.
_NOT_A_SESSION_REFUSAL: dict[str, str] = {
    "login": "wrong e-mail or password: no session existed to end",
}


def _module_sources() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(AUTH_ROOT.rglob("*.py"))
        if "migrations" not in path.parts
    ]


def _is_401(node: ast.expr) -> bool:
    """Does this ``raise`` argument name a 401?"""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr.startswith("HTTP_401"):
            return True
        if isinstance(child, ast.Constant) and child.value == 401:
            return True
    return False


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    """The function each line belongs to, for the allowlist above."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                # Innermost wins: a nested def is the closer owner.
                owner[line] = node.name
    return owner


def test_no_401_in_the_auth_core_is_raised_without_a_code_and_a_log_line() -> None:
    offenders: list[str] = []

    for path, tree in _module_sources():
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            if owner.get(node.lineno) in _NOT_A_SESSION_REFUSAL:
                continue
            raised = node.exc
            # ``raise credentials_exception`` — a name, not a call.
            if isinstance(raised, ast.Name):
                if raised.id not in _BARE_401_ALLOWED:
                    offenders.append(f"{path.name}:{node.lineno} raise {raised.id}")
                continue
            if not isinstance(raised, ast.Call) or not _is_401(raised):
                continue
            called = raised.func
            through_refusals = (
                isinstance(called, ast.Attribute)
                and called.attr == "refuse"
                or isinstance(called, ast.Name)
                and called.id == "refuse"
            )
            if not through_refusals:
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        "a 401 in the auth core must be raised through `refusals.refuse`, which names "
        "the case and logs it under this request's id — otherwise an incident cannot be "
        "explained afterwards (ADR 0062). Offenders: " + ", ".join(offenders)
    )


def _declared_codes() -> dict[str, str]:
    """Every ``NAME = "auth.…"`` in ``refusals.py``, by name."""
    tree = ast.parse((AUTH_ROOT / "refusals.py").read_text(encoding="utf-8"))
    codes: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Constant):
            continue
        if isinstance(node.value.value, str) and node.value.value.startswith("auth."):
            codes[target.id] = node.value.value
    return codes


def test_every_refusal_code_is_classified_exactly_once() -> None:
    declared = _declared_codes()
    assert declared, "no refusal codes found — has refusals.py moved?"

    groups = {
        "IDLE_CODES": refusals.IDLE_CODES,
        "REVOKED_CODES": refusals.REVOKED_CODES,
        "EXPIRED_CODES": refusals.EXPIRED_CODES,
    }

    for name, code in sorted(declared.items()):
        belongs = [group for group, codes in groups.items() if code in codes]
        assert belongs, (
            f"{name} ({code}) is in no group, so the login screen would call it "
            "'caducada' by default. Put it in IDLE_CODES, REVOKED_CODES or "
            "EXPIRED_CODES — the group is what the person reads (ADR 0062)."
        )
        assert len(belongs) == 1, f"{name} ({code}) is in {belongs}; the groups must not overlap"

    # And nothing classified that does not exist: a renamed code left
    # behind in a group is a rule that stopped covering anything.
    for group, codes in groups.items():
        unknown = set(codes) - set(declared.values())
        assert not unknown, f"{group} names codes that are not declared: {sorted(unknown)}"


def test_the_frontend_reads_the_same_three_groups() -> None:
    """The browser holds a copy of the table; this is the other half of
    `frontend/tests/session.test.ts`, which reads this file.

    Kept as an assertion here too so the backend suite fails on a group
    the frontend cannot possibly know about, without waiting for the
    frontend job.
    """
    path = Path(__file__).resolve().parents[2] / "frontend" / "app" / "utils" / "session.ts"
    if not path.exists():
        # The container mounts `backend/` alone, so the other half of the
        # repo is not there. CI runs this from a full checkout, and
        # `frontend/tests/session.test.ts` checks the same table from the
        # other side either way.
        pytest.skip("frontend tree not present in this checkout")
    mapping = path.read_text(encoding="utf-8")

    for group, codes in (
        ("IDLE_CODES", refusals.IDLE_CODES),
        ("REVOKED_CODES", refusals.REVOKED_CODES),
    ):
        for code in sorted(codes):
            assert f"'{code}'" in mapping, (
                f"{code} is in {group} but `frontend/app/utils/session.ts` does not list it, "
                "so the login screen would show the wrong sentence for it"
            )
