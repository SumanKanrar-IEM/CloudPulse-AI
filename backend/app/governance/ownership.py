"""Direct-creator ownership attribution (FR-020-FR-023, research.md R-302).

Correlates `connectors.aws.sweep_cloudtrail_events`'s in-memory event map
against the scan's persisted resource set -- one guarded write per resource,
so a later, lower-confidence result never overwrites an existing
higher-confidence attribution (FR-023).
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


def attribute_ownership(
    session: TenantSession,
    cloud_account_id: uuid.UUID,
    events_by_resource: dict[str, dict[str, Any]],
) -> int:
    """FR-020-FR-023: direct-creator attribution only (P1) -- a resource whose
    creation event falls outside the sweep's window, isn't in the map at all,
    or whose principal isn't human, stays queued unattributed (FR-022); P2's
    fallback chain (FR-024) is what picks up from there, in a later phase.

    Applies to every non-deleted resource in the account, top-level or child
    -- FR-020 carries no "top-level only" qualifier the way FR-013/FR-018 do.

    Returns the count of resources newly or re-attributed this call.
    """
    now = datetime.now(UTC)
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
        if event is None or not event.get("is_human") or not event.get("principal"):
            continue
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
    session.flush()
    logger.info(
        "ownership attribution complete",
        extra={"cloud_account_id": str(cloud_account_id), "resources_attributed": attributed},
    )
    return attributed


__all__ = ["attribute_ownership"]
