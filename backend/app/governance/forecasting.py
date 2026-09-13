"""Spend and capacity forecasts by deterministic calculation (spec 006, T046;
FR-021, FR-021a, FR-022, S51).

**No model call anywhere in this module, and none upstream of it.** FR-021 is
absolute: no model may produce or alter a forecast figure. Everything here is
arithmetic over collected history, in `Decimal`, in a fixed order -- which is
what makes the same history yield the same figure every time (FR-022), and
what makes a backtest a reproduction rather than an impression.

**The method is a least-squares line.** Ordinary least squares over
(day index, value), extrapolated across the horizon. Chosen over a moving
average because User Story 5 asks "where is spend heading", and a level
cannot head anywhere. Chosen over anything cleverer because SC-006's target is
MAPE under 15% on test projects, and a line is the simplest thing that can
honestly express a trend, be explained in one sentence, and be checked by hand.
Clamped at zero: spend does not go negative, and a fitted line can.

**Not enough data is a state, not a small number.** FR-021a: a project with
fewer distinct collected periods than `CLOUDPULSE_FORECAST_MIN_PERIODS` gets
`InsufficientHistory`, never a projection from too few points. The threshold is
read from the environment at point of use per R-612, with a conservative
fallback and no exception path -- a bad value must not take a read endpoint
down.

**Two kinds, one calculation.** Spend history is the SDA's daily spend total
(`spend_record`, gaps excluded); the projection is the *sum* over the horizon,
because a spend forecast answers "how much". Capacity history is the SDA's
daily mean CPU across its metered resources (`resource_metric`, unavailable
rows excluded); the projection is the fitted *level* at the horizon's end,
because a capacity forecast answers "how full".
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import func, select

from app.core.db import TenantSession
from app.models.core import Resource as ResourceRow
from app.models.core import ResourceMetric as MetricRow
from app.models.core import SpendRecord as SpendRow
from app.models.enums import ForecastKind, ResourceMetricKind

# R-612: environment at point of use, conservative fallback, never raises.
_MIN_PERIODS_ENV = "CLOUDPULSE_FORECAST_MIN_PERIODS"
_DEFAULT_MIN_PERIODS = 14

HORIZON_DAYS = 30

# Matches `forecast.projected_value` NUMERIC(14,4) and
# `absolute_percentage_error` NUMERIC(6,3).
_VALUE_PRECISION = Decimal("0.0001")
_ERROR_PRECISION = Decimal("0.001")


def minimum_periods() -> int:
    raw = os.environ.get(_MIN_PERIODS_ENV, "")
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MIN_PERIODS
    return value if value > 0 else _DEFAULT_MIN_PERIODS


@dataclass(frozen=True, slots=True)
class Observation:
    day: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class Projection:
    """A forecast for one SDA and kind, with the period it covers and the
    history it came from. `history_days` is what makes the not-enough-data
    boundary auditable after the fact (data-model.md)."""

    kind: ForecastKind
    period_start: date
    period_end: date
    projected_value: Decimal
    history_days: int


@dataclass(frozen=True, slots=True)
class InsufficientHistory:
    """FR-021a's explicit state. Carries the numbers a reader needs to know how
    far off sufficient is -- "not enough" with no count is a shrug."""

    kind: ForecastKind
    history_days: int
    required_days: int


@dataclass(frozen=True, slots=True)
class Backtest:
    """FR-022: the error a forecast made against actuals it never saw.

    `absolute_percentage_error` is None when the held-out actual is zero --
    a percentage of nothing is not a number, and reporting 0 or infinity there
    would both be lies in different directions.
    """

    kind: ForecastKind
    training_days: int
    held_out_days: int
    projected_value: Decimal
    actual_value: Decimal
    absolute_percentage_error: Decimal | None


# --- the calculation -------------------------------------------------------------


def _fit(observations: list[Observation]) -> tuple[Decimal, Decimal, date]:
    """Least squares over (day index, value). Returns (intercept, slope, day 0).

    Day indices are integers from the first observation, so the fit does not
    depend on the calendar date of the history -- only on its shape. Sorted
    first: the sums below are order-independent in exact arithmetic, and
    sorting makes that true in practice too.
    """
    ordered = sorted(observations, key=lambda o: o.day)
    origin = ordered[0].day
    n = Decimal(len(ordered))
    xs = [Decimal((o.day - origin).days) for o in ordered]
    ys = [o.value for o in ordered]
    sum_x = sum(xs, Decimal(0))
    sum_y = sum(ys, Decimal(0))
    sum_xx = sum((x * x for x in xs), Decimal(0))
    sum_xy = sum((x * y for x, y in zip(xs, ys, strict=True)), Decimal(0))
    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        # Every observation on the same day (a single distinct period): a flat
        # line at the mean is the only honest fit. Unreachable when the caller
        # enforces a minimum above 1, kept so the arithmetic never divides by 0.
        return sum_y / n, Decimal(0), origin
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    return intercept, slope, origin


def _predict(intercept: Decimal, slope: Decimal, origin: date, day: date) -> Decimal:
    return max(Decimal(0), intercept + slope * Decimal((day - origin).days))


def project(
    kind: ForecastKind,
    observations: list[Observation],
    *,
    period_start: date,
    horizon_days: int = HORIZON_DAYS,
    required: int | None = None,
) -> Projection | InsufficientHistory:
    """Forecast `horizon_days` from `period_start`, or say why not.

    Spend sums the fitted daily values across the horizon; capacity takes the
    fitted level on its last day. Same line, different question.
    """
    required = required if required is not None else minimum_periods()
    distinct_days = len({o.day for o in observations})
    if distinct_days < required:
        return InsufficientHistory(kind=kind, history_days=distinct_days, required_days=required)

    intercept, slope, origin = _fit(observations)
    period_end = period_start + timedelta(days=horizon_days - 1)
    if kind is ForecastKind.SPEND:
        value = sum(
            (
                _predict(intercept, slope, origin, period_start + timedelta(days=i))
                for i in range(horizon_days)
            ),
            Decimal(0),
        )
    else:
        value = _predict(intercept, slope, origin, period_end)

    return Projection(
        kind=kind,
        period_start=period_start,
        period_end=period_end,
        projected_value=value.quantize(_VALUE_PRECISION, rounding=ROUND_HALF_EVEN),
        history_days=distinct_days,
    )


def backtest(
    kind: ForecastKind,
    observations: list[Observation],
    *,
    held_out_days: int,
    required: int | None = None,
) -> Backtest | InsufficientHistory:
    """FR-022. Fit on everything before the last `held_out_days`, forecast that
    window, compare with what actually happened in it.

    Deterministic by construction: the split is by sorted day, the fit is
    `_fit`, and nothing here reads a clock.
    """
    ordered = sorted(observations, key=lambda o: o.day)
    days = sorted({o.day for o in ordered})
    if len(days) <= held_out_days:
        return InsufficientHistory(
            kind=kind,
            history_days=len(days),
            required_days=(required if required is not None else minimum_periods()) + held_out_days,
        )
    cutoff = days[-held_out_days]
    training = [o for o in ordered if o.day < cutoff]
    held_out = [o for o in ordered if o.day >= cutoff]

    result = project(
        kind,
        training,
        period_start=cutoff,
        horizon_days=held_out_days,
        required=required,
    )
    if isinstance(result, InsufficientHistory):
        return result

    if kind is ForecastKind.SPEND:
        actual = sum((o.value for o in held_out), Decimal(0))
    else:
        actual = held_out[-1].value

    error: Decimal | None = None
    if actual != 0:
        error = (abs(result.projected_value - actual) / abs(actual) * Decimal(100)).quantize(
            _ERROR_PRECISION, rounding=ROUND_HALF_EVEN
        )
    return Backtest(
        kind=kind,
        training_days=result.history_days,
        held_out_days=len({o.day for o in held_out}),
        projected_value=result.projected_value,
        actual_value=actual.quantize(_VALUE_PRECISION, rounding=ROUND_HALF_EVEN),
        absolute_percentage_error=error,
    )


# --- history, from the store ---------------------------------------------------------


def spend_history(session: TenantSession, sda_id: uuid.UUID) -> list[Observation]:
    """Daily spend total for one SDA. Gap days are excluded rather than read as
    zero -- the same discipline that stored them as gaps."""
    statement = (
        session.scoped(select(SpendRow.spend_date, func.sum(SpendRow.amount_usd)), SpendRow)
        .where(SpendRow.sda_id == sda_id)
        .where(SpendRow.is_gap.is_(False))
        .group_by(SpendRow.spend_date)
        .order_by(SpendRow.spend_date)
    )
    return [
        Observation(day=day, value=Decimal(total))
        for day, total in session.raw.execute(statement)
        if total is not None
    ]


def capacity_history(session: TenantSession, sda_id: uuid.UUID) -> list[Observation]:
    """Daily mean CPU across the SDA's metered resources. Unavailable rows are
    excluded (FR-020): averaging a NULL as zero is the thing that column
    exists to prevent."""
    statement = (
        session.scoped(
            select(func.date(MetricRow.period_start), func.avg(MetricRow.value)), MetricRow
        )
        .join(ResourceRow, ResourceRow.id == MetricRow.resource_id)
        .where(ResourceRow.sda_id == sda_id)
        .where(MetricRow.metric == ResourceMetricKind.CPU)
        .where(MetricRow.is_unavailable.is_(False))
        .group_by(func.date(MetricRow.period_start))
        .order_by(func.date(MetricRow.period_start))
    )
    return [
        Observation(day=day, value=Decimal(mean))
        for day, mean in session.raw.execute(statement)
        if mean is not None
    ]


__all__ = [
    "HORIZON_DAYS",
    "Backtest",
    "InsufficientHistory",
    "Observation",
    "Projection",
    "backtest",
    "capacity_history",
    "minimum_periods",
    "project",
    "spend_history",
]
