"""Spending guardrails for a project: auto-creation, threshold crossing, and
the overrun finding (spec 005, FR-015-FR-017, T029/T034).

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

import calendar
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import Budget as BudgetRow
from app.models.core import Finding as FindingRow
from app.models.core import Sda as SdaRow
from app.models.core import SpendRecord as SpendRecordRow
from app.models.enums import FindingKind, FindingSeverity, FindingStatus

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
    "ThresholdState",
    "check_thresholds",
    "create_budget_for_sda",
    "crossings",
    "default_budget_usd",
    "month_bounds",
    "opens_a_finding",
    "project_forecast",
    "resolves_a_finding",
    "threshold_state",
]


# --- threshold crossing (T034; FR-015-FR-017, research.md R-506, R-507) ------------

# R-506: a daily average over this window, extrapolated across the days left in the
# month. Seven days rather than one, because a single unusual day (one large one-off
# charge) would otherwise falsely trip a forecast flag for the rest of the month.
_FORECAST_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ThresholdState:
    """What this project's spend looks like against its cap, right now.

    `actual_usd` is month-to-date; `forecast_usd` is that plus R-506's
    extrapolation across the remaining days. Both are absolute dollars rather
    than ratios, so a caller reporting a number to a human never has to
    reconstruct one from a percentage.
    """

    actual_usd: Decimal
    forecast_usd: Decimal
    budget_usd: Decimal

    @property
    def actual_ratio(self) -> Decimal:
        return self.actual_usd / self.budget_usd

    @property
    def forecast_ratio(self) -> Decimal:
        return self.forecast_usd / self.budget_usd


def month_bounds(day: date) -> tuple[date, date]:
    """First and last calendar day of `day`'s month.

    Calendar-aware rather than a 30-day approximation: a February forecast
    extrapolated over 30 days would overstate the month by roughly 7%, which is
    more than enough to trip an 80% flag that should not have fired.
    """
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def project_forecast(
    actual_month_to_date: Decimal, recent_daily_spend: list[Decimal], as_of: date
) -> Decimal:
    """R-506: month-to-date actual, plus a 7-day daily average across the days
    still to come.

    An empty window forecasts exactly month-to-date rather than zero or an
    error: with no recent data there is nothing to extrapolate from, and
    claiming a project will spend nothing more this month would be a guess
    dressed as a projection.
    """
    _, month_end = month_bounds(as_of)
    days_remaining = (month_end - as_of).days
    if not recent_daily_spend or days_remaining <= 0:
        return actual_month_to_date
    daily_average = sum(recent_daily_spend, Decimal("0")) / Decimal(len(recent_daily_spend))
    return actual_month_to_date + (daily_average * Decimal(days_remaining))


def crossings(state: ThresholdState) -> dict[str, bool]:
    """Which of FR-015's four thresholds this state is at or past.

    `>=` rather than `>`: spend landing exactly on the cap has reached it, and
    a budget you have exactly exhausted is not "within budget".
    """
    return {
        "actual_80": state.actual_ratio >= ACTUAL_WARNING_RATIO,
        "actual_100": state.actual_ratio >= ACTUAL_BREACH_RATIO,
        "forecast_80": state.forecast_ratio >= ACTUAL_WARNING_RATIO,
        "forecast_100": state.forecast_ratio >= ACTUAL_BREACH_RATIO,
    }


def opens_a_finding(previous_actual_100_crossed: bool, state: ThresholdState) -> bool:
    """R-507: **actual** spend reaching 100%, and only on the transition.

    Neither 80% threshold and not forecast-100 -- a forecast is a projection,
    not a fact, and opening a finding (which fires User Story 2's email) over a
    projection that may not materialise would put a false-positive-prone signal
    into the same channel real violations use.
    """
    return crossings(state)["actual_100"] and not previous_actual_100_crossed


def resolves_a_finding(state: ThresholdState) -> bool:
    """FR-017: spend has dropped back under the cap.

    This detects an already-changed external fact; it grants no remediation
    action, matching the platform-wide exclusion of remediation execution.
    """
    return not crossings(state)["actual_100"]


def _month_to_date_actual(session: TenantSession, sda_id: uuid.UUID, as_of: date) -> Decimal:
    """Gap days contribute nothing rather than zero.

    `is_gap` rows carry a NULL amount by construction (FR-002a), and SUM skips
    NULLs -- so a month containing a gap under-reports rather than inventing a
    zero for it. That is the honest direction to be wrong in for a threshold
    that opens a finding and emails someone.
    """
    month_start, _ = month_bounds(as_of)
    total = session.raw.execute(
        session.scoped(
            select(func.coalesce(func.sum(SpendRecordRow.amount_usd), 0)), SpendRecordRow
        ).where(
            SpendRecordRow.sda_id == sda_id,
            SpendRecordRow.spend_date >= month_start,
            SpendRecordRow.spend_date <= as_of,
        )
    ).scalar_one()
    return Decimal(total)


def _recent_daily_spend(session: TenantSession, sda_id: uuid.UUID, as_of: date) -> list[Decimal]:
    """One total per day over R-506's window, gap days excluded entirely.

    Excluded, not zeroed: a gap means "we do not know what this day cost", and
    averaging a false zero into the daily rate would systematically understate
    the forecast for the rest of the month.
    """
    window_start = as_of - timedelta(days=_FORECAST_WINDOW_DAYS - 1)
    rows = session.raw.execute(
        session.scoped(
            select(SpendRecordRow.spend_date, func.sum(SpendRecordRow.amount_usd)),
            SpendRecordRow,
        )
        .where(
            SpendRecordRow.sda_id == sda_id,
            SpendRecordRow.spend_date >= window_start,
            SpendRecordRow.spend_date <= as_of,
            SpendRecordRow.is_gap.is_(False),
        )
        .group_by(SpendRecordRow.spend_date)
    ).all()
    return [Decimal(total) for _, total in rows if total is not None]


def threshold_state(session: TenantSession, budget: BudgetRow, *, as_of: date) -> ThresholdState:
    actual = _month_to_date_actual(session, budget.sda_id, as_of)
    return ThresholdState(
        actual_usd=actual,
        forecast_usd=project_forecast(
            actual, _recent_daily_spend(session, budget.sda_id, as_of), as_of
        ),
        budget_usd=Decimal(budget.amount_usd),
    )


def _open_overrun_finding(session: TenantSession, sda_id: uuid.UUID) -> FindingRow:
    """R-508: attaches to the SDA, with resource/rule left NULL.

    `ck_finding_kind_shape` enforces that shape at the database, so getting it
    wrong here fails loudly rather than storing a half-formed finding.
    """
    finding = FindingRow(
        sda_id=sda_id,
        kind=FindingKind.BUDGET_OVERRUN,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    session.add(finding)
    return finding


def _open_overrun_finding_for(session: TenantSession, sda_id: uuid.UUID) -> FindingRow | None:
    statement = session.scoped(select(FindingRow), FindingRow).where(
        FindingRow.sda_id == sda_id,
        FindingRow.kind == FindingKind.BUDGET_OVERRUN,
        FindingRow.status == FindingStatus.OPEN,
    )
    row: FindingRow | None = session.raw.execute(statement).scalars().first()
    return row


def check_thresholds(
    session: TenantSession, budget: BudgetRow, *, as_of: date | None = None
) -> ThresholdState:
    """Update this budget's four crossed-timestamps, and open or resolve its
    overrun finding (FR-015-FR-017, research.md R-505/R-507).

    Runs inside `cost-ingestion-worker`'s own transaction, immediately after
    that account's spend lands (R-505) -- so the day's spend and the day's
    threshold verdict are never computed by two workers that could disagree.

    The four timestamps reset at the start of a calendar month, recognised by
    this daily run rather than by a separate scheduled job (data-model.md).
    """
    as_of = as_of or datetime.now(UTC).date()
    _reset_for_new_month(budget, as_of)

    state = threshold_state(session, budget, as_of=as_of)
    was_over = budget.actual_100_crossed_at is not None
    crossed = crossings(state)
    now = datetime.now(UTC)

    # Set on the way up, cleared on the way back down: FR-015's thresholds
    # describe the *current* state, so a project that dropped back under 80%
    # must stop showing as over it. R-507's finding trigger reads the actual-100
    # transition specifically, which `was_over` captures before any of this.
    budget.actual_80_crossed_at = _stamp(budget.actual_80_crossed_at, crossed["actual_80"], now)
    budget.actual_100_crossed_at = _stamp(budget.actual_100_crossed_at, crossed["actual_100"], now)
    budget.forecast_80_crossed_at = _stamp(
        budget.forecast_80_crossed_at, crossed["forecast_80"], now
    )
    budget.forecast_100_crossed_at = _stamp(
        budget.forecast_100_crossed_at, crossed["forecast_100"], now
    )

    existing = _open_overrun_finding_for(session, budget.sda_id)
    if opens_a_finding(was_over, state):
        # The partial unique index makes a duplicate impossible at the database;
        # checking here means the second daily run is a no-op rather than an
        # IntegrityError the worker has to catch.
        if existing is None:
            _open_overrun_finding(session, budget.sda_id)
    elif existing is not None and resolves_a_finding(state):
        existing.status = FindingStatus.RESOLVED
        existing.resolved_at = now

    session.raw.flush()
    return state


def _stamp(current: datetime | None, crossed: bool, now: datetime) -> datetime | None:
    """Keep the original crossing time while still crossed; clear once not.

    Not re-stamped every run: "when did this project first pass 80% this
    month" is the useful fact, and overwriting it daily would destroy it.
    """
    if not crossed:
        return None
    return current or now


def _reset_for_new_month(budget: BudgetRow, as_of: date) -> None:
    """data-model.md: the four timestamps are per-calendar-month.

    Recognised by this daily run, not a separate scheduled job -- one fewer
    schedule, and no window in which a new month's spend is measured against
    last month's crossings.
    """
    month_start, _ = month_bounds(as_of)
    for field in (
        "actual_80_crossed_at",
        "actual_100_crossed_at",
        "forecast_80_crossed_at",
        "forecast_100_crossed_at",
    ):
        crossed_at: datetime | None = getattr(budget, field)
        if crossed_at is not None and crossed_at.date() < month_start:
            setattr(budget, field, None)
