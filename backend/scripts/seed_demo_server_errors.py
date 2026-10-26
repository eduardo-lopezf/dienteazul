#!/usr/bin/env python3
"""Write five sample server errors so the control panel has something to show.

``GET /api/v1/ops/errors`` reads ``<ERROR_LOG_DIR>/errors.log`` (ADR
0060). On a deployment that has not failed yet the panel is empty, which
looks the same as a panel that is broken — this fills it with five
occurrences of the kinds that actually happen, so the view, its columns
and its ordering can be seen working.

They go through ``server_errors.record``, the same path a real failure
takes, so what lands on disk is exactly what a real one would: the same
fields, the same scrubbing of quoted values. Each sample deliberately
carries an e-mail, a phone or a constraint value, so the panel can be
checked for what it must *not* show.

Usage, from ``backend/``::

    python scripts/seed_demo_server_errors.py          # write five
    python scripts/seed_demo_server_errors.py --clear  # forget them first

This is demo data. The panel's own ``DELETE /api/v1/ops/errors`` removes
them, and so does ``--clear``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://stub:stub@localhost:5432/stub")
os.environ.setdefault("SECRET_KEY", "server-error-seed-stub-key-32chars-minimum")
os.environ.setdefault("ENVIRONMENT", "development")

from app.core import server_errors  # noqa: E402


def _raised(exc: BaseException) -> BaseException:
    """``exc`` with a real traceback, so the sample has frames like any other."""
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001 — re-raised below as data
        return caught


class _IntegrityError(Exception):
    """Stands in for ``sqlalchemy.exc.IntegrityError`` without importing it."""


SAMPLES: list[tuple[BaseException, str, str]] = [
    (
        _IntegrityError(
            'duplicate key value violates unique constraint "users_email_key"\n'
            "DETAIL:  Key (email)=(ana.perez@example.com) already exists.\n"
            "[parameters: ('ana.perez@example.com',)]"
        ),
        "POST",
        "/api/v1/auth/register",
    ),
    (
        KeyError("treatment_plan.prescription.invalid"),
        "POST",
        "/api/v1/treatment-plans/{plan_id}/items/{item_id}/prescriptions",
    ),
    (
        TimeoutError("connection to kapso timed out after 30s"),
        "POST",
        "/api/v1/notifications/send",
    ),
    (
        ValueError("no row for patient 5512345678 in clinic"),
        "GET",
        "/api/v1/patients/{patient_id}",
    ),
    (
        AttributeError("'NoneType' object has no attribute 'default_price'"),
        "POST",
        "/api/v1/budget/plans/{plan_id}/budget",
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="Forget the recorded errors first.")
    args = parser.parse_args(argv)

    directory = server_errors.log_dir()
    if args.clear:
        server_errors.clear()
        print(f"Cleared {directory / server_errors.LOG_FILE_NAME}")

    for index, (exc, method, path) in enumerate(SAMPLES, start=1):
        server_errors.record(
            _raised(exc),
            method=method,
            path=path,
            request_id=f"demo{index:04d}{'0' * 8}",
            clinic_id=None,
            user_id=None,
        )

    written = len(server_errors.read(limit=len(SAMPLES)))
    target = directory / server_errors.LOG_FILE_NAME
    if written < len(SAMPLES):
        print(
            f"Only {written} of {len(SAMPLES)} are readable from {target}. "
            "Check that ERROR_LOG_DIR is writable by this process.",
            file=sys.stderr,
        )
        return 1

    print(f"Wrote {len(SAMPLES)} sample server errors to {target}")
    print("Read them back at GET /api/v1/ops/errors, or with: tail -n 5 " + str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
