"""Budget-overrun findings -- `GET /budget-overruns` (spec 005, FR-016, T036d).

**Why this is a separate endpoint rather than a `kind` branch inside
`GET /findings`.** A budget-overrun finding attaches to a project and has no
resource at all (research.md R-508). `GET /findings`'s response schema requires
`resource`, and every way of expressing "the resource may be absent" -- making
the property optional, or making it nullable via `anyOf` -- is a breaking
response change that `contract-compat` correctly rejects under FR-048b
(`response-property-became-optional`, then `response-required-property-removed`
on the nested properties). Serving overruns here instead keeps that contract
untouched and additive.

FR-016's actual requirement is unaffected: an overrun is the same `Finding`
row, opened and resolved by `governance.budgets`, acknowledged through the same
`POST /findings/{findingId}/acknowledge`, notified and escalated by the same
machinery as any other finding. Only the *read* surface is separate, because
the two kinds genuinely have different shapes.

Any role may read, matching this spec's other read surfaces.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.governance.notifications import displayed_escalated_at
from app.models.core import Budget as BudgetRow
from app.models.core import Finding as FindingRow
from app.models.core import Sda as SdaRow
from app.models.enums import FindingKind, FindingStatus

router = APIRouter(tags=["budget-overruns"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


class BudgetOverrun(BaseModel):
    """One overrun finding, carrying the project it is about.

    The same lifecycle fields a tag-violation finding exposes -- this is one
    `Finding` row, not a parallel entity, and it moves through exactly the same
    open/acknowledge/resolve/suppress states.
    """

    id: str
    sda_id: str = Field(alias="sdaId")
    sda_name: str = Field(alias="sdaName")
    budget_usd: str | None = Field(default=None, alias="budgetUsd")
    severity: str
    status: str
    opened_at: datetime = Field(alias="openedAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")
    acknowledged_at: datetime | None = Field(default=None, alias="acknowledgedAt")
    escalated_at: datetime | None = Field(default=None, alias="escalatedAt")

    model_config = {"populate_by_name": True}


class BudgetOverrunsList(BaseModel):
    overruns: list[BudgetOverrun]


@router.get(
    "/budget-overruns",
    operation_id="listBudgetOverruns",
    summary="Findings opened by a project exceeding its budget",
    response_model=BudgetOverrunsList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_budget_overruns(
    principal: ViewerPrincipal,
    status_filter: Annotated[FindingStatus | None, Query(alias="status")] = None,
) -> BudgetOverrunsList:
    """FR-016. Most recently opened first, matching `GET /findings`'s ordering
    so the two lists read as one workbench rather than two conventions."""
    with tenant_session(principal.tenant_id) as session:
        statement = (
            session.scoped(select(FindingRow, SdaRow, BudgetRow), FindingRow)
            .join(SdaRow, FindingRow.sda_id == SdaRow.id)
            .outerjoin(BudgetRow, BudgetRow.sda_id == SdaRow.id)
            .where(
                SdaRow.tenant_id == session.tenant_id,
                FindingRow.kind == FindingKind.BUDGET_OVERRUN,
            )
            .order_by(FindingRow.opened_at.desc())
        )
        if status_filter is not None:
            statement = statement.where(FindingRow.status == status_filter)

        return BudgetOverrunsList(
            overruns=[
                BudgetOverrun(
                    id=str(finding.id),
                    sda_id=str(sda.id),
                    sda_name=sda.name,
                    budget_usd=str(budget.amount_usd) if budget is not None else None,
                    severity=finding.severity.value,
                    status=finding.status.value,
                    opened_at=finding.opened_at,
                    resolved_at=finding.resolved_at,
                    acknowledged_at=finding.acknowledged_at,
                    escalated_at=displayed_escalated_at(finding),
                )
                for finding, sda, budget in session.raw.execute(statement).all()
            ]
        )


__all__ = ["router"]
