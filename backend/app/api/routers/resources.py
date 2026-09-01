"""Resource inventory: paged/filtered listing and one resource's detail
(FR-010-FR-013, FR-030).

The platform's first paginated list endpoint (confirmed against the router
directory during planning -- no general resource-listing endpoint existed
before this spec). Read-only: this spec adds no new discovery capability,
only the API surface that exposes what account onboarding and discovery
already writes.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import Finding as FindingRow
from app.models.core import Resource
from app.models.core import ResourceOwner as ResourceOwnerRow
from app.models.core import Rule as RuleRow
from app.models.enums import FindingStatus

router = APIRouter(prefix="/resources", tags=["resources"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


class InventoryResourceSummary(BaseModel):
    id: str
    account_id: str = Field(alias="accountId")
    arn: str
    resource_type: str = Field(alias="resourceType")
    service: str
    region: str
    sda_id: str | None = Field(default=None, alias="sdaId")
    tag_status: str = Field(alias="tagStatus")
    owner_status: str = Field(alias="ownerStatus")

    model_config = {"populate_by_name": True}


class ResourcesPage(BaseModel):
    resources: list[InventoryResourceSummary]
    page: int
    page_size: int = Field(alias="pageSize")
    total_count: int = Field(alias="totalCount")

    model_config = {"populate_by_name": True}


class ResourceDetail(BaseModel):
    id: str
    arn: str
    resource_type: str = Field(alias="resourceType")
    service: str
    region: str
    tags: dict[str, str]
    detail: dict[str, Any]
    owner: dict[str, Any] | None = None
    findings: list[dict[str, Any]]

    model_config = {"populate_by_name": True}


def _parse_tag_status(value: str) -> tuple[str, str | None]:
    """Research.md R-403: a tag-compliance fact, distinct from ownership
    attribution. "compliant" or "missing:<ruleKey>" -- unit-testable in
    isolation of any database (T014)."""
    if value == "compliant":
        return ("compliant", None)
    prefix, _, rule_key = value.partition(":")
    if prefix == "missing" and rule_key:
        return ("missing", rule_key)
    raise AppError(
        ErrorCode.VALIDATION_FAILED,
        status_code=422,
        message='tagStatus must be "compliant" or "missing:<ruleKey>".',
    )


def _open_finding_rule_keys(session: TenantSession, resource_id: uuid.UUID) -> set[str]:
    # select_from is load-bearing: selecting only RuleRow.key without it leaves
    # SQLAlchemy unable to tell FindingRow is the driving table to join RuleRow
    # onto (found by running this, not by inspection -- "don't know how to join
    # to Rule").
    stmt = (
        select(RuleRow.key)
        .select_from(FindingRow)
        .join(RuleRow, FindingRow.rule_id == RuleRow.id)
        .where(
            FindingRow.resource_id == resource_id,
            FindingRow.status == FindingStatus.OPEN,
            RuleRow.tenant_id == session.tenant_id,
        )
    )
    return set(session.raw.execute(stmt).scalars().all())


def _tag_status_of(session: TenantSession, resource_id: uuid.UUID) -> str:
    open_keys = _open_finding_rule_keys(session, resource_id)
    if not open_keys:
        return "compliant"
    return f"missing:{sorted(open_keys)[0]}"


def _has_owner(session: TenantSession, resource_id: uuid.UUID) -> bool:
    stmt = session.scoped(select(ResourceOwnerRow.id), ResourceOwnerRow).where(
        ResourceOwnerRow.resource_id == resource_id
    )
    return session.raw.execute(stmt).scalar_one_or_none() is not None


@router.get(
    "",
    operation_id="listResources",
    summary="List the resource inventory, paged and filtered",
    response_model=ResourcesPage,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403], 422: ERROR_RESPONSES[422]},
)
async def list_resources(
    principal: ViewerPrincipal,
    account_id: Annotated[uuid.UUID | None, Query(alias="accountId")] = None,
    service: Annotated[str | None, Query()] = None,
    region: Annotated[str | None, Query()] = None,
    sda_id: Annotated[str | None, Query(alias="sdaId")] = None,
    tag_status: Annotated[str | None, Query(alias="tagStatus")] = None,
    owner_status: Annotated[str | None, Query(alias="ownerStatus")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", ge=1, le=_MAX_PAGE_SIZE)
    ] = _DEFAULT_PAGE_SIZE,
) -> ResourcesPage:
    """FR-010, FR-011. Any role may view (FR-030). Excludes soft-deleted
    resources by default (FR-030's own "never a row deletion" note -- a
    deleted resource has no governance action to take, but its detail view
    stays reachable directly by ID, data-model.md)."""
    parsed_tag_status = _parse_tag_status(tag_status) if tag_status is not None else None
    if owner_status is not None and owner_status != "unattributed":
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            status_code=422,
            message='ownerStatus must be "unattributed".',
        )

    with tenant_session(principal.tenant_id) as session:
        stmt = session.scoped(select(Resource), Resource).where(Resource.deleted_at.is_(None))
        if account_id is not None:
            stmt = stmt.where(Resource.cloud_account_id == account_id)
        if service is not None:
            stmt = stmt.where(Resource.service == service)
        if region is not None:
            stmt = stmt.where(Resource.region == region)
        if sda_id is not None:
            stmt = stmt.where(
                Resource.sda_id.is_(None) if sda_id == "none" else Resource.sda_id == sda_id
            )
        stmt = stmt.order_by(Resource.first_seen_at.desc())

        rows = session.raw.execute(stmt).scalars().all()

        summaries: list[InventoryResourceSummary] = []
        for row in rows:
            row_tag_status = _tag_status_of(session, row.id)
            if parsed_tag_status is not None:
                kind, rule_key = parsed_tag_status
                if kind == "compliant" and row_tag_status != "compliant":
                    continue
                if kind == "missing" and row_tag_status != f"missing:{rule_key}":
                    continue

            row_has_owner = _has_owner(session, row.id)
            if owner_status == "unattributed" and row_has_owner:
                continue

            summaries.append(
                InventoryResourceSummary(
                    id=str(row.id),
                    account_id=str(row.cloud_account_id),
                    arn=row.arn,
                    resource_type=row.resource_type,
                    service=row.service,
                    region=row.region,
                    sda_id=str(row.sda_id) if row.sda_id else None,
                    tag_status=row_tag_status,
                    owner_status="attributed" if row_has_owner else "unattributed",
                )
            )

        total_count = len(summaries)
        start = (page - 1) * page_size
        page_items = summaries[start : start + page_size]
        return ResourcesPage(
            resources=page_items, page=page, page_size=page_size, total_count=total_count
        )


@router.get(
    "/{resource_id}",
    operation_id="getResourceDetail",
    summary="One resource's tags, owner + evidence, findings, and enrichment detail",
    response_model=ResourceDetail,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def get_resource_detail(resource_id: uuid.UUID, principal: ViewerPrincipal) -> ResourceDetail:
    """FR-012. Any role may view (FR-030). Reachable even for a soft-deleted
    resource (data-model.md) -- only the default listing excludes those."""
    with tenant_session(principal.tenant_id) as session:
        resource_stmt = session.scoped(select(Resource), Resource).where(Resource.id == resource_id)
        resource = session.raw.execute(resource_stmt).scalar_one_or_none()
        if resource is None:
            raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)

        owner_stmt = session.scoped(select(ResourceOwnerRow), ResourceOwnerRow).where(
            ResourceOwnerRow.resource_id == resource_id
        )
        owner_row = session.raw.execute(owner_stmt).scalar_one_or_none()
        owner = (
            None
            if owner_row is None
            else {
                "ownerEmail": owner_row.owner_email,
                "confidence": owner_row.confidence.value,
                "evidence": owner_row.evidence,
            }
        )

        findings_stmt = (
            session.scoped(select(FindingRow), FindingRow)
            .join(RuleRow, FindingRow.rule_id == RuleRow.id)
            .where(FindingRow.resource_id == resource_id, RuleRow.tenant_id == session.tenant_id)
            .order_by(FindingRow.opened_at.desc())
        )
        finding_rows = session.raw.execute(findings_stmt).scalars().all()
        findings = []
        for finding_row in finding_rows:
            rule = session.raw.get(RuleRow, finding_row.rule_id)
            assert rule is not None  # FK guarantees this
            findings.append(
                {
                    "id": str(finding_row.id),
                    "ruleKey": rule.key,
                    "severity": finding_row.severity.value,
                    "status": finding_row.status.value,
                    "openedAt": finding_row.opened_at.isoformat(),
                }
            )

        return ResourceDetail(
            id=str(resource.id),
            arn=resource.arn,
            resource_type=resource.resource_type,
            service=resource.service,
            region=resource.region,
            tags=resource.tags,
            detail=resource.detail,
            owner=owner,
            findings=findings,
        )


__all__ = ["router"]
