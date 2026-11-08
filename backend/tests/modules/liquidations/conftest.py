"""Liquidations on their own percentage.

The suite mounts every module, and with `commissions` running it is the
source of every percentage (``CommissionRates``). These tests cover the
module without it; `tests/modules/commissions/` covers it with it.
"""

from collections.abc import Iterator

import pytest

from app.core.plugins.registry import module_registry


@pytest.fixture(autouse=True)
def _without_commissions() -> Iterator[None]:
    was_active = module_registry.is_installed("commissions")
    module_registry.deactivate("commissions")
    try:
        yield
    finally:
        if was_active:
            module_registry.activate("commissions")
