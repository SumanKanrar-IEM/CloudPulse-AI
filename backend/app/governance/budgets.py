"""Auto-created spending guardrails for a project (spec 005, FR-015, T029).

One budget per SDA, created synchronously inside `POST /sdas`'s own
transaction (research.md R-502) -- "within a day of registration" is FR-015's
outer bound, not a target, and the registration endpoint already writes one
row inside one transaction, so this is a second row on an existing write path
rather than a new capability with its own worker and schedule.

The 80%/100% thresholds are fixed platform-wide defaults for this release
(spec.md's own Assumptions); nothing here reads a per-project override,
because none exists to read.
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import Budget as BudgetRow
from app.models.core import Sda as SdaRow

# FR-015's two thresholds, as data rather than as literals scattered through
# the crossing checks that will read them in Phase 8 (T034).
ACTUAL_WARNING_RATIO = Decimal("0.80")
ACTUAL_BREACH_RATIO = Decimal("1.00")

# data-model.md: the cap amount is "a configured default, e.g. from an environment
# variable" -- deliberately not an FR, and explicitly not per-project this release.
_BUDGET_ENV_VAR = "CLOUDPULSE_DEFAULT_BUDGET_USD"
_FALLBACK_BUDGET_USD = Decimal("1000.00")


def default_budget_usd() -> Decimal:
    """The cap a newly-registered project's budget is created with.

    Read from the environment directly rather than through `Settings`, matching
    what `app/api/main.py` already does for `frontend_url`. Going through
    `Settings` would make `POST /sdas` -- a request path that has never needed
    any configuration -- fail outright wherever the full Settings model cannot
    be constructed, which is a real coupling to add for one Decimal.

    An unparseable value falls back rather than raising: a malformed budget cap
    must not take SDA registration down with it, and the fallback is a
    conservative default, not a guess at what was meant.
    """
    raw = os.environ.get(_BUDGET_ENV_VAR)
    if not raw:
        return _FALLBACK_BUDGET_USD
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.warning(
            "ignoring an unparseable default budget; using the fallback",
            extra={"env_var": _BUDGET_ENV_VAR, "fallback_usd": str(_FALLBACK_BUDGET_USD)},
        )
        return _FALLBACK_BUDGET_USD
    if value <= 0:
        logger.warning(
            "ignoring a non-positive default budget; using the fallback",
            extra={"env_var": _BUDGET_ENV_VAR, "fallback_usd": str(_FALLBACK_BUDGET_USD)},
        )
        return _FALLBACK_BUDGET_USD
    return value


def create_budget_for_sda(session: TenantSession, sda: SdaRow, *, amount_usd: Decimal) -> BudgetRow:
    """FR-015: a guardrail exists the moment the project does.

    None of the four crossed-timestamp columns is set here. A brand-new budget
    has crossed nothing, and seeding them with anything other than NULL would
    make R-507's trigger condition -- `actual_100_crossed_at` transitioning
    from NULL to non-NULL -- fire on a project that has never spent a cent.
    """
    budget = BudgetRow(sda_id=sda.id, amount_usd=amount_usd)
    session.add(budget)
    return budget


__all__ = [
    "ACTUAL_BREACH_RATIO",
    "ACTUAL_WARNING_RATIO",
    "create_budget_for_sda",
    "default_budget_usd",
]
