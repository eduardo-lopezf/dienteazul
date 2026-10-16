"""Which reports can be answered, given the Apps that are running.

Every figure here is read from another App's tables: the agenda, budgets,
invoices and payments, patients, professionals, the catalog. They are
``integrates`` of this module, not ``depends`` (ADR 0037). A section whose
App is off answers 404 and the screen hides it; it comes back with the App.
With Patients off the figures stay and the names go; with Professionals
off, the professionals' names.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, status

from app.core.plugins.registry import module_registry

#: What a hidden name reads as, the same placeholder the reports already use.
NO_NAME = "-"


def running(*modules: str) -> bool:
    """Whether every one of ``modules`` is running here."""
    return all(module_registry.is_installed(module) for module in modules)


def needs(*modules: str) -> Callable[[], None]:
    """A route dependency: 404 while any of ``modules`` is off."""

    def _check() -> None:
        if not running(*modules):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This report's app is not enabled",
            )

    return _check
