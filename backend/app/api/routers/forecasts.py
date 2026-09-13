"""`GET /forecasts` -- per-project spend and capacity projections with their
backtested error (spec 006, T047; FR-021, FR-021a, FR-022, S51).

**Computed on request, not read from a table.** The calculation is
deterministic (FR-022), cheap (a least-squares line over at most thirty
points per project), and needs no state beyond the history it reads. Storing
a forecast would only be worth it to compare it with actuals later -- and the
backtest does exactly that, reproducibly, from the same history on every
request. `forecast` rows are not written by this endpoint; see tasks.md T047a.

**`insufficientHistory` is a field, not an absence.** FR-021a. A project below
the minimum appears in the list with `insufficientHistory: true`, a null
projection, and the counts a reader needs to know how far off sufficient is.
Dropping it from the response would make "no forecast" indistinguishable from
"no project", which is the difference SC-006 needs to be able to see.

**No model call on this path.** FR-021. The router calls `forecasting`, which
imports nothing that can reach one, and `test_forecasting.py` asserts that
against the module's source.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_viewer
from app.governance.forecasting import (
    Backtest,
    InsufficientHistory,
    Observation,
    backtest,
    capacity_history,
    minimum_periods,
    project,
    spend_history,
)
from app.models.core import Sda as SdaRow
from app.models.enums import ForecastKind

router = APIRouter(tags=["forecasts"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

# A week held out. Long enough that a backtest error means something; short
# enough that a project with the minimum history still has more to train on
# than to test against.
BACKTEST_HELD_OUT_DAYS = 7


class BacktestResponse(BaseModel):
    training_days: int = Field(alias="trainingDays")
    held_out_days: int = Field(alias="heldOutDays")
    projected_value: Decimal = Field(alias="projectedValue")
    actual_value: Decimal = Field(alias="actualValue")
    # None when the held-out actual was zero: a percentage of nothing.
    absolute_percentage_error: Decimal | None = Field(default=None, alias="absolutePercentageError")

    model_config = {"populate_by_name": True}


class ForecastResponse(BaseModel):
    """One kind for one project. Either a projection or the reason there is
    none -- never both, never neither."""

    kind: str
    insufficient_history: bool = Field(alias="insufficientHistory")
    history_days: int = Field(alias="historyDays")
    required_days: int = Field(alias="requiredDays")
    period_start: date | None = Field(default=None, alias="periodStart")
    period_end: date | None = Field(default=None, alias="periodEnd")
    projected_value: Decimal | None = Field(default=None, alias="projectedValue")
    backtest: BacktestResponse | None = None

    model_config = {"populate_by_name": True}


class ProjectForecasts(BaseModel):
    sda_id: str = Field(alias="sdaId")
    sda_name: str = Field(alias="sdaName")
    forecasts: list[ForecastResponse]

    model_config = {"populate_by_name": True}


class ForecastList(BaseModel):
    generated_at: datetime = Field(alias="generatedAt")
    projects: list[ProjectForecasts]

    model_config = {"populate_by_name": True}


def _forecast(kind: ForecastKind, history: list[Observation], *, today: date) -> ForecastResponse:
    result = project(kind, history, period_start=today + timedelta(days=1))
    if isinstance(result, InsufficientHistory):
        return ForecastResponse(
            kind=kind.value,
            insufficient_history=True,
            history_days=result.history_days,
            required_days=result.required_days,
        )

    tested = backtest(kind, history, held_out_days=BACKTEST_HELD_OUT_DAYS)
    return ForecastResponse(
        kind=kind.value,
        insufficient_history=False,
        history_days=result.history_days,
        # The threshold the projection cleared, so a reader sees both numbers
        # whether or not the project was near it.
        required_days=minimum_periods(),
        period_start=result.period_start,
        period_end=result.period_end,
        projected_value=result.projected_value,
        backtest=(
            BacktestResponse(
                training_days=tested.training_days,
                held_out_days=tested.held_out_days,
                projected_value=tested.projected_value,
                actual_value=tested.actual_value,
                absolute_percentage_error=tested.absolute_percentage_error,
            )
            if isinstance(tested, Backtest)
            else None
        ),
    )


def _project_forecasts(session: TenantSession, sda: SdaRow, *, today: date) -> ProjectForecasts:
    return ProjectForecasts(
        sda_id=str(sda.id),
        sda_name=sda.name,
        forecasts=[
            _forecast(ForecastKind.SPEND, spend_history(session, sda.id), today=today),
            _forecast(ForecastKind.CAPACITY, capacity_history(session, sda.id), today=today),
        ],
    )


@router.get(
    "/forecasts",
    operation_id="listForecasts",
    summary="Per-project spend and capacity forecasts, with backtested error",
    response_model=ForecastList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_forecasts(principal: ViewerPrincipal) -> ForecastList:
    """FR-021, FR-021a, FR-022. Every project, every kind, every time -- a
    project with no history is listed with the not-enough-data state rather
    than left out."""
    now = datetime.now(UTC)
    with tenant_session(principal.tenant_id) as session:
        sdas = session.raw.execute(
            session.scoped(select(SdaRow), SdaRow).order_by(SdaRow.name)
        ).scalars()
        return ForecastList(
            generated_at=now,
            projects=[_project_forecasts(session, sda, today=now.date()) for sda in sdas],
        )


__all__ = ["router"]
