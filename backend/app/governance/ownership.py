"""Direct-creator ownership attribution (FR-020-FR-023, research.md R-302) and
its P2 fallback chain (FR-024-FR-026).

Correlates `connectors.aws.sweep_cloudtrail_events`'s in-memory event map
against the scan's persisted resource set -- one guarded write per resource,
so a later, lower-confidence result never overwrites an existing
higher-confidence attribution (FR-023). A resource whose creator is
automation rather than human falls back to its most frequent human modifier
(`connectors.aws.sweep_write_events`), provided that human meets FR-025's
>=3-write-event threshold; short of that, it stays unattributed (FR-026)
rather than a below-threshold guess.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import Resource, ResourceOwner
from app.models.enums import OwnerConfidence


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _write_attribution(
    session: TenantSession,
    *,
    resource_id: uuid.UUID,
    owner_email: str,
    confidence: OwnerConfidence,
    evidence: dict[str, Any],
    attributed_at: datetime,
) -> bool:
    """FR-023: a guarded upsert -- the write only ever takes effect if the new
    confidence is the same or better than any existing row's.

    `owner_confidence` is declared `(high, medium, low)` in migration 0001, so
    Postgres's native enum ordinal has `high` sort first/smallest -- "new is
    same-or-better than existing" is therefore exactly
    `EXCLUDED.confidence <= resource_owner.confidence`, not the other
    direction. Returns whether this call actually wrote (inserted or
    updated) a row.
    """
    insert_stmt = pg_insert(ResourceOwner).values(
        tenant_id=session.tenant_id,
        resource_id=resource_id,
        owner_email=owner_email,
        confidence=confidence,
        evidence=evidence,
        attributed_at=attributed_at,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["tenant_id", "resource_id"],
        set_={
            "owner_email": insert_stmt.excluded.owner_email,
            "confidence": insert_stmt.excluded.confidence,
            "evidence": insert_stmt.excluded.evidence,
            "attributed_at": insert_stmt.excluded.attributed_at,
        },
        where=(insert_stmt.excluded.confidence <= ResourceOwner.confidence),
    ).returning(ResourceOwner.id)
    result = session.raw.execute(stmt)
    return result.scalar_one_or_none() is not None


# FR-025: the fallback human modifier must have made at least this many
# write events against the resource in the lookback window.
_FALLBACK_MIN_WRITE_EVENTS = 3


def _most_frequent_human_modifier(
    events: list[dict[str, Any]],
) -> tuple[int, dict[str, Any]] | None:
    """FR-024/FR-025: the human principal with the most write events, provided
    they meet the threshold -- else `None` (FR-026)."""
    counts: dict[str, int] = {}
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        principal = event.get("principal")
        if not event.get("is_human") or not principal:
            continue
        counts[principal] = counts.get(principal, 0) + 1
        if principal not in latest or event["event_time"] > latest[principal]["event_time"]:
            latest[principal] = event
    eligible = [p for p, c in counts.items() if c >= _FALLBACK_MIN_WRITE_EVENTS]
    if not eligible:
        return None
    winner = max(eligible, key=lambda p: (counts[p], p))
    return counts[winner], latest[winner]


def attribute_ownership(
    session: TenantSession,
    cloud_account_id: uuid.UUID,
    events_by_resource: dict[str, dict[str, Any]],
    write_events_by_resource: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    """FR-020-FR-026: direct-creator attribution (P1) first; for a resource
    whose creator is missing, out-of-window, or automation rather than human,
    fall back to its most frequent human modifier (P2, FR-024/FR-025) when
    `write_events_by_resource` is supplied. Neither path attributed leaves the
    resource queued unattributed (FR-022/FR-026), never a guess.

    Applies to every non-deleted resource in the account, top-level or child
    -- FR-020 carries no "top-level only" qualifier the way FR-013/FR-018 do.

    Returns the count of resources newly or re-attributed this call.
    """
    now = datetime.now(UTC)
    write_events_by_resource = write_events_by_resource or {}
    resources = (
        session.raw.execute(
            session.scoped(select(Resource), Resource).where(
                Resource.cloud_account_id == cloud_account_id,
                Resource.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    attributed = 0
    for resource in resources:
        short_id = resource.arn.rsplit("/", 1)[-1]
        event = events_by_resource.get(short_id) or events_by_resource.get(resource.arn)
        if event is not None and event.get("is_human") and event.get("principal"):
            wrote = _write_attribution(
                session,
                resource_id=resource.id,
                owner_email=event["principal"],
                confidence=OwnerConfidence.HIGH,
                evidence={
                    "kind": "direct",
                    "cloudtrail_event_id": event.get("event_id"),
                    "principal": event["principal"],
                    "event_time": _isoformat(event.get("event_time")),
                },
                attributed_at=now,
            )
            if wrote:
                attributed += 1
            continue

        write_events = write_events_by_resource.get(short_id) or write_events_by_resource.get(
            resource.arn
        )
        fallback = _most_frequent_human_modifier(write_events) if write_events else None
        if fallback is None:
            continue
        count, winner_event = fallback
        wrote = _write_attribution(
            session,
            resource_id=resource.id,
            owner_email=winner_event["principal"],
            # FR-025: lower confidence than direct attribution. MEDIUM, not
            # LOW -- a >=3-write-event signal is a reasonably confident one,
            # not a last-resort guess (the exact level was left to
            # implementation sizing by data-model.md's own resource_owner
            # section, which only requires it be lower than direct).
            confidence=OwnerConfidence.MEDIUM,
            evidence={
                "kind": "fallback",
                "cloudtrail_event_id": winner_event.get("event_id"),
                "principal": winner_event["principal"],
                "event_time": _isoformat(winner_event.get("event_time")),
                "write_event_count": count,
            },
            attributed_at=now,
        )
        if wrote:
            attributed += 1
    session.flush()
    logger.info(
        "ownership attribution complete",
        extra={"cloud_account_id": str(cloud_account_id), "resources_attributed": attributed},
    )
    return attributed


__all__ = ["attribute_ownership"]
