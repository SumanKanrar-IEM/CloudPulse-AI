"""SDA registry: registration, editing, removal, and the "No SDA" bucket
(FR-007-FR-010b, FR-012's P1 API half, FR-029, FR-030).

Registering/editing/removing is admin-only (FR-029); viewing -- including the "No
SDA" bucket -- is open to every role (FR-030), the same split spec 002 and this
spec's `rules.py` already established.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode, ErrorEnvelope, correlation_id_of
from app.core.audit import write_audit_event
from app.core.db import TenantSession, tenant_session
from app.core.security import Principal, require_admin, require_viewer
from app.governance.sda_matching import mappings_overlap
from app.models.core import Resource
from app.models.core import Sda as SdaRow

router = APIRouter(tags=["sdas"])

AdminPrincipal = Annotated[Principal, Depends(require_admin)]
ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

_OVERLAP_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "This tag-value mapping overlaps an already-registered SDA's mapping.",
}


# --- Schemas -----------------------------------------------------------------------


class Sda(BaseModel):
    id: str
    name: str
    owner_email: str = Field(alias="ownerEmail")
    team: str | None = None
    tag_values: dict[str, str] = Field(alias="tagValues")

    model_config = {"populate_by_name": True}


class SdaCreate(BaseModel):
    name: str
    owner_email: str = Field(alias="ownerEmail")
    team: str | None = None
    tag_values: dict[str, str] = Field(alias="tagValues")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class SdaUpdate(BaseModel):
    owner_email: str | None = Field(default=None, alias="ownerEmail")
    team: str | None = None
    tag_values: dict[str, str] | None = Field(default=None, alias="tagValues")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class SdasList(BaseModel):
    sdas: list[Sda]


class ResourceSummary(BaseModel):
    id: str
    arn: str
    resource_type: str = Field(alias="resourceType")
    region: str
    account_id: str = Field(alias="accountId")

    model_config = {"populate_by_name": True}


class UnmatchedResourcesList(BaseModel):
    resources: list[ResourceSummary]


# --- Helpers ---------------------------------------------------------------------


def _to_sda_model(row: SdaRow) -> Sda:
    return Sda(
        id=str(row.id),
        name=row.name,
        owner_email=row.owner_email,
        team=row.team,
        tag_values=dict(row.tag_values),
    )


def _reject_overlap(
    session: TenantSession, tag_values: dict[str, str], *, exclude_id: uuid.UUID | None
) -> None:
    """FR-010a, research.md R-305. `exclude_id` lets an edit compare a mapping
    against every *other* SDA without tripping over itself."""
    stmt = session.scoped(select(SdaRow), SdaRow)
    if exclude_id is not None:
        stmt = stmt.where(SdaRow.id != exclude_id)
    existing = session.raw.execute(stmt).scalars().all()
    for other in existing:
        if mappings_overlap(tag_values, dict(other.tag_values)):
            raise AppError(
                ErrorCode.CONFLICT,
                status_code=status.HTTP_409_CONFLICT,
                message=(
                    f"This tag-value mapping overlaps SDA {other.name!r}'s mapping. "
                    "Which SDA a resource belongs to must never be ambiguous."
                ),
            )


def _get_or_404(session: TenantSession, sda_id: uuid.UUID) -> SdaRow:
    stmt = session.scoped(select(SdaRow), SdaRow).where(SdaRow.id == sda_id)
    row: SdaRow | None = session.raw.execute(stmt).scalar_one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)
    return row


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
        target_type="sda",
        actor_label=principal.email or principal.subject,
        target_id=target_id,
        correlation_id=correlation_id,
    )


# --- Routes ------------------------------------------------------------------


@router.get(
    "/sdas",
    operation_id="listSdas",
    summary="List every registered SDA",
    response_model=SdasList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_sdas(principal: ViewerPrincipal) -> SdasList:
    """FR-007. Any role may view (FR-030)."""
    with tenant_session(principal.tenant_id) as session:
        rows = session.raw.execute(session.scoped(select(SdaRow), SdaRow)).scalars().all()
        return SdasList(sdas=[_to_sda_model(r) for r in rows])


@router.post(
    "/sdas",
    operation_id="registerSda",
    summary="Register a new SDA",
    response_model=Sda,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        409: _OVERLAP_RESPONSE,
        422: ERROR_RESPONSES[422],
    },
)
async def register_sda(body: SdaCreate, request: Request, principal: AdminPrincipal) -> Sda:
    """FR-007. Admin only (FR-029). Refused with 409 if the mapping overlaps an
    existing SDA's (FR-010a)."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        _reject_overlap(session, body.tag_values, exclude_id=None)
        row = SdaRow(
            name=body.name,
            owner_email=body.owner_email,
            team=body.team,
            tag_values=body.tag_values,
        )
        session.add(row)
        session.flush()
        _audit(
            session,
            principal=principal,
            action="sda.register",
            target_id=str(row.id),
            correlation_id=correlation_id,
        )
        return _to_sda_model(row)


@router.patch(
    "/sdas/{sda_id}",
    operation_id="updateSda",
    summary="Edit an SDA's tag-value mapping",
    response_model=Sda,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
        409: _OVERLAP_RESPONSE,
    },
)
async def update_sda(
    sda_id: uuid.UUID, body: SdaUpdate, request: Request, principal: AdminPrincipal
) -> Sda:
    """FR-010. Admin only. Reclassification of matching resources happens at the
    next scan (Phase 7's worker calls `sda_matching.reclassify_account_resources`),
    not here -- this endpoint only updates the SDA row itself."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        row = _get_or_404(session, sda_id)
        new_tag_values = body.tag_values if body.tag_values is not None else dict(row.tag_values)
        if body.tag_values is not None:
            _reject_overlap(session, new_tag_values, exclude_id=sda_id)
        if body.owner_email is not None:
            row.owner_email = body.owner_email
        if body.team is not None:
            row.team = body.team
        row.tag_values = new_tag_values
        session.flush()
        _audit(
            session,
            principal=principal,
            action="sda.update",
            target_id=str(row.id),
            correlation_id=correlation_id,
        )
        return _to_sda_model(row)


@router.delete(
    "/sdas/{sda_id}",
    operation_id="removeSda",
    summary="Remove an SDA",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def remove_sda(sda_id: uuid.UUID, request: Request, principal: AdminPrincipal) -> None:
    """FR-010b. Admin only. Never refused for having attached resources -- the
    `ON DELETE SET NULL` foreign key is what immediately reverts every attached
    resource to the "No SDA" bucket, not application code, and not deferred to
    the next scan (Acceptance Scenario US2.5)."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        row = _get_or_404(session, sda_id)
        row_id = str(row.id)
        session.raw.delete(row)
        session.flush()
        _audit(
            session,
            principal=principal,
            action="sda.remove",
            target_id=row_id,
            correlation_id=correlation_id,
        )


@router.get(
    "/sdas/unmatched-resources",
    operation_id="listUnmatchedResources",
    summary='List resources in the "No SDA" bucket',
    response_model=UnmatchedResourcesList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_unmatched_resources(
    principal: ViewerPrincipal,
    account_id: Annotated[uuid.UUID | None, Query(alias="accountId")] = None,
) -> UnmatchedResourcesList:
    """FR-009/FR-012. Any role may view (FR-030) -- the P1 API the P2 triage
    screen (FR-012) consumes; this endpoint itself is P1 since FR-009's
    visibility requirement is P1."""
    with tenant_session(principal.tenant_id) as session:
        stmt = session.scoped(select(Resource), Resource).where(
            Resource.sda_id.is_(None),
            Resource.parent_resource_id.is_(None),
            Resource.deleted_at.is_(None),
        )
        if account_id is not None:
            stmt = stmt.where(Resource.cloud_account_id == account_id)
        rows = session.raw.execute(stmt).scalars().all()
        return UnmatchedResourcesList(
            resources=[
                ResourceSummary(
                    id=str(r.id),
                    arn=r.arn,
                    resource_type=r.resource_type,
                    region=r.region,
                    account_id=str(r.cloud_account_id),
                )
                for r in rows
            ]
        )


__all__ = ["router"]
