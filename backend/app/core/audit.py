"""Append-only audit writing (FR-040).

Every privileged or state-changing action writes a record naming the actor, the
action, the target and the time. This module is the *only* sanctioned way to do it,
and it exposes exactly one verb: write.

There is deliberately no update, no delete, and no bulk-purge helper. FR-029 makes
audit events immutable and FR-029a makes them permanent, so the correct API surface is
the absence of anything that could violate either. The database enforces the same rule
twice more -- a trigger and a withheld grant (migration ``0003``) -- because a control
that exists only in application code lasts until the next developer writes raw SQL.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from app.core.db import TenantSession
from app.models.core import AuditEvent

# Values that must never reach the payload. FR-046 forbids them in logs; an audit
# payload is a log that is kept forever, so the bar is at least as high.
REDACTED: Final[str] = "[redacted]"
SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_key",
        "secret_key",
        "secret_access_key",
        "session_token",
        "authorization",
        "api_key",
        "private_key",
        "credential",
        "credentials",
    }
)


def _redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip sensitive values, recursively.

    Applied at the write boundary rather than trusted to callers: a permanent record
    is the worst possible place to discover a leaked secret, and by then it cannot be
    deleted -- by design.
    """
    if payload is None:
        return None

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (REDACTED if k.lower() in SENSITIVE_KEYS else _walk(v)) for k, v in value.items()
            }
        if isinstance(value, list):
            return [_walk(v) for v in value]
        return value

    walked: dict[str, Any] = _walk(payload)
    return walked


def write_audit_event(
    session: TenantSession,
    *,
    action: str,
    target_type: str,
    actor_label: str,
    actor_user_id: uuid.UUID | None = None,
    target_id: str | None = None,
    correlation_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Write one audit event (FR-040).

    Keyword-only throughout: positional arguments across seven similar strings are a
    silent-mix-up waiting to happen, and this record is permanent.

    ``actor_label`` is required even when ``actor_user_id`` is given, so a system or
    pipeline actor -- which has no ``app_user`` row -- is still attributable, and so
    the label survives changes to the user row.
    """
    if not action or not target_type:
        raise ValueError("audit events require both an action and a target_type (FR-040)")
    if not actor_label:
        raise ValueError(
            "audit events require an actor_label; an unattributable record does not "
            "satisfy FR-040"
        )

    event = AuditEvent(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        correlation_id=correlation_id,
        payload=_redact(payload),
    )
    session.add(event)  # stamps tenant_id (FR-030)
    session.flush()
    return event


__all__ = ["write_audit_event", "SENSITIVE_KEYS", "REDACTED"]
