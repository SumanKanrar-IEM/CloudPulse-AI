"""Agent run accounting and the cost cap (T008; spec 006, FR-004, FR-004a,
FR-005, FR-007a).

Pure: a run's bookkeeping is decided in code, and the database only records the
decision. That split is what lets FR-004a's retention rule -- which differs by
the *shape* of a capability's output -- be proven without a fixture.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.governance.agent_runs import (
    ITEM_WISE_CAPABILITIES,
    RunBudget,
    keeps_partial_output,
    outcome_for,
)
from app.models.enums import AgentCapability, AgentRunStatus


def _budget(cap: str = "100") -> RunBudget:
    return RunBudget(cap_units=Decimal(cap))


# --- the cap -----------------------------------------------------------------------


def test_a_run_under_its_cap_may_continue() -> None:
    budget = _budget()
    budget.charge(Decimal("30"))
    assert budget.remaining == Decimal("70")
    assert not budget.exhausted


def test_a_run_reaching_its_cap_exactly_is_exhausted() -> None:
    """At the cap is spent, not nearly spent — continuing would exceed it, which
    FR-004 forbids."""
    budget = _budget()
    budget.charge(Decimal("100"))
    assert budget.exhausted
    assert budget.remaining == Decimal("0")


def test_remaining_never_reports_negative() -> None:
    """A final call can overshoot; reporting -12 tokens remaining would be a
    number nobody can act on."""
    budget = _budget()
    budget.charge(Decimal("112"))
    assert budget.exhausted
    assert budget.remaining == Decimal("0")
    assert budget.consumed == Decimal("112")


def test_a_zero_or_negative_cap_is_refused_at_construction() -> None:
    """A cap of zero truncates every run before it starts, which is silent
    breakage rather than a configured limit (R-612's fallback reasoning)."""
    for bad in ("0", "-1"):
        with pytest.raises(ValueError):
            RunBudget(cap_units=Decimal(bad))


# --- outcome (FR-004, FR-007a) -----------------------------------------------------


def test_a_completed_run_within_budget_succeeded() -> None:
    status, reason = outcome_for(_budget(), completed=True, error=None)
    assert status is AgentRunStatus.SUCCEEDED
    assert reason is None


def test_a_run_stopped_at_the_cap_is_truncated_not_failed() -> None:
    """FR-004: `truncated` is a first-class status. Recording it as a failure
    would make an ordinary budget stop indistinguishable from the model being
    unreachable, which is the one thing FR-007a needs to see."""
    budget = _budget()
    budget.charge(Decimal("100"))
    status, reason = outcome_for(budget, completed=False, error=None)
    assert status is AgentRunStatus.TRUNCATED
    assert reason is None


def test_an_unreachable_model_is_failed_with_a_reason() -> None:
    """FR-007a's expected steady state. The reason is required by
    `ck_agent_run_failure_reason_shape`, and an unexplained failure is useless
    for diagnosing it."""
    status, reason = outcome_for(_budget(), completed=False, error="endpoint unreachable")
    assert status is AgentRunStatus.FAILED
    assert reason == "endpoint unreachable"


def test_an_error_outranks_an_exhausted_budget() -> None:
    """A run that both hit its cap and errored is a failure: the error is the
    fact that needs diagnosing, and truncation would hide it."""
    budget = _budget()
    budget.charge(Decimal("100"))
    status, reason = outcome_for(budget, completed=False, error="boom")
    assert status is AgentRunStatus.FAILED
    assert reason == "boom"


# --- FR-004a: what a truncated run keeps -------------------------------------------


@pytest.mark.parametrize("capability", [AgentCapability.SUGGESTER, AgentCapability.ADVISOR])
def test_item_wise_capabilities_keep_validated_items_on_truncation(
    capability: AgentCapability,
) -> None:
    """Each item stands alone, and discarding them would waste spend already
    incurred (FR-004a)."""
    assert keeps_partial_output(capability) is True
    assert capability in ITEM_WISE_CAPABILITIES


@pytest.mark.parametrize("capability", [AgentCapability.DIGEST, AgentCapability.NARRATOR])
def test_whole_artifact_capabilities_discard_partial_output(
    capability: AgentCapability,
) -> None:
    """A half-written digest implies nothing else was notable, which is worse
    than no digest (FR-004a)."""
    assert keeps_partial_output(capability) is False


def test_every_capability_has_a_stated_retention_rule() -> None:
    """A capability added later must be classified deliberately, not inherit a
    default that silently discards or silently keeps."""
    for capability in AgentCapability:
        assert isinstance(keeps_partial_output(capability), bool)
