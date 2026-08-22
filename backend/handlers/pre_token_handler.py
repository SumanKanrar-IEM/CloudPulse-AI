"""Cognito pre-token-generation trigger (FR-032, research.md R-004).

**Layer 1 of two.** This stamps a single ``custom:role`` claim when the caller belongs
to exactly one mapped group, and stamps nothing otherwise. ``app.core.security`` then
re-derives the role from the raw group claim on every request and refuses anything that
is not exactly one — it never trusts what this function wrote.

Two layers because one is not enough:

* the API Gateway JWT authorizer validates signature, issuer, audience and expiry, but
  **not claim cardinality**, so it cannot enforce FR-032a by itself;
* a token issued before a group change keeps working until it expires, so only a
  server-side re-check bounds propagation (FR-038);
* and a control that silently picks the first of two groups is exactly the
  privilege-escalation bug FR-032a exists to prevent — it looks like success from every
  angle except the security one.

This function **never fails the sign-in**. Cognito treats a trigger error as an
authentication failure, and refusing to issue a token is a worse outcome than issuing
one with no role claim: the application refuses the request either way, but the second
produces a clear 403 rather than an opaque login error.
"""

from __future__ import annotations

import os
from typing import Any

from app.core.logging import logger

GROUPS_CLAIM = "cognito:groups"
ROLE_CLAIM = "custom:role"

# Mirrors infra/envs/*/terraform.tfvars (FR-039a: the mapping is data, not code).
# Overridable by environment so a redeploy can change it without a code change.
DEFAULT_GROUP_ROLE_MAP: dict[str, str] = {
    "cloudpulse-admins": "admin",
    "cloudpulse-operators": "operator",
    "cloudpulse-viewers": "viewer",
}


def _group_role_map() -> dict[str, str]:
    raw = os.environ.get("CLOUDPULSE_GROUP_ROLE_MAP", "")
    if not raw:
        return DEFAULT_GROUP_ROLE_MAP
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            group, role = pair.split(":", 1)
            mapping[group.strip()] = role.strip()
    return mapping or DEFAULT_GROUP_ROLE_MAP


def resolve_single_role(groups: list[str] | None, mapping: dict[str, str]) -> str | None:
    """Return the role when exactly one maps, otherwise ``None``.

    ``None`` covers three distinct cases -- no claim, no mapped group, and more than one
    mapped group. They are logged separately but treated identically here: no claim is
    stamped, and the application refuses the request.
    """
    if not groups:
        return None
    matched = {mapping[g] for g in groups if g in mapping}
    return next(iter(matched)) if len(matched) == 1 else None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Add ``custom:role`` to the token when the group claim is unambiguous."""
    try:
        request = event.get("request", {})
        groups = request.get("groupConfiguration", {}).get("groupsToOverride")
        if groups is None:
            groups = request.get("userAttributes", {}).get(GROUPS_CLAIM)
            if isinstance(groups, str):
                groups = [g.strip() for g in groups.split(",") if g.strip()]

        mapping = _group_role_map()
        role = resolve_single_role(groups, mapping)

        if role is None:
            matched = len({mapping[g] for g in (groups or []) if g in mapping})
            logger.warning(
                "no single role resolved; issuing token without a role claim",
                extra={
                    "reason": (
                        "claim_absent"
                        if not groups
                        else "multiple_mapped_groups"
                        if matched > 1
                        else "no_mapped_group"
                    ),
                    "matched_count": matched,
                },
            )
            # No claim suppression, no default. The application refuses (FR-032a).
            return event

        event.setdefault("response", {}).setdefault("claimsOverrideDetails", {}).setdefault(
            "claimsToAddOrOverride", {}
        )[ROLE_CLAIM] = role

        logger.info("role claim stamped", extra={"role": role})
        return event

    except Exception as exc:
        # Never fail the sign-in. See the module docstring: a trigger error becomes an
        # opaque authentication failure, which is worse than a clear 403 later.
        logger.exception(
            "pre-token trigger failed; issuing token unchanged",
            extra={"error_type": type(exc).__name__},
        )
        return event


__all__ = ["handler", "resolve_single_role", "ROLE_CLAIM", "DEFAULT_GROUP_ROLE_MAP"]
