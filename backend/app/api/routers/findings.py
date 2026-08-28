"""Findings, filterable by account/resource/status (FR-014, FR-030).

Read-only -- there is no write route here. Findings are opened, re-pointed, and
auto-closed exclusively by `app.governance.validation`, driven by a scan
(FR-015/FR-016); nothing about this spec lets a human open or close one by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import Finding as FindingRow
from app.models.core import Resource
from app.models.core import Rule as RuleRow
from app.models.enums import FindingStatus

router = APIRouter(prefix="/findings", tags=["findings"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

# FR-014: the three violation kinds `evaluate_rule_against_tags` (validation.py)
# can return, exposed as-is on the wire.
_KIND_VALUES = ("missing_tag", "invalid_value", "invalid_format")


class ResourceSummary(BaseModel):
    id: str
    arn: str
    resource_type: str = Field(alias="resourceType")
    region: str
    account_id: str = Field(alias="accountId")

    model_config = {"populate_by_name": True}


class Finding(BaseModel):
    id: str
    resource: ResourceSummary
    rule_key: str = Field(alias="ruleKey")
    rule_version: int = Field(alias="ruleVersion")
    severity: str
    status: str
    opened_at: datetime = Field(alias="openedAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")

    model_config = {"populate_by_name": True}


class FindingsList(BaseModel):
    findings: list[Finding]


@router.get(
    "",
    operation_id="listFindings",
    summary="List findings",
    response_model=FindingsList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_findings(
    principal: ViewerPrincipal,
    account_id: Annotated[uuid.UUID | None, Query(alias="accountId")] = None,
    resource_id: Annotated[uuid.UUID | None, Query(alias="resourceId")] = None,
    status_filter: Annotated[FindingStatus | None, Query(alias="status")] = None,
) -> FindingsList:
    """FR-014. Any role may view (FR-030). Most recently opened first."""
    with tenant_session(principal.tenant_id) as session:
        stmt = (
            session.scoped(select(FindingRow), FindingRow)
            .join(Resource, FindingRow.resource_id == Resource.id)
            .join(RuleRow, FindingRow.rule_id == RuleRow.id)
            .where(Resource.tenant_id == session.tenant_id, RuleRow.tenant_id == session.tenant_id)
            .order_by(FindingRow.opened_at.desc())
        )
        if account_id is not None:
            stmt = stmt.where(Resource.cloud_account_id == account_id)
        if resource_id is not None:
            stmt = stmt.where(FindingRow.resource_id == resource_id)
        if status_filter is not None:
            stmt = stmt.where(FindingRow.status == status_filter)

        rows = session.raw.execute(stmt).scalars().all()
        findings: list[Finding] = []
        for row in rows:
            resource = session.raw.get(Resource, row.resource_id)
            rule = session.raw.get(RuleRow, row.rule_id)
            assert resource is not None and rule is not None  # FK guarantees this
            findings.append(
                Finding(
                    id=str(row.id),
                    resource=ResourceSummary(
                        id=str(resource.id),
                        arn=resource.arn,
                        resource_type=resource.resource_type,
                        region=resource.region,
                        account_id=str(resource.cloud_account_id),
                    ),
                    rule_key=rule.key,
                    rule_version=row.rule_version,
                    severity=row.severity.value,
                    status=row.status.value,
                    opened_at=row.opened_at,
                    resolved_at=row.resolved_at,
                )
            )
        return FindingsList(findings=findings)


__all__ = ["router"]
