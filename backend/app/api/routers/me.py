"""The current caller (FR-034, FR-033a).

Returns the identity and the role **derived from directory group membership on this
request** — never a stored value. FR-031a makes the directory the sole authority, so
there is no role field to read and no way to change one through this API.

The `app_user` row is created just in time on first authenticated request. It exists
only to attribute audit events and display a name; it holds no password and no role, so
creating it grants nothing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.logging import logger
from app.core.security import CurrentPrincipal
from app.models.core import AppUser
from pydantic import BaseModel, Field
from sqlalchemy import select

router = APIRouter(tags=["identity"])


class CurrentUser(BaseModel):
    user_id: str = Field(alias="userId")
    email: str
    display_name: str | None = Field(default=None, alias="displayName")
    role: str = Field(
        description="Derived from directory group membership; never stored by the platform."
    )
    tenant_id: str = Field(alias="tenantId")

    model_config = {"populate_by_name": True}


def _upsert_user(principal: Any) -> tuple[str, str | None]:
    """Find or create the caller's `app_user` row, and refresh `last_seen_at`.

    Just-in-time rather than provisioned ahead of time: there is no registration path
    (FR-031), so the first authenticated request is the only moment the row can appear.
    """
    with tenant_session(principal.tenant_id) as session:
        existing = session.raw.execute(
            select(AppUser).where(AppUser.cognito_sub == principal.subject)
        ).scalar_one_or_none()

        if existing is None:
            user = AppUser(cognito_sub=principal.subject, email=principal.email)
            session.add(user)
            session.flush()
            logger.info("created app_user on first authenticated request")
            return str(user.id), user.display_name

        from sqlalchemy import func

        existing.last_seen_at = func.now()
        session.flush()
        return str(existing.id), existing.display_name


@router.get(
    "/me",
    operation_id="getCurrentUser",
    summary="The signed-in caller and their resolved role",
    response_model=CurrentUser,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        500: ERROR_RESPONSES[500],
    },
)
async def get_current_user(principal: CurrentPrincipal) -> dict[str, Any]:
    """Any caller with exactly one resolved role may read this, and no one else.

    A caller mapping to zero or multiple directory groups never reaches here —
    `get_principal` raises 403 first (FR-032a).
    """
    user_id, display_name = _upsert_user(principal)
    return CurrentUser(
        userId=user_id,
        email=principal.email,
        displayName=display_name,
        role=principal.role.value,
        tenantId=str(principal.tenant_id),
    ).model_dump(by_alias=True, exclude_none=True)


__all__ = ["router", "CurrentUser"]
