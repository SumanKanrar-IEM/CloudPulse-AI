"""Spend visibility -- `GET /spend`, `GET /spend/summary` (FR-001-FR-003).

Any role may read (spec 003/004's established "governance data is visible to
every role" pattern, restated in this spec's own Assumptions).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import Sda as SdaRow
from app.models.core import SpendRecord as SpendRecordRow

router = APIRouter(tags=["spend"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

_NO_SDA_FILTER = "none"


def _parse_sda_id(raw: str) -> uuid.UUID:
    """`sdaId` is typed as a string, not a UUID, so the literal `"none"`
    sentinel can share the parameter -- which means FastAPI does not validate
    the UUID case for us, and a malformed value would otherwise reach
    `uuid.UUID()` and surface as an unhandled 500 rather than a 422.
    """
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            status_code=422,
            message=f'sdaId must be a UUID, or the literal "{_NO_SDA_FILTER}".',
        ) from None


# --- Schemas -----------------------------------------------------------------------


class SpendRecord(BaseModel):
    account_id: str = Field(alias="accountId")
    sda_id: str | None = Field(default=None, alias="sdaId")
    service: str | None = None
    spend_date: date = Field(alias="spendDate")
    amount_usd: Decimal | None = Field(default=None, alias="amountUsd")
    is_gap: bool = Field(alias="isGap")

    model_config = {"populate_by_name": True}


class SpendList(BaseModel):
    spend: list[SpendRecord]


class SpendByProject(BaseModel):
    sda_id: str | None = Field(default=None, alias="sdaId")
    sda_name: str | None = Field(default=None, alias="sdaName")
    total_usd: Decimal = Field(alias="totalUsd")

    model_config = {"populate_by_name": True}


class SpendTrendPoint(BaseModel):
    date: date
    total_usd: Decimal | None = Field(default=None, alias="totalUsd")

    model_config = {"populate_by_name": True}


class SpendSummary(BaseModel):
    total_usd: Decimal = Field(alias="totalUsd")
    by_project: list[SpendByProject] = Field(alias="byProject")
    trend: list[SpendTrendPoint]

    model_config = {"populate_by_name": True}


# --- GET /spend ----------------------------------------------------------------


@router.get(
    "/spend",
    operation_id="listSpend",
    summary="Daily spend records, optionally filtered",
    response_model=SpendList,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        422: ERROR_RESPONSES[422],
    },
)
async def list_spend(
    principal: ViewerPrincipal,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
    account_id: Annotated[uuid.UUID | None, Query(alias="accountId")] = None,
    sda_id: Annotated[str | None, Query(alias="sdaId")] = None,
) -> SpendList:
    """FR-001, FR-003. `sdaId=none` filters to the "No SDA" bucket specifically
    -- distinct from omitting the parameter, which applies no SDA filter at
    all."""
    with tenant_session(principal.tenant_id) as session:
        stmt = session.scoped(select(SpendRecordRow), SpendRecordRow).where(
            SpendRecordRow.spend_date >= from_, SpendRecordRow.spend_date <= to
        )
        if account_id is not None:
            stmt = stmt.where(SpendRecordRow.cloud_account_id == account_id)
        if sda_id == _NO_SDA_FILTER:
            stmt = stmt.where(SpendRecordRow.sda_id.is_(None))
        elif sda_id is not None:
            stmt = stmt.where(SpendRecordRow.sda_id == _parse_sda_id(sda_id))

        rows = session.raw.execute(stmt).scalars().all()
        return SpendList(
            spend=[
                SpendRecord(
                    account_id=str(r.cloud_account_id),
                    sda_id=str(r.sda_id) if r.sda_id else None,
                    service=r.service,
                    spend_date=r.spend_date,
                    amount_usd=r.amount_usd,
                    is_gap=r.is_gap,
                )
                for r in rows
            ]
        )


# --- GET /spend/summary ---------------------------------------------------------


@router.get(
    "/spend/summary",
    operation_id="getSpendSummary",
    summary="Org-wide spend totals with trend, for the cost dashboard",
    response_model=SpendSummary,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def get_spend_summary(
    principal: ViewerPrincipal,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
) -> SpendSummary:
    """FR-003, SC-002. Org-wide (no account filter) -- every registered
    account's spend, rolled up.

    A trend day is `null` if *any* account has a gap for that day (FR-002a) --
    a conservative "this total is not the whole picture" signal, since a
    partial sum presented as complete would be worse than an honest null.
    """
    with tenant_session(principal.tenant_id) as session:
        rows = (
            session.raw.execute(
                session.scoped(select(SpendRecordRow), SpendRecordRow).where(
                    SpendRecordRow.spend_date >= from_, SpendRecordRow.spend_date <= to
                )
            )
            .scalars()
            .all()
        )
        sdas = {
            s.id: s.name
            for s in session.raw.execute(session.scoped(select(SdaRow), SdaRow)).scalars().all()
        }

        real_rows = [r for r in rows if not r.is_gap]
        total_usd = sum((r.amount_usd or Decimal(0) for r in real_rows), Decimal(0))

        by_project: dict[uuid.UUID | None, Decimal] = {}
        for r in real_rows:
            by_project[r.sda_id] = by_project.get(r.sda_id, Decimal(0)) + (
                r.amount_usd or Decimal(0)
            )

        gap_days = {r.spend_date for r in rows if r.is_gap}
        totals_by_day: dict[date, Decimal] = {}
        for r in real_rows:
            totals_by_day[r.spend_date] = totals_by_day.get(r.spend_date, Decimal(0)) + (
                r.amount_usd or Decimal(0)
            )

        trend: list[SpendTrendPoint] = []
        day = from_
        while day <= to:
            if day in gap_days:
                trend.append(SpendTrendPoint(date=day, total_usd=None))
            else:
                trend.append(
                    SpendTrendPoint(date=day, total_usd=totals_by_day.get(day, Decimal(0)))
                )
            day = date.fromordinal(day.toordinal() + 1)

        return SpendSummary(
            total_usd=total_usd,
            by_project=[
                SpendByProject(
                    sda_id=str(sda_id) if sda_id else None,
                    sda_name=sdas.get(sda_id) if sda_id else None,
                    total_usd=amount,
                )
                for sda_id, amount in by_project.items()
            ],
            trend=trend,
        )


__all__ = ["router"]
