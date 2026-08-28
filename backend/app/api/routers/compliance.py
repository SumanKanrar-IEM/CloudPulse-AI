"""Compliance scoring, per account and per SDA (FR-018-FR-019a, FR-030).

Read-only -- the score is always computed from current `Resource`/`Finding`
rows, never stored, so there is nothing to write here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_viewer
from app.governance.scoring import account_compliance_score, sda_compliance_score
from app.models.core import CloudAccount
from app.models.core import Sda as SdaRow

router = APIRouter(tags=["compliance"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


class ComplianceScore(BaseModel):
    compliant_count: int = Field(alias="compliantCount")
    total_count: int = Field(alias="totalCount")
    score: float

    model_config = {"populate_by_name": True}


def _require_account(session: TenantSession, account_id: uuid.UUID) -> None:
    stmt = session.scoped(select(CloudAccount.id), CloudAccount).where(
        CloudAccount.id == account_id
    )
    if session.raw.execute(stmt).scalar_one_or_none() is None:
        raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)


def _require_sda(session: TenantSession, sda_id: uuid.UUID) -> None:
    stmt = session.scoped(select(SdaRow.id), SdaRow).where(SdaRow.id == sda_id)
    if session.raw.execute(stmt).scalar_one_or_none() is None:
        raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)


@router.get(
    "/accounts/{account_id}/compliance-score",
    operation_id="getAccountComplianceScore",
    summary="Retrieve an account's compliance score",
    response_model=ComplianceScore,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def get_account_compliance_score(
    account_id: uuid.UUID, principal: ViewerPrincipal
) -> ComplianceScore:
    """FR-018/FR-019/FR-019a. Any role may view (FR-030)."""
    with tenant_session(principal.tenant_id) as session:
        _require_account(session, account_id)
        compliant_count, total_count, score = account_compliance_score(session, account_id)
        return ComplianceScore(
            compliant_count=compliant_count, total_count=total_count, score=score
        )


@router.get(
    "/sdas/{sda_id}/compliance-score",
    operation_id="getSdaComplianceScore",
    summary="Retrieve one SDA's compliance score",
    response_model=ComplianceScore,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def get_sda_compliance_score(
    sda_id: uuid.UUID, principal: ViewerPrincipal
) -> ComplianceScore:
    """FR-018/FR-019/FR-019a, scoped to one SDA's resources only."""
    with tenant_session(principal.tenant_id) as session:
        _require_sda(session, sda_id)
        compliant_count, total_count, score = sda_compliance_score(session, sda_id)
        return ComplianceScore(
            compliant_count=compliant_count, total_count=total_count, score=score
        )


__all__ = ["router"]
