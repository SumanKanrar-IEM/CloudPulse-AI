"""Agent run accounting: the cost cap, the outcome, and what a truncated run
keeps (spec 006, T009; FR-004, FR-004a, FR-005, FR-007a, research.md R-612).

Deliberately split from persistence. The decisions here -- is the budget spent,
did this run succeed or truncate or fail, does this capability keep what it
already produced -- are pure, so they are provable without a database and cannot
drift into a query. Writing the `agent_run` row is the caller's job.

**The cap is in model tokens** (FR-004), input and output combined, because that
is the unit the platform is actually billed in. Both consumed and cap are
recorded on the row, so a later reader can tell "hit the cap" from "the cap was
lowered" without consulting configuration history.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.core.logging import logger
from app.models.enums import AgentCapability, AgentRunStatus

# R-612: read from the environment at point of use, not added to the shared
# `Settings` model. Spec 005 tried that and gave `POST /sdas` its first-ever
# configuration dependency, breaking 11 spec-003 tests that had no reason to
# construct a Settings environment (its T029a).
_CAP_ENV_VAR = "CLOUDPULSE_AGENT_COST_CAP_UNITS"
_FALLBACK_CAP_UNITS = Decimal("200000")

# FR-004a. An item-wise capability produces results that stand alone, so a
# truncated run keeps every one that passed validation -- discarding them would
# waste spend already incurred. A whole-artifact capability produces one thing,
# and half of it implies that nothing else was notable.
ITEM_WISE_CAPABILITIES: frozenset[AgentCapability] = frozenset(
    {AgentCapability.SUGGESTER, AgentCapability.ADVISOR}
)


@dataclass
class RunBudget:
    """What a run may spend, and what it has spent (FR-004)."""

    cap_units: Decimal
    consumed: Decimal = field(default=Decimal("0"))

    def __post_init__(self) -> None:
        if self.cap_units <= 0:
            # A cap of zero truncates every run before it starts. That is silent
            # breakage dressed as a configured limit, so it is refused here
            # rather than discovered as "the digest stopped appearing".
            raise ValueError("agent cost cap must be positive")

    def charge(self, units: Decimal) -> None:
        self.consumed += units

    @property
    def exhausted(self) -> bool:
        """At the cap counts as spent: continuing would exceed it."""
        return self.consumed >= self.cap_units

    @property
    def remaining(self) -> Decimal:
        """Never negative. A final call can overshoot the cap, and reporting a
        negative remaining budget is a number nobody can act on."""
        return max(Decimal("0"), self.cap_units - self.consumed)


def default_cost_cap_units() -> Decimal:
    """The cap a run starts with (FR-004, R-612).

    A malformed or non-positive value falls back rather than raising, for the
    same reason spec 005's `default_budget_usd` does: a bad configuration value
    must not take a scheduled run down, and the conservative default is a better
    answer than a crash.
    """
    raw = os.environ.get(_CAP_ENV_VAR)
    if not raw:
        return _FALLBACK_CAP_UNITS
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.warning(
            "ignoring an unparseable agent cost cap; using the fallback",
            extra={"env_var": _CAP_ENV_VAR, "fallback_units": str(_FALLBACK_CAP_UNITS)},
        )
        return _FALLBACK_CAP_UNITS
    if value <= 0:
        logger.warning(
            "ignoring a non-positive agent cost cap; using the fallback",
            extra={"env_var": _CAP_ENV_VAR, "fallback_units": str(_FALLBACK_CAP_UNITS)},
        )
        return _FALLBACK_CAP_UNITS
    return value


def outcome_for(
    budget: RunBudget, *, completed: bool, error: str | None
) -> tuple[AgentRunStatus, str | None]:
    """How a run ended, and why if it failed (FR-004, FR-007a).

    An error outranks an exhausted budget: a run that both hit its cap and threw
    is a failure, because the error is the fact that needs diagnosing and
    truncation would hide it.

    `truncated` is deliberately not a failure. Recording it as one would make an
    ordinary budget stop indistinguishable from the model being unreachable,
    which is the single thing FR-007a needs to be able to see.
    """
    if error is not None:
        return AgentRunStatus.FAILED, error
    if completed:
        return AgentRunStatus.SUCCEEDED, None
    if budget.exhausted:
        return AgentRunStatus.TRUNCATED, None
    # Neither completed, nor errored, nor out of budget: the caller stopped for a
    # reason it did not report. Treated as a failure rather than a success,
    # because a silent early stop presented as success is how a partial digest
    # would reach a user.
    return AgentRunStatus.FAILED, "run ended without completing and without a reported error"


def keeps_partial_output(capability: AgentCapability) -> bool:
    """FR-004a, as a lookup rather than a branch at every call site."""
    return capability in ITEM_WISE_CAPABILITIES


__all__ = [
    "ITEM_WISE_CAPABILITIES",
    "RunBudget",
    "default_cost_cap_units",
    "keeps_partial_output",
    "outcome_for",
]
