"""Insight surfaces -- `GET /insights/digest`, `/insights/runs`,
`/insights/rejections` (spec 006, T018; FR-006, FR-007a, FR-009, FR-010).

Three read surfaces, one theme: **what the intelligence layer did is
inspectable, including when it produced nothing.** A digest that silently fails
to appear is indistinguishable from a scheduler that never fired, and a
grounding validator nobody can audit is a claim rather than a control (FR-006).

`available` on the digest carries FR-007a. When the model is unreachable no
digest is stored, so this serves the last one that passed validation -- labelled
with the run and period that produced it (FR-009), so a stale digest is never
mistaken for a current one. When nothing has ever been stored, `available` is
false and the frontend renders "not enough data yet". Neither state is a
partial or placeholder digest; there is no code path here that can produce one,
because a rejected or truncated run writes no row at all.

Any role may read, matching this spec's other read surfaces.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import AgentRun as AgentRunRow
from app.models.core import GroundingRejection as GroundingRejectionRow
from app.models.core import InsightDigest as InsightDigestRow
from app.models.enums import AgentCapability, AgentRunStatus

router = APIRouter(tags=["insights"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

# FR-008a's order, named once so the surface reports the basis the platform
# actually applied rather than a string a caller has to trust.
SELECTION_BASIS = "severity_escalation_age"

# FR-006a. Runs and rejections are operational history, not an audit log --
# thirty days answers "is the layer behaving?" without accumulating forever.
HISTORY_LIMIT = 200


class DigestFigure(BaseModel):
    label: str
    value: str


class DigestReference(BaseModel):
    kind: str
    id: str
    label: str


class DigestSection(BaseModel):
    heading: str
    body: str
    figures: list[DigestFigure] = Field(default_factory=list)
    references: list[DigestReference] = Field(default_factory=list)


class InsightDigestResponse(BaseModel):
    """FR-009/FR-010. `available` and `isEmpty` are different answers, and
    collapsing them would lose the distinction the digest exists to make: "no
    digest has been produced" is a platform state, "a digest ran and found
    nothing notable" is a governance result."""

    available: bool
    generated_at: datetime | None = Field(default=None, alias="generatedAt")
    period_date: date | None = Field(default=None, alias="periodDate")
    is_empty: bool = Field(alias="isEmpty")
    selection_basis: str | None = Field(default=None, alias="selectionBasis")
    definition_hash: str | None = Field(default=None, alias="definitionHash")
    sections: list[DigestSection] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class AgentRunResponse(BaseModel):
    id: str
    capability: str
    status: str
    definition_hash: str = Field(alias="definitionHash")
    cost_units: str = Field(alias="costUnits")
    cost_cap_units: str = Field(alias="costCapUnits")
    failure_reason: str | None = Field(default=None, alias="failureReason")
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")

    model_config = {"populate_by_name": True}


class AgentRunList(BaseModel):
    runs: list[AgentRunResponse]


class GroundingRejectionResponse(BaseModel):
    id: str
    agent_run_id: str = Field(alias="agentRunId")
    rejected_reference: str = Field(alias="rejectedReference")
    reference_kind: str = Field(alias="referenceKind")
    rejected_at: datetime = Field(alias="rejectedAt")

    model_config = {"populate_by_name": True}


class GroundingRejectionList(BaseModel):
    rejections: list[GroundingRejectionResponse]


def _sections(content: dict[str, Any]) -> list[DigestSection]:
    """Read the stored structure, ignoring anything else it carries.

    `platform_figures` also lives in `content` -- the compliance baseline the
    next run reads. It is deliberately not served: it is the platform's own
    working, not part of the digest, and exposing it would invite a frontend to
    render a number the grounding validator never checked as prose.
    """
    return [
        DigestSection(
            heading=str(section.get("heading", "")),
            body=str(section.get("body", "")),
            figures=[
                DigestFigure(label=str(f.get("label", "")), value=str(f.get("value", "")))
                for f in section.get("figures", [])
            ],
            references=[
                DigestReference(
                    kind=str(r.get("kind", "")),
                    id=str(r.get("id", "")),
                    label=str(r.get("label", "")),
                )
                for r in section.get("references", [])
            ],
        )
        for section in content.get("sections", [])
    ]


@router.get(
    "/insights/digest",
    operation_id="getInsightDigest",
    summary="The most recent validated digest for this tenant",
    response_model=InsightDigestResponse,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def get_insight_digest(principal: ViewerPrincipal) -> InsightDigestResponse:
    """FR-009, FR-007a, FR-010.

    Ordered by period, not by insert time: a backfill run for an older day must
    not displace the current digest just because it was written most recently.
    """
    with tenant_session(principal.tenant_id) as session:
        statement = (
            session.scoped(select(InsightDigestRow, AgentRunRow), InsightDigestRow)
            .join(AgentRunRow, InsightDigestRow.agent_run_id == AgentRunRow.id)
            .order_by(InsightDigestRow.period_date.desc())
            .limit(1)
        )
        row = session.raw.execute(statement).first()
        if row is None:
            # Not an error and not an empty digest: nothing has been produced
            # yet. The frontend renders "not enough data yet" (FR-007a).
            return InsightDigestResponse(available=False, is_empty=False)

        digest, run = row
        return InsightDigestResponse(
            available=True,
            generated_at=digest.created_at,
            period_date=digest.period_date,
            is_empty=digest.is_empty,
            selection_basis=SELECTION_BASIS,
            definition_hash=run.definition_hash,
            sections=[] if digest.is_empty else _sections(digest.content),
        )


@router.get(
    "/insights/runs",
    operation_id="listAgentRuns",
    summary="Agent run history, including truncated and failed runs",
    response_model=AgentRunList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_agent_runs(
    principal: ViewerPrincipal,
    capability: Annotated[AgentCapability | None, Query()] = None,
    status_filter: Annotated[AgentRunStatus | None, Query(alias="status")] = None,
) -> AgentRunList:
    """FR-005, FR-007a. Failed and truncated runs are listed alongside
    successful ones -- a history showing only successes would answer "is the
    layer working?" with "yes" whatever the truth."""
    with tenant_session(principal.tenant_id) as session:
        statement = (
            session.scoped(select(AgentRunRow), AgentRunRow)
            .order_by(AgentRunRow.started_at.desc())
            .limit(HISTORY_LIMIT)
        )
        if capability is not None:
            statement = statement.where(AgentRunRow.capability == capability)
        if status_filter is not None:
            statement = statement.where(AgentRunRow.status == status_filter)

        return AgentRunList(
            runs=[
                AgentRunResponse(
                    id=str(run.id),
                    capability=run.capability.value,
                    status=run.status.value,
                    definition_hash=run.definition_hash,
                    cost_units=str(run.cost_units),
                    cost_cap_units=str(run.cost_cap_units),
                    failure_reason=run.failure_reason,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
                for run in session.raw.execute(statement).scalars()
            ]
        )


@router.get(
    "/insights/rejections",
    operation_id="listGroundingRejections",
    summary="Outputs refused before display, and what could not be validated",
    response_model=GroundingRejectionList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_grounding_rejections(principal: ViewerPrincipal) -> GroundingRejectionList:
    """FR-006. The rejected output itself is not stored and so is not served --
    keeping it would put a fabricated reference inside the platform, which is
    the thing the check exists to prevent. The reference that failed is enough
    to diagnose the rejection."""
    with tenant_session(principal.tenant_id) as session:
        statement = (
            session.scoped(select(GroundingRejectionRow), GroundingRejectionRow)
            .order_by(GroundingRejectionRow.rejected_at.desc())
            .limit(HISTORY_LIMIT)
        )
        return GroundingRejectionList(
            rejections=[
                GroundingRejectionResponse(
                    id=str(rejection.id),
                    agent_run_id=str(rejection.agent_run_id),
                    rejected_reference=rejection.rejected_reference,
                    reference_kind=rejection.reference_kind.value,
                    rejected_at=rejection.rejected_at,
                )
                for rejection in session.raw.execute(statement).scalars()
            ]
        )


__all__ = ["router"]
