"""Budget visibility -- `GET /budgets` (spec 005, FR-015, T030).

Read-only by design. There is no create, edit, or delete endpoint here: a
budget is created synchronously by `POST /sdas` (research.md R-502), its cap
is a platform-wide configured default rather than a per-project value, and its
four crossed-timestamp fields are written by `cost-ingestion-worker`, never by
a request. Nothing in this spec's scope gives a human a reason to write one.

Any role may read, matching the established "governance data is visible to
every role" pattern (spec 003/004, restated in this spec's Assumptions).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import Budget as BudgetRow
from app.models.core import Sda as SdaRow

router = APIRouter(tags=["budgets"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


class Budget(BaseModel):
    """One project's guardrail and which thresholds it has crossed.

    All four crossed timestamps are exposed, not just the one that opens a
    finding: FR-015 makes 80% dashboard-visible precisely *because* it sends no
    notification, so hiding it here would leave the only warning signal with
    nowhere to appear.
    """

    id: str
    sda_id: str = Field(alias="sdaId")
    sda_name: str = Field(alias="sdaName")
    amount_usd: Decimal = Field(alias="amountUsd")
    actual_80_crossed_at: datetime | None = Field(default=None, alias="actual80CrossedAt")
    actual_100_crossed_at: datetime | None = Field(default=None, alias="actual100CrossedAt")
    forecast_80_crossed_at: datetime | None = Field(default=None, alias="forecast80CrossedAt")
    forecast_100_crossed_at: datetime | None = Field(default=None, alias="forecast100CrossedAt")

    model_config = {"populate_by_name": True}


class BudgetsList(BaseModel):
    budgets: list[Budget]


@router.get(
    "/budgets",
    operation_id="listBudgets",
    summary="Every project's budget and threshold state",
    response_model=BudgetsList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_budgets(principal: ViewerPrincipal) -> BudgetsList:
    """FR-015. Any role may read. Ordered by project name, so the dashboard's
    budget rows line up with its spend-by-project table rather than arriving in
    insertion order."""
    with tenant_session(principal.tenant_id) as session:
        statement = (
            session.scoped(select(BudgetRow, SdaRow), BudgetRow)
            .join(SdaRow, BudgetRow.sda_id == SdaRow.id)
            .where(SdaRow.tenant_id == session.tenant_id)
            .order_by(SdaRow.name)
        )
        return BudgetsList(
            budgets=[
                Budget(
                    id=str(budget.id),
                    sda_id=str(budget.sda_id),
                    sda_name=sda.name,
                    amount_usd=budget.amount_usd,
                    actual_80_crossed_at=budget.actual_80_crossed_at,
                    actual_100_crossed_at=budget.actual_100_crossed_at,
                    forecast_80_crossed_at=budget.forecast_80_crossed_at,
                    forecast_100_crossed_at=budget.forecast_100_crossed_at,
                )
                for budget, sda in session.raw.execute(statement).all()
            ]
        )


__all__ = ["router"]
