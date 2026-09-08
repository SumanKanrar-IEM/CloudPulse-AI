"""The insight digest: what it covers, and how it is assembled (spec 006, T013,
T015; FR-008, FR-008a, FR-008b, FR-009, FR-010, research.md R-606a, R-610).

**The platform selects; the agent explains.** Finding selection is a
deterministic query performed before the agent is invoked (FR-008a). Ranking is
a scoring decision and Principle IV reserves scoring for the deterministic core.
It is also the only version that is verifiable: the grounding validator can
confirm a finding exists, but has no way to confirm that a model-chosen finding
was genuinely the most urgent. A claim nobody can check is not a requirement.

Notability is decided here too (FR-008b), against configured thresholds rather
than by the agent. Leaving "notable" to the model would make FR-010's
nothing-notable branch unverifiable -- the validator can confirm a figure is
real, but not that omitting it was correct.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.core.logging import logger
from app.models.enums import FindingSeverity

# A digest naming forty findings answers "what should I care about today?" no
# better than the findings list it exists to summarise.
DIGEST_FINDING_LIMIT = 5

# FR-008a's first key. Declared explicitly because the enum's declaration order
# is not its urgency order, and sorting the string values would rank `low` above
# `medium` and `critical` below both.
_SEVERITY_RANK: dict[FindingSeverity, int] = {
    FindingSeverity.CRITICAL: 4,
    FindingSeverity.HIGH: 3,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 1,
}

# FR-008b, read from the environment at point of use per R-612 -- not added to
# the shared `Settings` model, which spec 005 tried and paid for in its T029a.
_SPEND_PERCENT_ENV = "CLOUDPULSE_DIGEST_SPEND_NOTABLE_PERCENT"
_SPEND_ABSOLUTE_ENV = "CLOUDPULSE_DIGEST_SPEND_NOTABLE_USD"
_COMPLIANCE_POINTS_ENV = "CLOUDPULSE_DIGEST_COMPLIANCE_NOTABLE_POINTS"

_FALLBACK_SPEND_PERCENT = Decimal("20")
_FALLBACK_SPEND_ABSOLUTE = Decimal("50")
_FALLBACK_COMPLIANCE_POINTS = Decimal("5")


@dataclass(frozen=True)
class DigestCandidate:
    """One finding eligible for the digest, reduced to what ranking needs.

    A plain value rather than an ORM row so selection stays pure and provable
    without a database -- FR-008a's reproducibility clause is the requirement,
    and a function that needed a session to demonstrate it would be a weaker
    proof.
    """

    finding_id: uuid.UUID
    severity: FindingSeverity
    escalated: bool
    opened_at: datetime
    label: str


@dataclass(frozen=True)
class NotabilityThresholds:
    """FR-008b's configured bars for "notable"."""

    spend_percent: Decimal
    spend_absolute_usd: Decimal
    compliance_points: Decimal


def select_digest_findings(
    candidates: list[DigestCandidate], *, limit: int = DIGEST_FINDING_LIMIT
) -> list[DigestCandidate]:
    """FR-008a: severity descending, then escalated first, then oldest first.

    `sorted` rather than `list.sort`: the caller may still need its own ordering,
    and sorting in place would be an invisible side effect on a shared list.
    """
    return sorted(
        candidates,
        key=lambda c: (-_SEVERITY_RANK[c.severity], not c.escalated, c.opened_at),
    )[:limit]


def _decimal_from_env(name: str, fallback: Decimal) -> Decimal:
    """R-612: a malformed or non-positive threshold falls back rather than
    raising. A bad configuration value must not take a scheduled digest run
    down, and a conservative default is a better answer than a crash."""
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.warning(
            "ignoring an unparseable digest threshold; using the fallback",
            extra={"env_var": name, "fallback": str(fallback)},
        )
        return fallback
    if value <= 0:
        logger.warning(
            "ignoring a non-positive digest threshold; using the fallback",
            extra={"env_var": name, "fallback": str(fallback)},
        )
        return fallback
    return value


def notability_thresholds() -> NotabilityThresholds:
    """FR-008b's thresholds, as configuration rather than literals."""
    return NotabilityThresholds(
        spend_percent=_decimal_from_env(_SPEND_PERCENT_ENV, _FALLBACK_SPEND_PERCENT),
        spend_absolute_usd=_decimal_from_env(_SPEND_ABSOLUTE_ENV, _FALLBACK_SPEND_ABSOLUTE),
        compliance_points=_decimal_from_env(_COMPLIANCE_POINTS_ENV, _FALLBACK_COMPLIANCE_POINTS),
    )


def is_spend_change_notable(
    previous: Decimal, current: Decimal, thresholds: NotabilityThresholds
) -> bool:
    """FR-008b: notable when the move clears **either** bar.

    Either, not both, deliberately. A percentage alone calls every jitter on a
    tiny project notable; an absolute alone stays silent on a large project
    moving a meaningful fraction of its spend. Each covers the other's blind
    spot, so the first to trigger wins.
    """
    delta = abs(current - previous)
    if delta >= thresholds.spend_absolute_usd:
        return True
    if previous <= 0:
        # No baseline to take a percentage of. A project's first spend is
        # notable only if it clears the absolute bar, which the check above
        # already decided -- treating it as an infinite percentage increase
        # would make every new project's first day notable.
        return False
    return (delta / previous) * Decimal("100") >= thresholds.spend_percent


def is_compliance_move_notable(
    previous: Decimal, current: Decimal, thresholds: NotabilityThresholds
) -> bool:
    """FR-008b: a compliance move of at least the configured points, in either
    direction. A score that improved sharply is as worth reporting as one that
    fell -- a digest that only ever delivers bad news gets read as noise."""
    return abs(current - previous) >= thresholds.compliance_points


__all__ = [
    "DIGEST_FINDING_LIMIT",
    "DigestCandidate",
    "NotabilityThresholds",
    "is_compliance_move_notable",
    "is_spend_change_notable",
    "notability_thresholds",
    "select_digest_findings",
]
