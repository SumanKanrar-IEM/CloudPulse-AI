"""Lambda authorizer for the HTTP API (FR-034, FR-043).

**Why this exists instead of API Gateway's native JWT authorizer.** The native "JWT"
authorizer type rejects an invalid or missing token itself, and HTTP APIs give it no way
to customise that 401 body -- it always returns API Gateway's fixed
``{"message":"Unauthorized"}``, which breaks FR-043's uniform error envelope for exactly
the requests that never reach the app (found during T107/T109 live prod verification).

**The fix is a deliberate design, not a workaround.** This authorizer verifies the token
(signature, issuer, expiry, and audience/client-id -- the same checks the native
authorizer performed) and returns ``isAuthorized: true`` in **every** case. A token that
fails verification is not denied at the gateway; instead its failure is recorded in the
authorizer context as ``valid: "false"`` with no claim data attached, and the request is
allowed to reach the app. ``app.core.security.get_principal`` reads that context: no
verified claims means no ``sub``, which raises the app's own ``AppError(UNAUTHORIZED)`` --
the same uniform envelope every other failure already uses. The security boundary is
unchanged (an invalid token still ends in a refusal); only which layer manufactures the
401 body moves.

**This does not weaken verification.** A caller cannot forge context values -- only this
function writes them, and it writes ``valid: "true"`` only after `PyJWT` verifies the
signature against Cognito's JWKS. Unverified claims are never forwarded; on any failure
the context carries no claim fields at all, matching the "no identity" case the app
already handles as FR-034's default-refuse.

Deliberately outside the VPC, like the pre-token Lambda: it only needs to reach Cognito's
public JWKS endpoint, and putting it in private subnets would need a NAT gateway paid for
by every request just to fetch a JWT (research.md R-003's zero-cost posture).
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.logging import logger

_ISSUER = os.environ.get("CLOUDPULSE_COGNITO_ISSUER", "")
_CLIENT_ID = os.environ.get("CLOUDPULSE_COGNITO_CLIENT_ID", "")

# PyJWKClient caches keys in-process; a warm Lambda execution environment reuses this
# across invocations, so most requests cost zero JWKS round trips.
_jwk_client = PyJWKClient(f"{_ISSUER}/.well-known/jwks.json") if _ISSUER else None

_DENY_CONTEXT: dict[str, str] = {"valid": "false"}


def _verify(token: str) -> dict[str, Any] | None:
    """Return verified claims, or ``None`` on any failure. Never raises."""
    if _jwk_client is None:
        return None

    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_ISSUER,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        logger.warning("token verification failed", extra={"reason": type(exc).__name__})
        return None

    if claims.get("token_use") not in ("id", "access"):
        logger.warning("unexpected token_use claim")
        return None

    # Cognito ID tokens carry `aud`; access tokens carry `client_id` instead. The native
    # JWT authorizer checked whichever applies, so this mirrors that rather than
    # narrowing behaviour.
    audience = claims.get("aud") or claims.get("client_id")
    if audience != _CLIENT_ID:
        logger.warning("audience/client_id mismatch")
        return None

    return claims


def _context_from(claims: dict[str, Any]) -> dict[str, str]:
    """Flatten verified claims into the scalar-only shape a Lambda authorizer may return."""
    context: dict[str, str] = {"valid": "true", "sub": str(claims.get("sub", ""))}

    email = claims.get("email")
    if email is not None:
        context["email"] = str(email)

    tenant_id = claims.get("custom:tenant_id")
    if tenant_id is not None:
        context["tenant_id"] = str(tenant_id)

    groups = claims.get("cognito:groups")
    if groups is not None:
        # Distinguishing "claim present but empty" from "claim absent" is load-bearing
        # for FR-032a (security.py's _normalise_groups relies on it), so the flag travels
        # separately from the (possibly empty) joined string.
        context["groups_present"] = "true"
        context["groups"] = (
            ",".join(str(g) for g in groups) if isinstance(groups, list) else str(groups)
        )
    else:
        context["groups_present"] = "false"

    return context


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """HTTP API v2 Lambda authorizer, simple-response format.

    Always returns ``isAuthorized: true`` -- see the module docstring for why. The token
    is never trusted based on the header alone; only a JWKS-verified signature earns a
    ``valid: "true"`` context.
    """
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization") or ""

    token = auth_header.removeprefix("Bearer ").strip() if auth_header else ""
    if not token:
        return {"isAuthorized": True, "context": dict(_DENY_CONTEXT)}

    claims = _verify(token)
    if claims is None:
        return {"isAuthorized": True, "context": dict(_DENY_CONTEXT)}

    return {"isAuthorized": True, "context": _context_from(claims)}


__all__ = ["handler"]
