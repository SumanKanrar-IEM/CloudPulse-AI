"""Owner-identity resolution: raw audit-trail identity to a contact email
(FR-027, FR-028, S23a).

FR-027's precedence, in order: a syntactically valid email in the resource's
own `owner` tag wins outright; else the admin-configured pattern applied to
the audit-trail identity; else the manual override table. If none resolve,
the caller keeps the raw principal identity it already had (quickstart.md
V4's documented behavior) -- this chain never invents a value.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.core.db import TenantSession
from app.models.core import OwnerIdentityOverride, Tenant

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The one placeholder the pattern template supports -- the audit-trail
# identity's trailing path segment (e.g. "alice" from an IAM user ARN).
_PATTERN_PLACEHOLDER = "{principal_local_part}"


def _is_valid_email(value: str | None) -> bool:
    return value is not None and bool(_EMAIL_RE.match(value))


def _owner_tag_value(tags: dict[str, str]) -> str | None:
    tags_lower = {k.lower(): v for k, v in tags.items()}
    return tags_lower.get("owner")


def resolve_owner_email(
    session: TenantSession, tags: dict[str, str], principal_id: str
) -> str | None:
    """FR-027's chain. Returns `None` if nothing resolves."""
    owner_tag = _owner_tag_value(tags)
    if _is_valid_email(owner_tag):
        return owner_tag

    pattern = session.raw.execute(
        select(Tenant.owner_identity_pattern).where(Tenant.id == session.tenant_id)
    ).scalar_one_or_none()
    if pattern:
        local_part = principal_id.rsplit("/", 1)[-1]
        candidate = pattern.replace(_PATTERN_PLACEHOLDER, local_part)
        if _is_valid_email(candidate):
            return candidate

    override = session.raw.execute(
        session.scoped(select(OwnerIdentityOverride), OwnerIdentityOverride).where(
            OwnerIdentityOverride.principal_id == principal_id
        )
    ).scalar_one_or_none()
    if override is not None:
        return str(override.owner_email)

    return None


__all__ = ["resolve_owner_email"]
