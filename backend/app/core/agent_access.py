"""The read-only, tenant-scoped access path for Bedrock agent action groups.

FR-056, SC-017, and constitution Principle IV (*Deterministic Core, Agentic Edge*).

Spec 006 builds against this; spec 001 provides it and constrains it. The constraints
are the point:

* an agent reaches platform data **only** through the platform API — never the data
  store directly, never a cloud account;
* it holds **no cloud credential**;
* every state-changing operation is **refused**, not merely discouraged.

Enforcing this at the foundation rather than trusting spec 006 to re-derive it is
deliberate. Principle IV says agents "never execute changes against cloud accounts" —
a rule stated once in a constitution and re-implemented by each later spec is a rule
that eventually gets implemented wrong.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from fastapi import Request, status

from app.api.errors import AppError, ErrorCode
from app.core.config import Role
from app.core.logging import logger
from app.core.security import Principal

# HTTP methods an agent may use. Anything else is refused before a route runs.
READ_ONLY_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

# The claim identifying a caller as an agent action group rather than a human.
AGENT_CLAIM: Final[str] = "custom:agent_id"


class AgentPrincipal(Principal):
    """An agent action group. Always viewer-role, always read-only.

    Subclasses Principal so existing dependencies keep working, but carries an
    ``is_agent`` marker so a route can refuse agents specifically where that matters.
    """

    __slots__ = ("agent_id",)

    def __init__(self, *, agent_id: str, tenant_id: uuid.UUID, correlation_id: uuid.UUID | None = None) -> None:
        super().__init__(
            subject=f"agent:{agent_id}",
            email="",
            # Hardcoded, not derived. An agent must never be able to obtain a role that
            # permits mutation, whatever its token claims.
            role=Role.VIEWER,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        )
        self.agent_id = agent_id

    @property
    def is_agent(self) -> bool:
        return True


def enforce_agent_read_only(request: Request, principal: Principal) -> None:
    """Refuse any state-changing operation by an agent (FR-056, SC-017).

    Checked on the HTTP method rather than per-route, so an endpoint added by a later
    spec is covered without anyone remembering to opt in. Fail-closed: a method not on
    the read-only list is refused, including ones that do not exist yet.
    """
    if not isinstance(principal, AgentPrincipal):
        return

    if request.method.upper() not in READ_ONLY_METHODS:
        logger.warning(
            "agent attempted a state-changing operation",
            extra={
                "agent_id": principal.agent_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)


def build_agent_principal(claims: dict[str, Any], correlation_id: uuid.UUID | None = None) -> AgentPrincipal:
    """Construct an agent principal from validated token claims.

    The tenant is taken from the token, never from a request parameter — an agent that
    could name its own tenant would defeat FR-030 entirely.
    """
    agent_id = claims.get(AGENT_CLAIM)
    if not agent_id:
        raise AppError(ErrorCode.UNAUTHORIZED, status_code=status.HTTP_401_UNAUTHORIZED)

    tenant_raw = claims.get("custom:tenant_id")
    if not tenant_raw:
        raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)

    try:
        tenant_id = uuid.UUID(str(tenant_raw))
    except (ValueError, TypeError):
        raise AppError(ErrorCode.FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN) from None

    return AgentPrincipal(
        agent_id=str(agent_id), tenant_id=tenant_id, correlation_id=correlation_id
    )


__all__ = [
    "AgentPrincipal", "build_agent_principal", "enforce_agent_read_only",
    "READ_ONLY_METHODS", "AGENT_CLAIM",
]
