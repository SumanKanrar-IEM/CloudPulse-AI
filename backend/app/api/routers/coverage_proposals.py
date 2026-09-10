"""Coverage proposals and advisory gaps (spec 006, T036; FR-015a, FR-016,
FR-017, FR-018).

**Three endpoints, and the shape of the set is the point.** Proposals are
listed, advisory gaps are listed, and a proposal can be decided. There is
deliberately no decision endpoint for an advisory gap -- not a disabled one,
not one that returns 403, not one that accepts and quietly does nothing.
FR-015a's rule is that a gap needing a code change must never be offered as
acceptable, and the cleanest way to guarantee that is for the route not to
exist: no request can reach a handler that is not there, so no frontend bug,
no direct API call and no future refactor can make one acceptable by accident.

Reading is open to every role, deciding is admin-only (FR-016). A non-admin
seeing a proposal they cannot act on is intended, not an oversight: coverage is
a governance concern the whole team can see, while changing it is a decision
with an owner.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode, ErrorEnvelope, correlation_id_of
from app.core.audit import write_audit_event
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_admin, require_viewer
from app.core.users import resolve_app_user_id
from app.governance.coverage_advisor import decide as decide_proposal
from app.models.core import CoverageAdvisoryGap as AdvisoryRow
from app.models.core import CoverageProposal as ProposalRow

router = APIRouter(prefix="/coverage-proposals", tags=["coverage-proposals"])

AdminPrincipal = Annotated[Principal, Depends(require_admin)]
ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

_ALREADY_DECIDED_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "This proposal has already been accepted or rejected.",
}


class CoverageProposalResponse(BaseModel):
    id: str
    proposal_kind: str = Field(alias="proposalKind")
    resource_type: str = Field(alias="resourceType")
    evidence_account_id: str = Field(alias="evidenceAccountId")
    proposed_change: dict[str, Any] = Field(alias="proposedChange")
    review_state: str = Field(alias="reviewState")
    decided_at: datetime | None = Field(default=None, alias="decidedAt")
    applied_at: datetime | None = Field(default=None, alias="appliedAt")

    model_config = {"populate_by_name": True}


class CoverageProposalList(BaseModel):
    proposals: list[CoverageProposalResponse]


class AdvisoryGapResponse(BaseModel):
    """FR-015a. No `id` that a decision route could take, and no state field.

    The response carries nothing a client could mistake for something to act
    on -- it is a statement about what the platform cannot do yet, and the
    remedy is a release, not a click.
    """

    resource_type: str = Field(alias="resourceType")
    evidence_account_id: str = Field(alias="evidenceAccountId")
    reason: str
    observed_at: datetime = Field(alias="observedAt")

    model_config = {"populate_by_name": True}


class AdvisoryGapList(BaseModel):
    gaps: list[AdvisoryGapResponse]


class ProposalDecision(BaseModel):
    accept: bool


def _to_proposal(row: ProposalRow) -> CoverageProposalResponse:
    return CoverageProposalResponse(
        id=str(row.id),
        proposal_kind=row.proposal_kind.value,
        resource_type=row.resource_type,
        evidence_account_id=str(row.evidence_account_id),
        proposed_change=row.proposed_change,
        review_state=row.review_state.value,
        decided_at=row.decided_at,
        applied_at=row.applied_at,
    )


def _audit(
    session: TenantSession,
    *,
    principal: Principal,
    action: str,
    target_id: str,
    correlation_id: uuid.UUID,
) -> None:
    write_audit_event(
        session,
        action=action,
        target_type="coverage_proposal",
        actor_label=principal.email or principal.subject,
        target_id=target_id,
        correlation_id=correlation_id,
    )


@router.get(
    "",
    operation_id="listCoverageProposals",
    summary="Coverage gaps the platform can close as configuration",
    response_model=CoverageProposalList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_coverage_proposals(principal: ViewerPrincipal) -> CoverageProposalList:
    """FR-016. Every role may read; only an admin may decide.

    Decided proposals stay in the list rather than disappearing on decision --
    "we looked at this and said no" is the answer FR-018 needs to be visible,
    otherwise a rejected gap is indistinguishable from one never detected.
    """
    with tenant_session(principal.tenant_id) as session:
        statement = session.scoped(select(ProposalRow), ProposalRow).order_by(
            ProposalRow.resource_type
        )
        return CoverageProposalList(
            proposals=[
                _to_proposal(row) for row in session.raw.execute(statement).scalars()
            ]
        )


@router.get(
    "/advisory-gaps",
    operation_id="listCoverageAdvisoryGaps",
    summary="Coverage gaps that need a code change and cannot be accepted",
    response_model=AdvisoryGapList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_advisory_gaps(principal: ViewerPrincipal) -> AdvisoryGapList:
    """FR-015a. Read-only, for every role, with no sibling decision route.

    The reason served here is the one the advisor determined, read back from
    the row it wrote. It is not re-derived at request time: the deciding input
    is the enrichment registry behind the connector boundary (Principle V), and
    an inferred reason would be the platform's own guess presented as its
    finding.
    """
    with tenant_session(principal.tenant_id) as session:
        statement = session.scoped(select(AdvisoryRow), AdvisoryRow).order_by(
            AdvisoryRow.resource_type
        )
        return AdvisoryGapList(
            gaps=[
                AdvisoryGapResponse(
                    resource_type=row.resource_type,
                    evidence_account_id=str(row.evidence_account_id),
                    reason=row.reason,
                    observed_at=row.observed_at,
                )
                for row in session.raw.execute(statement).scalars()
            ]
        )


@router.post(
    "/{proposal_id}/decision",
    operation_id="decideCoverageProposal",
    summary="Accept or reject a coverage proposal",
    response_model=CoverageProposalResponse,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
        409: _ALREADY_DECIDED_RESPONSE,
        422: ERROR_RESPONSES[422],
    },
)
async def decide_coverage_proposal(
    proposal_id: uuid.UUID,
    body: ProposalDecision,
    request: Request,
    principal: AdminPrincipal,
) -> CoverageProposalResponse:
    """FR-016/FR-017/FR-018. Admin only, audited, and idempotent by refusal.

    An accepted proposal takes effect on the next scan with no deployment: the
    scan path reads accepted mappings as configuration. That is why this handler
    applies nothing itself -- there is no code path here that changes a cloud
    account, which is what keeps FR-016's "explicit acceptance" the whole of the
    action (Principle IV).

    A second decision on a decided proposal is a 409 rather than a silent
    re-apply: moving `applied_at` would make the audit trail misstate when the
    change took effect.
    """
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        actor_id = resolve_app_user_id(session, principal)
        try:
            row = decide_proposal(
                session, proposal_id, accept=body.accept, decided_by=actor_id
            )
        except ValueError as exc:
            raise AppError(
                ErrorCode.CONFLICT,
                status_code=status.HTTP_409_CONFLICT,
                message=str(exc),
            ) from exc
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)

        _audit(
            session,
            principal=principal,
            action="coverage_proposal.accept" if body.accept else "coverage_proposal.reject",
            target_id=str(proposal_id),
            correlation_id=correlation_id,
        )
        return _to_proposal(row)


__all__ = ["router"]
