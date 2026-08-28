"""Resource ownership, read-only (FR-020-FR-028, FR-030).

Ownership is written exclusively by `app.governance.ownership`, driven by the
ownership-attribution worker (T027) -- there is no write route here, the same
split `findings.py` follows for the validation pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import Resource
from app.models.core import ResourceOwner as ResourceOwnerRow

router = APIRouter(tags=["ownership"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


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


__all__ = ["router"]
