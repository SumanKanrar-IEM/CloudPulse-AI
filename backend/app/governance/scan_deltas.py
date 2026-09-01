"""A scan's resulting resource deltas (FR-021, research.md R-405).

Computed at query time from `resource.first_seen_at`/`last_seen_at`/`deleted_at`
against the scan's `[started_at, finished_at]` window -- no new persisted state,
matching this project's established preference for computing a value fresh from
source-of-truth data over persisting a derived one (Principle IV).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select

from app.core.db import TenantSession
from app.models.core import Resource


class ResourceTimestamps(NamedTuple):
    first_seen_at: datetime
    last_seen_at: datetime
    deleted_at: datetime | None


class ScanDeltas(NamedTuple):
    added: int
    removed: int
    changed: int


def compute_scan_deltas(
    resources: list[ResourceTimestamps], window_start: datetime, window_end: datetime
) -> ScanDeltas:
    """R-405's three counts, in isolation from any query.

    `changed` requires `first_seen_at` to predate `window_start` -- an existing
    resource this scan touched again, not one it just discovered (which would
    otherwise double-count into both `added` and `changed`).
    """
    added = sum(1 for r in resources if window_start <= r.first_seen_at <= window_end)
    removed = sum(
        1
        for r in resources
        if r.deleted_at is not None and window_start <= r.deleted_at <= window_end
    )
    changed = sum(
        1
        for r in resources
        if window_start <= r.last_seen_at <= window_end and r.first_seen_at < window_start
    )
    return ScanDeltas(added=added, removed=removed, changed=changed)


def scan_deltas(
    session: TenantSession,
    cloud_account_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> ScanDeltas:
    stmt = session.scoped(
        select(Resource.first_seen_at, Resource.last_seen_at, Resource.deleted_at), Resource
    ).where(Resource.cloud_account_id == cloud_account_id)
    rows = session.raw.execute(stmt).all()
    resources = [ResourceTimestamps(*row) for row in rows]
    return compute_scan_deltas(resources, window_start, window_end)


__all__ = ["ResourceTimestamps", "ScanDeltas", "compute_scan_deltas", "scan_deltas"]
