"""Findings, filterable by account/resource/status (FR-014, FR-030).

Findings themselves are opened, re-pointed, and auto-closed exclusively by
`app.governance.validation`, driven by a scan (FR-015/FR-016); nothing here
lets a human open or close one by hand. This module also owns two spec 004
additions layered on top of an existing finding: acknowledgment (FR-015-
FR-017, FR-020) and its remediation suggestion (FR-018-FR-020a), via
`app.governance.suggestions`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode, correlation_id_of
from app.core.audit import write_audit_event
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_admin, require_operator, require_viewer
from app.governance import suggestions as suggestions_governance
from app.governance.notifications import displayed_escalated_at
from app.models.core import AppUser, Resource
from app.models.core import Finding as FindingRow
from app.models.core import Notification as NotificationRow
from app.models.core import Rule as RuleRow
from app.models.core import Sda as SdaRow
from app.models.enums import FindingStatus

router = APIRouter(prefix="/findings", tags=["findings"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]
OperatorPrincipal = Annotated[Principal, Depends(require_operator)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]

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


class SdaSummary(BaseModel):
    id: str
    name: str

    model_config = {"populate_by_name": True}


class Finding(BaseModel):
    id: str
    # spec 005, R-508: nullable now. A budget_overrun finding attaches to a
    # project, not a resource, and `ck_finding_kind_shape` guarantees exactly one
    # of `resource`/`sda` is populated for any given kind.
    resource: ResourceSummary | None = None
    sda: SdaSummary | None = None
    kind: str
    rule_key: str | None = Field(default=None, alias="ruleKey")
    rule_version: int | None = Field(default=None, alias="ruleVersion")
    severity: str
    status: str
    opened_at: datetime = Field(alias="openedAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")
    acknowledged_at: datetime | None = Field(default=None, alias="acknowledgedAt")
    acknowledged_by: str | None = Field(default=None, alias="acknowledgedBy")
    # spec 005, FR-009. Non-null exactly while the escalated state is active:
    # the column itself is never cleared, so this is derived rather than read
    # straight through (`governance.notifications.displayed_escalated_at`).
    escalated_at: datetime | None = Field(default=None, alias="escalatedAt")

    model_config = {"populate_by_name": True}


class FindingsList(BaseModel):
    findings: list[Finding]


class FindingAcknowledgment(BaseModel):
    finding_id: str = Field(alias="findingId")
    acknowledged_at: datetime = Field(alias="acknowledgedAt")
    acknowledged_by: str = Field(alias="acknowledgedBy")

    model_config = {"populate_by_name": True}


class RemediationSuggestion(BaseModel):
    finding_id: str = Field(alias="findingId")
    suggestion_text: str | None = Field(default=None, alias="suggestionText")
    blast_radius_note: str | None = Field(default=None, alias="blastRadiusNote")
    source: str | None = None

    model_config = {"populate_by_name": True}


class NotificationAttempt(BaseModel):
    """One recorded attempt, whatever its outcome (spec 005, FR-013).

    `recipientEmail` is null for every non-`sent` outcome -- there was no
    recipient, which is the point of recording the attempt at all.
    """

    id: str
    cadence_point: str = Field(alias="cadencePoint")
    outcome: str
    recipient_email: str | None = Field(default=None, alias="recipientEmail")
    attempted_at: datetime = Field(alias="attemptedAt")

    model_config = {"populate_by_name": True}


class NotificationAttempts(BaseModel):
    finding_id: str = Field(alias="findingId")
    notifications: list[NotificationAttempt]

    model_config = {"populate_by_name": True}


class RemediationSuggestionSeed(BaseModel):
    suggestion_text: str = Field(alias="suggestionText")
    blast_radius_note: str = Field(alias="blastRadiusNote")

    model_config = {"populate_by_name": True}


def _get_finding_or_404(session: TenantSession, finding_id: uuid.UUID) -> FindingRow:
    stmt = session.scoped(select(FindingRow), FindingRow).where(FindingRow.id == finding_id)
    row: FindingRow | None = session.raw.execute(stmt).scalar_one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)
    return row


def _resolve_app_user_id(session: TenantSession, principal: Principal) -> uuid.UUID:
    """Find or create the caller's `app_user` row (mirrors `me._upsert_user`).

    A signed-in caller has always hit `GET /me` at least once, but this stays
    defensive rather than assuming that row already exists.
    """
    existing = session.raw.execute(
        select(AppUser).where(AppUser.cognito_sub == principal.subject)
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    user = AppUser(cognito_sub=principal.subject, email=principal.email)
    session.add(user)
    session.flush()
    return user.id


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
        # R-508: LEFT joins, not inner ones. The previous unconditional
        # `JOIN Resource`/`JOIN Rule` silently dropped every budget_overrun
        # finding, whose resource_id and rule_id are both NULL by construction --
        # they would have been invisible in the list rather than merely
        # unformatted.
        stmt = (
            session.scoped(select(FindingRow), FindingRow)
            .outerjoin(Resource, FindingRow.resource_id == Resource.id)
            .outerjoin(RuleRow, FindingRow.rule_id == RuleRow.id)
            .outerjoin(SdaRow, FindingRow.sda_id == SdaRow.id)
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
            resource = session.raw.get(Resource, row.resource_id) if row.resource_id else None
            rule = session.raw.get(RuleRow, row.rule_id) if row.rule_id else None
            sda = session.raw.get(SdaRow, row.sda_id) if row.sda_id else None
            findings.append(
                Finding(
                    id=str(row.id),
                    resource=(
                        ResourceSummary(
                            id=str(resource.id),
                            arn=resource.arn,
                            resource_type=resource.resource_type,
                            region=resource.region,
                            account_id=str(resource.cloud_account_id),
                        )
                        if resource is not None
                        else None
                    ),
                    sda=SdaSummary(id=str(sda.id), name=sda.name) if sda is not None else None,
                    kind=row.kind.value,
                    rule_key=rule.key if rule is not None else None,
                    rule_version=row.rule_version,
                    severity=row.severity.value,
                    status=row.status.value,
                    opened_at=row.opened_at,
                    resolved_at=row.resolved_at,
                    acknowledged_at=row.acknowledged_at,
                    acknowledged_by=str(row.acknowledged_by) if row.acknowledged_by else None,
                    escalated_at=displayed_escalated_at(row),
                )
            )
        return FindingsList(findings=findings)


@router.post(
    "/{finding_id}/acknowledge",
    operation_id="acknowledgeFinding",
    summary="Acknowledge an open finding",
    response_model=FindingAcknowledgment,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def acknowledge_finding(
    finding_id: uuid.UUID, request: Request, principal: OperatorPrincipal
) -> FindingAcknowledgment:
    """FR-015-FR-017, FR-020, FR-028. Admin or operator only. Never touches
    `status` or any compliance score (FR-017). Idempotent: the `WHERE
    acknowledged_at IS NULL` guard means a near-simultaneous second attempt
    updates nothing rather than racing or duplicating (data-model.md)."""
    with tenant_session(principal.tenant_id) as session:
        _get_finding_or_404(session, finding_id)
        user_id = _resolve_app_user_id(session, principal)
        stmt = (
            update(FindingRow)
            .where(FindingRow.id == finding_id, FindingRow.acknowledged_at.is_(None))
            .values(acknowledged_at=datetime.now(UTC), acknowledged_by=user_id)
        )
        session.raw.execute(stmt)
        session.flush()
        row = _get_finding_or_404(session, finding_id)
        assert row.acknowledged_at is not None and row.acknowledged_by is not None
        write_audit_event(
            session,
            action="finding.acknowledge",
            target_type="finding",
            actor_label=principal.email or principal.subject,
            target_id=str(finding_id),
            correlation_id=correlation_id_of(request),
        )
        return FindingAcknowledgment(
            finding_id=str(row.id),
            acknowledged_at=row.acknowledged_at,
            acknowledged_by=str(row.acknowledged_by),
        )


@router.get(
    "/{finding_id}/suggestion",
    operation_id="getFindingSuggestion",
    summary="A finding's remediation suggestion, if one exists",
    response_model=RemediationSuggestion,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def get_finding_suggestion(
    finding_id: uuid.UUID, principal: ViewerPrincipal
) -> RemediationSuggestion:
    """FR-018, FR-019. Any role may view. No suggestion yet is a normal 200
    with empty fields, not a 404 -- only a missing finding is a 404."""
    with tenant_session(principal.tenant_id) as session:
        _get_finding_or_404(session, finding_id)
        suggestion = suggestions_governance.get_suggestion(session, finding_id)
        if suggestion is None:
            return RemediationSuggestion(finding_id=str(finding_id))
        return RemediationSuggestion(
            finding_id=str(finding_id),
            suggestion_text=suggestion.suggestion_text,
            blast_radius_note=suggestion.blast_radius_note,
            source=suggestion.source.value,
        )


@router.put(
    "/{finding_id}/suggestion",
    operation_id="setFindingSuggestionSeed",
    summary="Attach a demo/QA test suggestion to a finding",
    response_model=RemediationSuggestion,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def set_finding_suggestion_seed(
    finding_id: uuid.UUID,
    body: RemediationSuggestionSeed,
    request: Request,
    principal: AdminPrincipal,
) -> RemediationSuggestion:
    """FR-020a, FR-028a. Admin only. Always writes `source=admin_seeded` --
    there is no parameter here that can produce `ai_generated`."""
    with tenant_session(principal.tenant_id) as session:
        _get_finding_or_404(session, finding_id)
        suggestion = suggestions_governance.seed_suggestion(
            session, finding_id, body.suggestion_text, body.blast_radius_note
        )
        write_audit_event(
            session,
            action="finding.suggestion.seed",
            target_type="finding",
            actor_label=principal.email or principal.subject,
            target_id=str(finding_id),
            correlation_id=correlation_id_of(request),
        )
        return RemediationSuggestion(
            finding_id=str(finding_id),
            suggestion_text=suggestion.suggestion_text,
            blast_radius_note=suggestion.blast_radius_note,
            source=suggestion.source.value,
        )


@router.get(
    "/{finding_id}/notifications",
    operation_id="listFindingNotifications",
    summary="Every notification attempt recorded for a finding",
    response_model=NotificationAttempts,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def list_finding_notifications(
    finding_id: uuid.UUID, principal: ViewerPrincipal
) -> NotificationAttempts:
    """FR-013's auditable trail. Any role may view, matching this router's
    other read endpoints. A finding nothing has been attempted for is a normal
    200 with an empty list -- only a missing finding is a 404, the same
    distinction `getFindingSuggestion` already draws."""
    with tenant_session(principal.tenant_id) as session:
        _get_finding_or_404(session, finding_id)
        rows = (
            session.raw.execute(
                session.scoped(select(NotificationRow), NotificationRow)
                .where(NotificationRow.finding_id == finding_id)
                .order_by(NotificationRow.attempted_at)
            )
            .scalars()
            .all()
        )
        return NotificationAttempts(
            finding_id=str(finding_id),
            notifications=[
                NotificationAttempt(
                    id=str(row.id),
                    cadence_point=row.cadence_point.value,
                    outcome=row.outcome.value,
                    recipient_email=row.recipient_email,
                    attempted_at=row.attempted_at,
                )
                for row in rows
            ],
        )


__all__ = ["router"]
