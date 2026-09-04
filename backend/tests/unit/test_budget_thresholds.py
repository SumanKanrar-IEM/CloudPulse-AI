"""Threshold crossing and the forecast, without a database (T032; S41,
FR-015, FR-016, research.md R-506, R-507).

All of this is pure by construction, which is the point R-506 makes about
choosing our own ingested spend over `ce:GetCostForecast`: the forecast is
fully testable with pytest, independent of any live AWS call, which a
Cost-Explorer-backed version would not be.

The DB-backed half -- the month-to-date and 7-day-window queries, and the
open/resolve of the finding itself -- is asserted against a real PostgreSQL in
`tests/integration/test_budget_overrun_finding.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.governance.budgets import (
    ThresholdState,
    crossings,
    month_bounds,
    opens_a_finding,
    project_forecast,
    resolves_a_finding,
)

BUDGET = Decimal("1000.00")


def _state(actual: str, forecast: str | None = None) -> ThresholdState:
    return ThresholdState(
        actual_usd=Decimal(actual),
        forecast_usd=Decimal(forecast if forecast is not None else actual),
        budget_usd=BUDGET,
    )


# --- month arithmetic --------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected_last"),
    [
        (date(2026, 2, 10), date(2026, 2, 28)),
        (date(2024, 2, 10), date(2024, 2, 29)),  # leap year
        (date(2026, 4, 10), date(2026, 4, 30)),
        (date(2026, 12, 31), date(2026, 12, 31)),
    ],
)
def test_month_bounds_are_calendar_aware(day: date, expected_last: date) -> None:
    """A 30-day approximation would overstate February by roughly 7% -- more
    than enough to trip an 80% flag that should not have fired."""
    first, last = month_bounds(day)
    assert first == day.replace(day=1)
    assert last == expected_last


# --- forecast (R-506) --------------------------------------------------------------


def test_the_forecast_extrapolates_the_daily_average_over_the_days_left() -> None:
    # 10/day average, 20 days left in a 30-day month from the 10th.
    forecast = project_forecast(Decimal("100"), [Decimal("10")] * 7, as_of=date(2026, 4, 10))
    assert forecast == Decimal("300")  # 100 month-to-date + 10 * 20 remaining


def test_the_forecast_averages_rather_than_trusting_the_last_day() -> None:
    """R-506 rejected "last day x days remaining" explicitly: one large one-off
    charge would otherwise falsely trip a forecast flag for the rest of the
    month."""
    spiky = [Decimal("1")] * 6 + [Decimal("601")]  # one 601 day, six quiet ones
    forecast = project_forecast(Decimal("0"), spiky, as_of=date(2026, 4, 10))
    naive_last_day = Decimal("601") * 20
    assert forecast < naive_last_day
    # The 7-day average is 607/7, not the 601 spike -- that is the whole point.
    assert forecast == (Decimal("607") / 7) * 20


def test_an_empty_window_forecasts_exactly_month_to_date() -> None:
    """With nothing to extrapolate from, claiming a project will spend nothing
    more would be a guess dressed as a projection."""
    assert project_forecast(Decimal("250"), [], as_of=date(2026, 4, 10)) == Decimal("250")


def test_the_last_day_of_the_month_forecasts_month_to_date() -> None:
    """Zero days remaining -- there is nothing left to project into."""
    assert project_forecast(
        Decimal("250"), [Decimal("10")] * 7, as_of=date(2026, 4, 30)
    ) == Decimal("250")


# --- crossings (FR-015) ------------------------------------------------------------


def test_spend_under_every_threshold_crosses_nothing() -> None:
    assert crossings(_state("500")) == {
        "actual_80": False,
        "actual_100": False,
        "forecast_80": False,
        "forecast_100": False,
    }


def test_spend_exactly_on_a_threshold_counts_as_crossed() -> None:
    """A budget you have exactly exhausted is not "within budget"."""
    assert crossings(_state("800"))["actual_80"] is True
    assert crossings(_state("1000"))["actual_100"] is True


def test_a_forecast_can_cross_while_actual_has_not() -> None:
    """The case FR-015's forecast thresholds exist for: still under today,
    heading over by month end."""
    crossed = crossings(_state("400", forecast="1200"))
    assert crossed["actual_80"] is False
    assert crossed["actual_100"] is False
    assert crossed["forecast_80"] is True
    assert crossed["forecast_100"] is True


# --- what opens a finding (R-507) --------------------------------------------------


def test_actual_100_opens_a_finding() -> None:
    assert opens_a_finding(False, _state("1000")) is True


def test_the_same_state_on_a_later_run_does_not_open_a_second_finding() -> None:
    """R-507's trigger is the transition, not the condition -- otherwise every
    daily run while a project stayed over budget would open another finding."""
    assert opens_a_finding(True, _state("1500")) is False


@pytest.mark.parametrize(
    ("label", "state"),
    [
        ("actual-80", _state("800")),
        ("forecast-80", _state("100", forecast="800")),
        ("forecast-100", _state("100", forecast="1200")),
    ],
)
def test_no_other_threshold_opens_a_finding(label: str, state: ThresholdState) -> None:
    """R-507: 80% is dashboard-only by the spec's own Clarifications, and a
    forecast is a projection rather than a fact -- opening a finding over one
    would put a false-positive-prone signal into the same channel real
    violations use, and would fire User Story 2's email with it."""
    assert opens_a_finding(False, state) is False, label


def test_spend_dropping_back_under_resolves() -> None:
    """FR-017. Detection of an already-changed external fact -- no remediation
    action is implied or granted."""
    assert resolves_a_finding(_state("999.99")) is True


def test_spend_still_over_does_not_resolve() -> None:
    assert resolves_a_finding(_state("1000")) is False
