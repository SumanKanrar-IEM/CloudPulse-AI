"""Resolving the caller's `app_user` row (spec 001, FR-031).

There is no registration path, so the first authenticated request is the only
moment a user row can appear. Anything that needs to *record* who acted -- a
finding acknowledgement, a coverage decision -- needs that row's id, and so
needs this.

`me.py` keeps its own variant rather than calling this one: it also refreshes
`last_seen_at` and returns the display name, and opens its own session because
it is the entry point rather than a step inside someone else's transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import TenantSession
from app.core.security import Principal
from app.models.core import AppUser


def resolve_app_user_id(session: TenantSession, principal: Principal) -> uuid.UUID:
    """Find or create the caller's `app_user` row and return its id.

    A signed-in caller has always hit `GET /me` at least once, so the row
    normally exists. Creating it here anyway keeps a write that must record an
    actor from failing on the one request where it does not.
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


__all__ = ["resolve_app_user_id"]
