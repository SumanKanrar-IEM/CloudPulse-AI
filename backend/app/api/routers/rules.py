"""Tagging rules, expressed as admin-editable data (FR-001-FR-006a).

A rule's `key` is its stable identity across edits; editing creates a new version
under the same key rather than mutating a row in place (research.md R-301,
Clarifications session 2026-08-25) -- this is what lets an already-open finding
follow a rule across an edit instead of being orphaned against a superseded version
(see `app.governance.validation`, Phase 5).

Reading is open to every role (FR-030); creating and editing are admin-only (FR-029),
reusing spec 001's `require_role`/`require_viewer` exactly as spec 002 did.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode, ErrorEnvelope, correlation_id_of
from app.core.audit import write_audit_event
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_admin, require_viewer
from app.models.core import Rule as RuleRow

router = APIRouter(prefix="/rules", tags=["rules"])

AdminPrincipal = Annotated[Principal, Depends(require_admin)]
ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

_CONFLICT_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "A rule with this key is already registered.",
}


# --- Schemas -----------------------------------------------------------------------


class RuleDefinition(BaseModel):
    """FR-004: three independent checks a rule may express, any subset of them."""

    required: bool
    allowed_values: list[str] | None = Field(default=None, alias="allowedValues")
    format_pattern: str | None = Field(default=None, alias="formatPattern")
    severity: Literal["low", "medium", "high", "critical"] = "medium"

    model_config = {"populate_by_name": True, "extra": "forbid"}


class RuleCreate(BaseModel):
    key: str
    definition: RuleDefinition

    model_config = {"populate_by_name": True, "extra": "forbid"}


class RuleUpdate(BaseModel):
    """No `key` field, deliberately (FR-006): an edit targets a key via the URL
    path, never the request body."""

    definition: RuleDefinition
    enabled: bool | None = None

    model_config = {"populate_by_name": True, "extra": "forbid"}


class Rule(BaseModel):
    id: str
    key: str
    version: int
    enabled: bool
    definition: RuleDefinition
    effective_from: str | None = Field(default=None, alias="effectiveFrom")

    model_config = {"populate_by_name": True}


class RulesList(BaseModel):
    rules: list[Rule]


# --- Helpers -------------------------------------------------------------------


def _to_rule_model(row: RuleRow) -> Rule:
    return Rule(
        id=str(row.id),
        key=row.key,
        version=row.version,
        enabled=row.enabled,
        definition=RuleDefinition.model_validate(row.definition),
        effective_from=row.effective_from.isoformat() if row.effective_from else None,
    )


def _latest_version(session: TenantSession, key: str) -> RuleRow | None:
    """The current version for a key -- the one row every read and every edit
    treats as authoritative (research.md R-301: `key`, not `id`, is the stable
    identity)."""
    stmt = (
        session.scoped(select(RuleRow), RuleRow)
        .where(RuleRow.key == key)
        .order_by(RuleRow.version.desc())
        .limit(1)
    )
    return session.raw.execute(stmt).scalars().first()


def _audit(
    session: TenantSession,
    *,
    principal: Principal,
    action: str,
    target_id: str | None,
    correlation_id: uuid.UUID,
) -> None:
    write_audit_event(
        session,
        action=action,
        target_type="rule",
        actor_label=principal.email or principal.subject,
        target_id=target_id,
        correlation_id=correlation_id,
    )


# --- Routes ------------------------------------------------------------------


@router.get(
    "",
    operation_id="listRules",
    summary="List every tagging rule",
    response_model=RulesList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_rules(principal: ViewerPrincipal) -> RulesList:
    """FR-001-FR-004. All three roles may view (FR-030). One row per key -- the
    latest version, via `DISTINCT ON` ordered by version descending."""
    with tenant_session(principal.tenant_id) as session:
        stmt = (
            session.scoped(select(RuleRow), RuleRow)
            .distinct(RuleRow.key)
            .order_by(RuleRow.key, RuleRow.version.desc())
        )
        rows = session.raw.execute(stmt).scalars().all()
        return RulesList(rules=[_to_rule_model(r) for r in rows])


@router.post(
    "",
    operation_id="createRule",
    summary="Create a new tagging rule",
    response_model=Rule,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        409: _CONFLICT_RESPONSE,
        422: ERROR_RESPONSES[422],
    },
)
async def create_rule(body: RuleCreate, request: Request, principal: AdminPrincipal) -> Rule:
    """FR-001. Admin only (FR-029). Refused if the key already exists -- editing an
    existing key is PATCH's job (FR-006), not a second POST."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        if _latest_version(session, body.key) is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                status_code=status.HTTP_409_CONFLICT,
                message=f"A rule with key {body.key!r} already exists. Use PATCH to edit it.",
            )
        row = RuleRow(
            key=body.key,
            version=1,
            definition=body.definition.model_dump(mode="json", by_alias=False),
            enabled=True,
        )
        session.add(row)
        session.flush()
        _audit(
            session,
            principal=principal,
            action="rule.create",
            target_id=str(row.id),
            correlation_id=correlation_id,
        )
        return _to_rule_model(row)


@router.patch(
    "/{rule_key}",
    operation_id="updateRule",
    summary="Edit a tagging rule",
    response_model=Rule,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
        422: ERROR_RESPONSES[422],
    },
)
async def update_rule(
    rule_key: str, body: RuleUpdate, request: Request, principal: AdminPrincipal
) -> Rule:
    """FR-005/FR-006. Admin only. Creates a new version under the same key
    (research.md R-301) rather than mutating the existing version in place -- the
    edit takes effect starting with the next scan that begins after this call, never
    a scan already in progress (Clarifications session 2026-08-25)."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        current = _latest_version(session, rule_key)
        if current is None:
            raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)
        row = RuleRow(
            key=rule_key,
            version=current.version + 1,
            definition=body.definition.model_dump(mode="json", by_alias=False),
            enabled=body.enabled if body.enabled is not None else current.enabled,
        )
        session.add(row)
        session.flush()
        _audit(
            session,
            principal=principal,
            action="rule.update",
            target_id=str(row.id),
            correlation_id=correlation_id,
        )
        return _to_rule_model(row)


__all__ = ["router"]
