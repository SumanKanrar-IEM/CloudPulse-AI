"""IAM hygiene flags -- `GET /iam-hygiene` (spec 005, FR-019, FR-020, T048).

Read-only, and that is the requirement rather than a limitation: FR-019 fixes
these as flag-only recommendations, never an automatic deletion or
deactivation, so there is deliberately no endpoint here that acts on one.

Any role may read, matching this spec's other read surfaces.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.models.core import IamHygieneFlag as FlagRow

router = APIRouter(tags=["iam-hygiene"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


class IamHygieneFlag(BaseModel):
    """One unused-principal recommendation, with the evidence behind it.

    `evidence` travels with every flag rather than being fetched separately:
    this is asking a human to delete something, and a recommendation without
    its basis is a guess presented as a fact.
    """

    id: str
    account_id: str = Field(alias="accountId")
    principal_type: str = Field(alias="principalType")
    principal_identifier: str = Field(alias="principalIdentifier")
    evidence: dict[str, Any]
    flagged_at: datetime = Field(alias="flaggedAt")
    cleared_at: datetime | None = Field(default=None, alias="clearedAt")

    model_config = {"populate_by_name": True}


class IamHygieneFlags(BaseModel):
    flags: list[IamHygieneFlag]


@router.get(
    "/iam-hygiene",
    operation_id="listIamHygieneFlags",
    summary="Roles, users, and keys that appear unused",
    response_model=IamHygieneFlags,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_iam_hygiene_flags(
    principal: ViewerPrincipal,
    account_id: Annotated[uuid.UUID | None, Query(alias="accountId")] = None,
    include_cleared: Annotated[bool, Query(alias="includeCleared")] = False,
) -> IamHygieneFlags:
    """FR-019. Active flags by default; `includeCleared=true` returns the
    history too, so an admin can see that a principal was flagged and later
    became active again rather than wondering where a flag went."""
    with tenant_session(principal.tenant_id) as session:
        statement = session.scoped(select(FlagRow), FlagRow).order_by(FlagRow.flagged_at.desc())
        if account_id is not None:
            statement = statement.where(FlagRow.cloud_account_id == account_id)
        if not include_cleared:
            statement = statement.where(FlagRow.cleared_at.is_(None))
        return IamHygieneFlags(
            flags=[
                IamHygieneFlag(
                    id=str(row.id),
                    account_id=str(row.cloud_account_id),
                    principal_type=row.principal_type.value,
                    principal_identifier=row.principal_identifier,
                    evidence=row.evidence,
                    flagged_at=row.flagged_at,
                    cleared_at=row.cleared_at,
                )
                for row in session.raw.execute(statement).scalars().all()
            ]
        )


__all__ = ["router"]
