"""Auto-created budget shape, without a database (T027; S40, FR-015).

The one thing worth pinning here is what a *new* budget must NOT carry: all
four crossed-timestamp columns start NULL. Research.md R-507 reads
`actual_100_crossed_at` transitioning from NULL to non-NULL as the trigger
that opens an overrun finding, so a budget seeded with anything else would
fire that trigger on a project that has never spent a cent.

That the row lands in the same transaction as the SDA (research.md R-502) is a
real transactional property and is asserted against a real PostgreSQL in
`tests/integration/test_sda_registration_creates_budget.py` instead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.governance.budgets import (
    ACTUAL_BREACH_RATIO,
    ACTUAL_WARNING_RATIO,
    create_budget_for_sda,
    default_budget_usd,
)
from app.models.core import Sda as SdaRow


class _RecordingSession:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def add(self, instance: Any) -> None:
        self.rows.append(instance)


def _sda() -> SdaRow:
    return SdaRow(
        id=uuid.uuid4(),
        name="platform",
        owner_email="p@example.com",
        tag_values={"project_id": "proj-a"},
    )


def test_a_new_budget_carries_the_configured_cap() -> None:
    session = _RecordingSession()
    sda = _sda()

    budget = create_budget_for_sda(session, sda, amount_usd=Decimal("1000.00"))

    assert budget.sda_id == sda.id
    assert budget.amount_usd == Decimal("1000.00")
    assert session.rows == [budget]


def test_a_new_budget_has_crossed_nothing() -> None:
    """R-507's trigger is `actual_100_crossed_at` going NULL -> non-NULL. A
    budget that started non-NULL would open an overrun finding for a project
    with no spend at all."""
    budget = create_budget_for_sda(_RecordingSession(), _sda(), amount_usd=Decimal("1000.00"))

    assert budget.actual_80_crossed_at is None
    assert budget.actual_100_crossed_at is None
    assert budget.forecast_80_crossed_at is None
    assert budget.forecast_100_crossed_at is None


def test_the_thresholds_are_the_fixed_platform_wide_defaults() -> None:
    """FR-015 and the spec's Assumptions: 80% and 100%, not configurable per
    project this release. Asserted so a later "make them configurable" change
    has to come past a test that says the spec said otherwise."""
    assert ACTUAL_WARNING_RATIO == Decimal("0.80")
    assert ACTUAL_BREACH_RATIO == Decimal("1.00")


# --- the configured cap -----------------------------------------------------------

_ENV = "CLOUDPULSE_DEFAULT_BUDGET_USD"


def test_an_unset_cap_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    assert default_budget_usd() == Decimal("1000.00")


def test_a_configured_cap_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "2500.50")
    assert default_budget_usd() == Decimal("2500.50")


@pytest.mark.parametrize("raw", ["", "not-a-number", "1,000", "0", "-50"])
def test_an_unusable_cap_falls_back_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A malformed or non-positive cap must not take SDA registration down with
    it. Zero and negative are rejected specifically: a budget of 0 would put
    every project instantly over 100% of its own guardrail."""
    monkeypatch.setenv(_ENV, raw)
    assert default_budget_usd() == Decimal("1000.00")
