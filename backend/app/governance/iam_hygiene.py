"""Flag-only IAM hygiene: which roles, users, and keys appear unused
(spec 005, FR-019, FR-020, T045).

**Flag-only is the requirement, not a current limitation.** FR-019 forbids
automatic deletion or deactivation outright, so nothing in this module writes
to IAM at all -- it only records `IamHygieneFlag` rows. That is also why a flag
is deliberately not a `Finding`: a Finding would carry it into the
acknowledge/notify/escalate pipeline, which is exactly the automated pressure
FR-019 says this must not apply.

**FR-020 is the constraint that shapes everything here.** A principal used
recently must never be flagged, so every rule below fails toward *not*
flagging: unknown last-used data flags only when the principal is old enough
that "we have never seen it used" is itself evidence, and any principal whose
evidence cannot be interpreted is left alone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.db import TenantSession
from app.models.core import IamHygieneFlag as FlagRow
from app.models.enums import IamPrincipalType

# FR-019's "appears unused". Ninety days matches spec 003's own CloudTrail
# lookback (FR-020 there), so "unused" means the same span of quiet across both
# features rather than two different definitions a reader has to hold at once.
UNUSED_AFTER = timedelta(days=90)

# A principal younger than this is never flagged, however little evidence there
# is: a role created last week with no recorded use is new, not abandoned, and
# flagging it would be exactly the false positive FR-020 forbids.
MIN_AGE_BEFORE_FLAGGING = timedelta(days=90)


@dataclass(frozen=True)
class Candidate:
    """One principal's raw evidence, as `connectors.aws.iam_unused_analysis`
    returns it -- no AWS types cross this boundary (Principle V)."""

    principal_type: str
    identifier: str
    name: str
    created_at: datetime | None
    last_used_at: datetime | None
    reason: str | None = None
    status: str | None = None


def is_unused(candidate: Candidate, *, now: datetime | None = None) -> bool:
    """FR-019/FR-020's judgement, as a pure function.

    Three cases, all failing toward not flagging:

    * Used within the window -> never flagged. This is FR-020 restated, and it
      is checked first so no later rule can override it.
    * Used, but longer ago than the window -> flagged.
    * Never used -> flagged only once the principal is older than
      `MIN_AGE_BEFORE_FLAGGING`. A principal with no creation date at all is
      not flagged, because the age test cannot be applied and guessing would
      risk the false positive FR-020 forbids.
    """
    now = now or datetime.now(UTC)

    if candidate.last_used_at is not None:
        return _aware(candidate.last_used_at) < now - UNUSED_AFTER

    if candidate.created_at is None:
        return False
    return _aware(candidate.created_at) < now - MIN_AGE_BEFORE_FLAGGING


def _aware(value: datetime) -> datetime:
    """boto3 returns tz-aware datetimes, but a fixture or a replayed payload may
    not. Comparing a naive datetime against an aware one raises, which would
    turn one odd record into a failed run for the whole account."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def evidence_for(candidate: Candidate, *, now: datetime | None = None) -> dict[str, Any]:
    """Why we believe this principal is unused.

    Recorded with the flag for the same reason spec 003 records attribution
    evidence: a recommendation without its basis is a guess presented as a
    fact, and this one is asking a human to delete something.
    """
    now = now or datetime.now(UTC)
    last_used = candidate.last_used_at
    return {
        "name": candidate.name,
        "lastUsedAt": _aware(last_used).isoformat() if last_used else None,
        "createdAt": _aware(candidate.created_at).isoformat() if candidate.created_at else None,
        "daysSinceLastUse": (now - _aware(last_used)).days if last_used else None,
        "unusedAfterDays": UNUSED_AFTER.days,
        "reason": candidate.reason,
        "status": candidate.status,
    }


def reconcile_flags(
    session: TenantSession,
    cloud_account_id: uuid.UUID,
    candidates: list[Candidate],
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Flag what is unused, clear what no longer is. Returns `(flagged, cleared)`.

    Clearing is driven by *this run's* candidate list, which is why
    `iam_unused_analysis` raises rather than returning partial results: a
    truncated list would look like "these principals are gone" and clear flags
    that should have stood.

    A principal that becomes unused again after being cleared gets a **new**
    row with a fresh `flagged_at`, never a revived old one -- the partial
    unique index (`WHERE cleared_at IS NULL`) allows exactly one active flag
    per principal while keeping the earlier, cleared row as history.
    """
    now = now or datetime.now(UTC)
    active = {
        flag.principal_identifier: flag
        for flag in session.raw.execute(
            session.scoped(select(FlagRow), FlagRow).where(
                FlagRow.cloud_account_id == cloud_account_id,
                FlagRow.cleared_at.is_(None),
            )
        )
        .scalars()
        .all()
    }

    flagged = 0
    seen: set[str] = set()
    for candidate in candidates:
        seen.add(candidate.identifier)
        if not is_unused(candidate, now=now):
            continue
        if candidate.identifier in active:
            continue  # already flagged; not re-flagged, so flagged_at stands
        session.add(
            FlagRow(
                cloud_account_id=cloud_account_id,
                principal_type=IamPrincipalType(candidate.principal_type),
                principal_identifier=candidate.identifier,
                evidence=evidence_for(candidate, now=now),
                flagged_at=now,
            )
        )
        flagged += 1

    cleared = 0
    for identifier, flag in active.items():
        still_unused = any(c.identifier == identifier and is_unused(c, now=now) for c in candidates)
        # A principal absent from this run's list is cleared too: it no longer
        # exists, so a standing "this is unused, delete it" recommendation
        # would point at nothing.
        if identifier not in seen or not still_unused:
            flag.cleared_at = now
            cleared += 1

    session.raw.flush()
    return flagged, cleared


__all__ = [
    "MIN_AGE_BEFORE_FLAGGING",
    "UNUSED_AFTER",
    "Candidate",
    "evidence_for",
    "is_unused",
    "reconcile_flags",
]
