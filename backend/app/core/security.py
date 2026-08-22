"""Role resolution and enforcement (FR-031a, FR-032, FR-032a, FR-034).

**The rule this module exists to enforce.** A caller resolves to *exactly one* role.
Zero mapped groups and two mapped groups are both **refused** — not resolved by picking
one. FR-032a says so explicitly, and the reason is worth stating: a control that
silently selects the first group looks identical to a working system from every angle
except the security one. It is the exact privilege-escalation bug the requirement was
written to prevent.

**Why this duplicates the pre-token Lambda.** research.md R-004 puts a
pre-token-generation Lambda on the Cognito pool that stamps a single role claim. This
module does *not* trust that claim. It re-derives the role from the raw
``cognito:groups`` array on every request, because:

* the API Gateway JWT authorizer validates signature, issuer, audience and expiry — it
  does **not** evaluate claim cardinality, so it cannot enforce FR-032a alone;
* a token issued before a group change keeps working until it expires, so a
  server-side re-check on every request is what actually bounds propagation (FR-038).

**No role is ever stored.** FR-031a makes the directory the sole authority. There is no
role column, no role cache, and no way to assign a role through this platform.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Final

from fastapi import Depends, Request, status

from app.api.errors import AppError, ErrorCode
from app.core.config import Role
from app.core.logging import logger

# The claim Cognito emits for group membership. An ARRAY -- which is precisely why
# cardinality has to be checked rather than assumed.
GROUPS_CLAIM: Final[str] = "cognito:groups"

# FR-039a: group -> role is DATA, mirrored from infra/envs/*/terraform.tfvars, so a
# freshly provisioned environment is governed identically to an existing one.
DEFAULT_GROUP_ROLE_MAP: Final[dict[str, Role]] = {
    "cloudpulse-admins": Role.ADMIN,
    "cloudpulse-operators": Role.OPERATOR,
    "cloudpulse-viewers": Role.VIEWER,
}

# Ordering is for display only. It is deliberately NOT used to break a multi-group tie:
# picking the highest would be privilege escalation, picking the lowest would be a
# silent downgrade. FR-032a requires refusal.
ROLE_RANK: Final[dict[Role, int]] = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


class Principal:
    """The authenticated caller for one request."""

    __slots__ = ("subject", "email", "role", "tenant_id", "correlation_id")

    def __init__(
        self,
        *,
        subject: str,
        email: str,
        role: Role,
        tenant_id: uuid.UUID,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        self.subject = subject
        self.email = email
        self.role = role
        self.tenant_id = tenant_id
        self.correlation_id = correlation_id

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Principal(subject={self.subject!r}, role={self.role.value})"


def resolve_role(
    groups: list[str] | None,
    group_role_map: dict[str, Role] | None = None,
) -> Role:
    """Derive exactly one role, or refuse (FR-032, FR-032a).

    Raises ``AppError(FORBIDDEN)`` when the claim maps to zero or more than one role.

    The three refusal cases are distinguished in the *logs* but not in the *response* —
    telling a caller "you are in two groups" is more information than an unauthenticated
    probe should get.
    """
    mapping = group_role_map or DEFAULT_GROUP_ROLE_MAP

    if groups is None:
        # A valid identity carrying no group claim at all. Must be refused, never
        # treated as an empty list that quietly matches a default -- that is the
        # "directory group claims missing from a sign-in" edge case.
        logger.warning("token carries no group claim", extra={"reason": "claim_absent"})
        raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)

    matched = {mapping[g] for g in groups if g in mapping}

    if len(matched) == 1:
        return next(iter(matched))

    if not matched:
        logger.warning(
            "no mapped group",
            extra={"reason": "no_mapped_group", "group_count": len(groups)},
        )
    else:
        # Ambiguous identity. Refused rather than resolved -- see the module docstring.
        logger.warning(
            "multiple mapped groups",
            extra={"reason": "multiple_mapped_groups", "matched_count": len(matched)},
        )

    raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)


def _claims_from(request: Request) -> dict[str, Any]:
    """Claims placed on the request by the API Gateway JWT authorizer.

    In AWS, Mangum surfaces them under the requestContext. Locally and in tests they
    are set directly on request.state by the test harness.
    """
    staged = getattr(request.state, "claims", None)
    if isinstance(staged, dict):
        return staged

    scope_event = request.scope.get("aws.event") or {}
    authorizer = (
        scope_event.get("requestContext", {}).get("authorizer", {}).get("jwt", {})
    )
    claims = authorizer.get("claims")
    return claims if isinstance(claims, dict) else {}


def _normalise_groups(raw: Any) -> list[str] | None:
    """Cognito emits the claim as a list, but API Gateway may flatten it to a string.

    Returning ``None`` for an absent claim is load-bearing: it is what lets
    ``resolve_role`` distinguish "no claim" from "empty claim", and both must be
    refused for different logged reasons.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(g) for g in raw]
    if isinstance(raw, str):
        stripped = raw.strip().strip("[]")
        return [g.strip() for g in stripped.split(",") if g.strip()] if stripped else []
    return None


def get_principal(request: Request) -> Principal:
    """Resolve the caller, or refuse (FR-034).

    Every non-public endpoint depends on this. There is no default-permit: an endpoint
    that forgets to declare a role dependency gets no principal and therefore cannot
    read a tenant-scoped session.
    """
    claims = _claims_from(request)

    subject = claims.get("sub")
    if not subject:
        raise AppError(ErrorCode.UNAUTHORIZED, status_code=status.HTTP_401_UNAUTHORIZED)

    role = resolve_role(_normalise_groups(claims.get(GROUPS_CLAIM)))

    tenant_raw = claims.get("custom:tenant_id")
    try:
        tenant_id = uuid.UUID(str(tenant_raw)) if tenant_raw else _default_tenant_id()
    except (ValueError, TypeError):
        logger.warning("malformed tenant claim")
        raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN) from None

    return Principal(
        subject=str(subject),
        email=str(claims.get("email", "")),
        role=role,
        tenant_id=tenant_id,
        correlation_id=getattr(request.state, "correlation_id", None),
    )


def _default_tenant_id() -> uuid.UUID:
    """The single seeded tenant (spec Assumptions).

    Resolved from the database rather than hardcoded, so the value cannot drift from
    what migration 0002 actually seeded.
    """
    from sqlalchemy import text

    from app.core.db import get_engine

    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).one()
    return uuid.UUID(str(row[0]))


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(*allowed: Role) -> Callable[[Principal], Principal]:
    """Dependency factory restricting an endpoint to specific roles (FR-033, FR-034).

    Every endpoint added by specs 002-006 declares its required role explicitly.
    FR-033a: there is no default-permit.
    """
    allowed_set = frozenset(allowed)

    def _dependency(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed_set:
            logger.warning(
                "role not permitted",
                extra={
                    "required": sorted(r.value for r in allowed_set),
                    "actual": principal.role.value,
                },
            )
            raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)
        return principal

    return _dependency


require_admin = require_role(Role.ADMIN)
require_operator = require_role(Role.ADMIN, Role.OPERATOR)
require_viewer = require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER)

__all__ = [
    "Principal", "CurrentPrincipal", "resolve_role", "get_principal", "require_role",
    "require_admin", "require_operator", "require_viewer",
    "GROUPS_CLAIM", "DEFAULT_GROUP_ROLE_MAP",
]
