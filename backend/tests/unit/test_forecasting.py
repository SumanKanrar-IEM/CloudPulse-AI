"""The forecast calculation is deterministic and refuses thin history (T044;
spec 006, FR-021, FR-021a, FR-022, S51).

Three properties, each the whole of one requirement:

* **Same history, same figure.** FR-022. Asserted by running the calculation
  twice and by shuffling the input order -- a sum that depended on iteration
  order would be deterministic per call and still wrong per requirement.
* **Below the minimum is a state, not a number.** FR-021a. One below refuses;
  exactly at the minimum forecasts. The boundary is the assertion, because an
  off-by-one here turns "not enough data" into a projection from too few points
  in one direction and refuses a valid forecast in the other.
* **No model.** `forecasting.py` imports nothing that can reach one. Asserted
  against the module's imports rather than trusted.

Everything here is pure: no database, no clock.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.governance import forecasting
from app.governance.forecasting import (
    Backtest,
    InsufficientHistory,
    Observation,
    Projection,
    backtest,
    minimum_periods,
    project,
)
from app.models.enums import ForecastKind

START = date(2026, 2, 1)


def _linear(days: int, *, base: str, step: str) -> list[Observation]:
    """A clean line, so the expected projection can be computed by hand."""
    return [
        Observation(day=START + timedelta(days=i), value=Decimal(base) + Decimal(step) * i)
        for i in range(days)
    ]


# --- FR-022: deterministic ------------------------------------------------------------


def test_the_same_history_yields_the_same_forecast_twice() -> None:
    history = _linear(20, base="10", step="0.5")

    first = project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14)
    second = project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14)

    assert first == second


def test_input_order_does_not_change_the_forecast() -> None:
    history = _linear(20, base="10", step="0.5")
    shuffled = history[:]
    random.Random(7).shuffle(shuffled)  # noqa: S311 - a fixed seed, not a secret

    assert project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14) == (
        project(ForecastKind.SPEND, shuffled, period_start=date(2026, 3, 1), required=14)
    )


def test_a_perfect_line_is_extrapolated_exactly() -> None:
    """y = 10 + 0.5x from 2026-02-01. Thirty days from 2026-03-01 (x=28..57):
    sum of 10 + 0.5x = 30*10 + 0.5 * sum(28..57) = 300 + 0.5 * 1275 = 937.5."""
    history = _linear(20, base="10", step="0.5")

    result = project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14)

    assert isinstance(result, Projection)
    assert result.projected_value == Decimal("937.5000")
    assert (result.period_start, result.period_end) == (date(2026, 3, 1), date(2026, 3, 30))
    assert result.history_days == 20


def test_capacity_projects_a_level_not_a_sum() -> None:
    """Same line, last day of the horizon (x=57): 10 + 0.5*57 = 38.5."""
    history = _linear(20, base="10", step="0.5")

    result = project(ForecastKind.CAPACITY, history, period_start=date(2026, 3, 1), required=14)

    assert isinstance(result, Projection)
    assert result.projected_value == Decimal("38.5000")


def test_a_falling_line_is_clamped_at_zero_not_projected_negative() -> None:
    history = _linear(20, base="5", step="-1")  # hits zero on day 5, negative after

    result = project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14)

    assert isinstance(result, Projection)
    assert result.projected_value == Decimal("0.0000")


# --- FR-021a: the minimum-period boundary -----------------------------------------------------


def test_one_below_the_minimum_is_insufficient_history() -> None:
    history = _linear(13, base="10", step="1")

    result = project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14)

    assert result == InsufficientHistory(kind=ForecastKind.SPEND, history_days=13, required_days=14)


def test_exactly_the_minimum_does_forecast() -> None:
    history = _linear(14, base="10", step="1")

    result = project(ForecastKind.SPEND, history, period_start=date(2026, 3, 1), required=14)

    assert isinstance(result, Projection)


def test_distinct_days_are_counted_not_rows() -> None:
    """Two rows on one day are one period. A project with fourteen rows across
    seven days has seven periods of history, not fourteen."""
    history = _linear(7, base="10", step="1")
    doubled = history + history

    result = project(ForecastKind.SPEND, doubled, period_start=date(2026, 3, 1), required=14)

    assert result == InsufficientHistory(kind=ForecastKind.SPEND, history_days=7, required_days=14)


def test_the_minimum_is_read_from_the_environment_with_a_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-612: a bad value falls back rather than raising. A threshold of zero
    would forecast from nothing; a non-integer would take the endpoint down."""
    monkeypatch.setenv("CLOUDPULSE_FORECAST_MIN_PERIODS", "21")
    assert minimum_periods() == 21

    for bad in ("0", "-3", "fourteen", ""):
        monkeypatch.setenv("CLOUDPULSE_FORECAST_MIN_PERIODS", bad)
        assert minimum_periods() == 14, bad


# --- FR-022: the backtest --------------------------------------------------------------------


def test_a_backtest_on_a_perfect_line_has_zero_error() -> None:
    history = _linear(30, base="10", step="0.5")

    result = backtest(ForecastKind.SPEND, history, held_out_days=7, required=14)

    assert isinstance(result, Backtest)
    assert result.training_days == 23
    assert result.held_out_days == 7
    assert result.absolute_percentage_error == Decimal("0.000")
    assert result.projected_value == result.actual_value


def test_a_backtest_reports_the_error_it_made() -> None:
    """Flat at 10 for 23 days, then the held-out week doubles. The line
    predicts ~70 for the week; actual is 140; error 50%."""
    history = _linear(23, base="10", step="0") + [
        Observation(day=START + timedelta(days=23 + i), value=Decimal("20")) for i in range(7)
    ]

    result = backtest(ForecastKind.SPEND, history, held_out_days=7, required=14)

    assert isinstance(result, Backtest)
    assert result.projected_value == Decimal("70.0000")
    assert result.actual_value == Decimal("140.0000")
    assert result.absolute_percentage_error == Decimal("50.000")


def test_a_backtest_is_reproducible() -> None:
    history = _linear(23, base="10", step="0.3") + [
        Observation(day=START + timedelta(days=23 + i), value=Decimal("17.1")) for i in range(7)
    ]
    assert backtest(ForecastKind.SPEND, history, held_out_days=7, required=14) == backtest(
        ForecastKind.SPEND, history, held_out_days=7, required=14
    )


def test_a_zero_actual_gives_no_percentage_rather_than_a_lie() -> None:
    history = _linear(23, base="10", step="0") + [
        Observation(day=START + timedelta(days=23 + i), value=Decimal("0")) for i in range(7)
    ]

    result = backtest(ForecastKind.SPEND, history, held_out_days=7, required=14)

    assert isinstance(result, Backtest)
    assert result.absolute_percentage_error is None


def test_a_backtest_needs_training_history_too() -> None:
    """Fourteen days total with seven held out leaves seven to train on --
    below the minimum, so the backtest says so rather than fitting to seven."""
    history = _linear(14, base="10", step="1")

    result = backtest(ForecastKind.SPEND, history, held_out_days=7, required=14)

    assert isinstance(result, InsufficientHistory)
    assert result.history_days == 7


# --- FR-021: no model, structurally -------------------------------------------------------


def test_the_calculation_imports_nothing_that_can_reach_a_model() -> None:
    """Not a style check. FR-021 says no model call may produce or alter a
    figure; the cheapest proof is that nothing in scope could make one."""
    import inspect

    source = inspect.getsource(forecasting)
    for forbidden in ("connectors", "bedrock", "invoke_agent", "boto3", "agent_runs"):
        assert forbidden not in source, forbidden
