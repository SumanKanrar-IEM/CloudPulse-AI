"""Utilization visibility -- `GET /utilization` (spec 005, FR-018, T040).

Computed live on each request (research.md R-509): an indexed count over rows
spec 002 already persisted, cheap enough at demo scale that a cached snapshot
or a nightly precompute would be premature optimization -- and both would
introduce a staleness window this endpoint does not otherwise have.

Any role may read, matching the established "governance data is visible to
every role" pattern.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_viewer
from app.governance import utilization as utilization_governance
from app.models.core import CloudAccount
from app.models.core import Sda as SdaRow

router = APIRouter(tags=["utilization"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


class UtilizationFigure(BaseModel):
    """A utilization percentage and the population it was measured over.

    `percent` is null, never 0 or 100, when nothing measurable exists -- and
    `used`/`provisioned` are always present so a caller can state the scope
    ("2 of 4 enriched resources") rather than implying a claim over the whole
    inventory (R-509).
    """

    used: int
    provisioned: int
    percent: float | None

    model_config = {"populate_by_name": True}


class AccountUtilization(BaseModel):
    account_id: str = Field(alias="accountId")
    alias: str
    utilization: UtilizationFigure

    model_config = {"populate_by_name": True}


class ProjectUtilization(BaseModel):
    sda_id: str | None = Field(alias="sdaId")
    sda_name: str | None = Field(alias="sdaName")
    utilization: UtilizationFigure

    model_config = {"populate_by_name": True}


class UtilizationReport(BaseModel):
    overall: UtilizationFigure
    by_account: list[AccountUtilization] = Field(alias="byAccount")
    by_project: list[ProjectUtilization] = Field(alias="byProject")

    model_config = {"populate_by_name": True}


def _figure(value: utilization_governance.Utilization) -> UtilizationFigure:
    return UtilizationFigure(used=value.used, provisioned=value.provisioned, percent=value.percent)


def _account_names(session: TenantSession) -> dict[uuid.UUID, str]:
    rows = session.raw.execute(
        session.scoped(select(CloudAccount.id, CloudAccount.alias), CloudAccount)
    ).all()
    return {account_id: alias for account_id, alias in rows}


def _sda_names(session: TenantSession) -> dict[uuid.UUID, str]:
    rows = session.raw.execute(session.scoped(select(SdaRow.id, SdaRow.name), SdaRow)).all()
    return {sda_id: name for sda_id, name in rows}


@router.get(
    "/utilization",
    operation_id="getUtilization",
    summary="Utilization overall, per account, and per project",
    response_model=UtilizationReport,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def get_utilization(principal: ViewerPrincipal) -> UtilizationReport:
    """FR-018. One response carries all three levels, which is what makes the
    account-to-project-to-resource drill-down reachable in three steps without
    a request per expansion."""
    with tenant_session(principal.tenant_id) as session:
        accounts = _account_names(session)
        sdas = _sda_names(session)
        return UtilizationReport(
            overall=_figure(utilization_governance.compute_utilization(session)),
            by_account=[
                AccountUtilization(
                    account_id=str(account_id),
                    alias=accounts.get(account_id, "unknown"),
                    utilization=_figure(value),
                )
                for account_id, value in utilization_governance.utilization_by_account(
                    session
                ).items()
            ],
            by_project=[
                ProjectUtilization(
                    # `None` is the "No SDA" bucket -- the same one spend and
                    # inventory already use for unattributed resources, not a
                    # missing value.
                    sda_id=str(sda_id) if sda_id else None,
                    sda_name=sdas.get(sda_id) if sda_id else None,
                    utilization=_figure(value),
                )
                for sda_id, value in utilization_governance.utilization_by_sda(session).items()
            ],
        )


__all__ = ["router"]
