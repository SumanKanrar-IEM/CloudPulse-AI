"""Resource ownership (FR-020-FR-028, FR-030) and, for P2 (S23a), the
owner-identity resolution config an admin maintains (FR-027-FR-029).

Attribution itself is written exclusively by `app.governance.ownership`,
driven by the ownership-attribution worker (T027) -- `GET .../owner` has no
write counterpart, the same split `findings.py` follows for the validation
pipeline. The pattern/override endpoints below are genuine admin-write
surfaces, since they are the "admin-editable configuration" FR-028 requires.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode, correlation_id_of
from app.core.audit import write_audit_event
from app.core.db import tenant_session
from app.core.security import Principal, require_admin, require_viewer
from app.models.core import OwnerIdentityOverride, Resource, Tenant
from app.models.core import ResourceOwner as ResourceOwnerRow

router = APIRouter(tags=["ownership"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]


class OwnershipEvidence(BaseModel):
    kind: str
    cloudtrail_event_id: str | None = Field(default=None, alias="cloudtrailEventId")
    principal: str | None = None
    event_time: str | None = Field(default=None, alias="eventTime")

    model_config = {"populate_by_name": True}


class ResourceOwnership(BaseModel):
    resource_id: str = Field(alias="resourceId")
    owner_email: str | None = Field(default=None, alias="ownerEmail")
    confidence: str | None = None
    evidence: OwnershipEvidence | None = None
    attributed_at: datetime | None = Field(default=None, alias="attributedAt")

    model_config = {"populate_by_name": True}


@router.get(
    "/resources/{resource_id}/owner",
    operation_id="getResourceOwner",
    summary="Retrieve a resource's attributed owner",
    response_model=ResourceOwnership,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def get_resource_owner(
    resource_id: uuid.UUID, principal: ViewerPrincipal
) -> ResourceOwnership:
    """FR-020-FR-028. Any role may view (FR-030). 200 with a null `ownerEmail`/
    `confidence` (not 404) when the resource exists but is queued
    unattributed (FR-022) -- a resource genuinely not found still 404s."""
    with tenant_session(principal.tenant_id) as session:
        resource_stmt = session.scoped(select(Resource.id), Resource).where(
            Resource.id == resource_id
        )
        if session.raw.execute(resource_stmt).scalar_one_or_none() is None:
            raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)

        owner_stmt = session.scoped(select(ResourceOwnerRow), ResourceOwnerRow).where(
            ResourceOwnerRow.resource_id == resource_id
        )
        owner = session.raw.execute(owner_stmt).scalar_one_or_none()
        if owner is None:
            return ResourceOwnership(resource_id=str(resource_id))

        evidence_raw = owner.evidence or {}
        return ResourceOwnership(
            resource_id=str(resource_id),
            owner_email=owner.owner_email,
            confidence=owner.confidence.value,
            evidence=OwnershipEvidence(
                kind=evidence_raw.get("kind", "direct"),
                cloudtrail_event_id=evidence_raw.get("cloudtrail_event_id"),
                principal=evidence_raw.get("principal"),
                event_time=evidence_raw.get("event_time"),
            ),
            attributed_at=owner.attributed_at,
        )


# --- P2 (S23a): owner-identity resolution config -------------------------------


class OwnerIdentityPatternBody(BaseModel):
    pattern: str | None = None


class OwnerIdentityOverrideBody(BaseModel):
    principal_id: str = Field(alias="principalId")
    owner_email: str = Field(alias="ownerEmail")

    model_config = {"populate_by_name": True}


class OwnerIdentityOverridesList(BaseModel):
    overrides: list[OwnerIdentityOverrideBody]


def _to_override_model(row: OwnerIdentityOverride) -> OwnerIdentityOverrideBody:
    return OwnerIdentityOverrideBody(principal_id=row.principal_id, owner_email=row.owner_email)


@router.get(
    "/owner-identity-pattern",
    operation_id="getOwnerIdentityPattern",
    summary="Retrieve the configured owner-identity resolution pattern",
    response_model=OwnerIdentityPatternBody,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def get_owner_identity_pattern(principal: ViewerPrincipal) -> OwnerIdentityPatternBody:
    """FR-028. Any role may view."""
    with tenant_session(principal.tenant_id) as session:
        pattern = session.raw.execute(
            select(Tenant.owner_identity_pattern).where(Tenant.id == session.tenant_id)
        ).scalar_one_or_none()
        return OwnerIdentityPatternBody(pattern=pattern)


@router.put(
    "/owner-identity-pattern",
    operation_id="setOwnerIdentityPattern",
    summary="Set the owner-identity resolution pattern",
    response_model=OwnerIdentityPatternBody,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        422: ERROR_RESPONSES[422],
    },
)
async def set_owner_identity_pattern(
    body: OwnerIdentityPatternBody, request: Request, principal: AdminPrincipal
) -> OwnerIdentityPatternBody:
    """FR-028. Admin only (FR-029) -- takes effect immediately, no redeploy."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        tenant = session.raw.get(Tenant, session.tenant_id)
        assert tenant is not None  # the tenant owning this session always exists
        tenant.owner_identity_pattern = body.pattern
        session.flush()
        write_audit_event(
            session,
            action="owner_identity_pattern.set",
            target_type="tenant",
            actor_label=principal.email or principal.subject,
            target_id=str(session.tenant_id),
            correlation_id=correlation_id,
        )
        return OwnerIdentityPatternBody(pattern=body.pattern)


@router.get(
    "/owner-identity-overrides",
    operation_id="listOwnerIdentityOverrides",
    summary="List manual owner-identity overrides",
    response_model=OwnerIdentityOverridesList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_owner_identity_overrides(principal: ViewerPrincipal) -> OwnerIdentityOverridesList:
    """FR-027. Any role may view."""
    with tenant_session(principal.tenant_id) as session:
        rows = (
            session.raw.execute(
                session.scoped(select(OwnerIdentityOverride), OwnerIdentityOverride)
            )
            .scalars()
            .all()
        )
        return OwnerIdentityOverridesList(overrides=[_to_override_model(r) for r in rows])


@router.put(
    "/owner-identity-overrides",
    operation_id="setOwnerIdentityOverride",
    summary="Create or replace a manual owner-identity override",
    response_model=OwnerIdentityOverrideBody,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        422: ERROR_RESPONSES[422],
    },
)
async def set_owner_identity_override(
    body: OwnerIdentityOverrideBody, request: Request, principal: AdminPrincipal
) -> OwnerIdentityOverrideBody:
    """FR-027. Admin only (FR-029). Upserts on `(tenant_id, principal_id)` --
    consulted last in the resolution chain, after the owner tag and pattern."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        insert_stmt = pg_insert(OwnerIdentityOverride).values(
            tenant_id=session.tenant_id,
            principal_id=body.principal_id,
            owner_email=body.owner_email,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["tenant_id", "principal_id"],
            set_={"owner_email": insert_stmt.excluded.owner_email},
        ).returning(OwnerIdentityOverride.id)
        row_id = session.raw.execute(stmt).scalar_one()
        session.flush()
        write_audit_event(
            session,
            action="owner_identity_override.set",
            target_type="owner_identity_override",
            actor_label=principal.email or principal.subject,
            target_id=str(row_id),
            correlation_id=correlation_id,
        )
        return body


__all__ = ["router"]
