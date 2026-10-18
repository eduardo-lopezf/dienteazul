"""Which custody modes an account tier is sold under.

``account_tier`` says what the software does for a clinic; ``CustodyMode``
says who runs the deployment and who holds its keys (ADR 0023). They are
independent axes, and a commercial offer is a *cell* of the matrix rather
than a rung on a ladder — see
``docs/features/licensing-and-packaging.md``. Exactly one rule connects
them, and it lives here.

**The entry tiers are sold hosted, and only hosted.** ``basic`` and
``medium`` are always ``managed``. Every other tier may be ``self``,
``managed`` or ``byok``.

The rule is not a database constraint, and that is deliberate. Only one
half of the pair is in the tenant's own database: ADR 0024 rule 2 keeps
``custody_mode`` out of the data plane, precisely so a claim about who
can read a database is not stored where its own subject can rewrite it.
A ``CHECK`` spanning both halves would therefore require moving custody
down, which is the trade this codebase has already refused. So the rule
is enforced in the application, at the two places where both halves are
known at once: when a clinic is created, and at boot.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from .policy import CustodyMode


class AccountTier(StrEnum):
    """Account/business tier a clinic operates under.

    Only ``CLINIC`` has real functionality today; the rest are reserved
    names for tiers agreed on but not built. ``MEDIUM`` and ``ADVANCED``
    are deliberately undefined as products — inventing the boundary
    between them before a customer asks for it turns a guess into a
    commitment.
    """

    BASIC = "basic"
    MEDIUM = "medium"
    ADVANCED = "advanced"
    CLINIC = "clinic"
    CLINIC_PRO = "clinic_pro"
    HOSPITAL = "hospital"


#: One professional's practice, as opposed to a clinic: the account holder
#: is the practice's only professional.
INDIVIDUAL_TIERS: Final[frozenset[AccountTier]] = frozenset(
    {AccountTier.BASIC, AccountTier.MEDIUM, AccountTier.ADVANCED}
)


# The entry tiers exist to be cheap, and a self-hosted deployment is the
# opposite of cheap for the clinic: it carries the infrastructure, the
# backups and the upgrades, plus the licence (ADR 0028). Offering them
# under `self` would be selling the most demanding delivery model to the
# customers least equipped to run it. `byok` is excluded for the same
# reason and one more: it needs a dedicated tenant database.
_MANAGED_ONLY_TIERS: Final[frozenset[AccountTier]] = frozenset(
    {AccountTier.BASIC, AccountTier.MEDIUM}
)


class TierCustodyError(ValueError):
    """An account tier was paired with a custody mode it is not sold under."""


def allowed_custody_modes(tier: AccountTier) -> frozenset[CustodyMode]:
    """Custody modes ``tier`` may be created under."""
    if tier in _MANAGED_ONLY_TIERS:
        return frozenset({CustodyMode.MANAGED})
    return frozenset(CustodyMode)


def tiers_available_under(mode: CustodyMode) -> tuple[AccountTier, ...]:
    """Account tiers a deployment running under ``mode`` may create.

    The inverse of :func:`allowed_custody_modes`, in declaration order, so
    a caller offering a choice (the first-run screen) offers only the
    valid ones instead of letting the user pick and then be refused.
    """
    return tuple(tier for tier in AccountTier if mode in allowed_custody_modes(tier))


def validate_tier_custody(tier: AccountTier, mode: CustodyMode) -> None:
    """Raise :class:`TierCustodyError` if the pairing is not one we sell.

    Both values are mandatory by construction: the caller cannot reach
    this function without having decided each of them, which is the point
    of validating the pair rather than defaulting either half.
    """
    allowed = allowed_custody_modes(tier)
    if mode not in allowed:
        offered = ", ".join(sorted(m.value for m in allowed))
        raise TierCustodyError(
            f"account tier {tier.value!r} is not offered under custody mode "
            f"{mode.value!r}; it is sold as: {offered}"
        )


def incompatible_tiers(tiers: Iterable[str], mode: CustodyMode) -> tuple[str, ...]:
    """Tiers among ``tiers`` that ``mode`` is not allowed to serve.

    The pairing is checked when a clinic is created, but the custody half
    is an environment variable and an environment variable can be changed
    afterwards: flipping a deployment holding ``basic`` clinics over to
    ``self`` would strand them silently. This is the boot-time half of the
    check. It reports rather than refuses — see the caller — because
    taking a running clinic offline over a commercial rule is worse than
    the rule being briefly untrue.

    Unknown strings are returned as incompatible: a tier the taxonomy does
    not contain cannot be shown to be allowed.
    """
    offenders: list[str] = []
    for raw in tiers:
        try:
            tier = AccountTier(raw)
        except ValueError:
            offenders.append(raw)
            continue
        if mode not in allowed_custody_modes(tier):
            offenders.append(raw)
    return tuple(dict.fromkeys(offenders))
