"""Utilization: how much of what a project has provisioned is actually in use
(spec 005, FR-018, T039, research.md R-509).

Makes no AWS call at all. It reads `resource.state`, which spec 002's
enrichment functions already persisted -- which is why this is the one
capability in this spec that is fully live-verifiable regardless of R-407 and
R-511's networking gap.

**Scope is stated, not silently assumed.** A resource whose `state` is NULL --
most of them, since `state` is only populated by the enrichment functions, and
`connectors/aws.py` defaults it to `None` at discovery -- is excluded from
*both* the numerator and the denominator. Counting it idle would systematically
understate utilization for every account holding resource types this platform
has never enriched; counting it used would systematically overstate it. Both
are worse than being honest about what is actually being measured, so the
result carries the counts it was computed from and the caller reports "N of M
enriched resources", never a bare percentage over the full inventory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.core.db import TenantSession
from app.models.core import Resource as ResourceRow

# R-509: data, not a per-service `if/elif` chain -- the same data-as-config
# discipline `app/scan/coverage_definitions.json` already follows.
#
# Keyed by the `service` value `connectors/aws.py` records on the resource. The
# fallback key covers every service without its own entry: the four
# EC2/RDS-shaped strings R-509 names, which is also what the enrichment
# functions actually emit for those types.
_IDLE_STATES: dict[str, frozenset[str]] = {
    # An unattached EBS volume reads as "available", which is the opposite of
    # what the word suggests everywhere else in this table: it means nothing is
    # using it, while "in-use" means something is. Called out because reading
    # this row as "available = healthy" is the obvious mistake, and it would
    # count every orphaned volume -- exactly the waste this feature exists to
    # surface -- as utilized.
    "ec2-volume": frozenset({"available", "creating", "deleting", "error"}),
    "elasticloadbalancing": frozenset({"failed"}),
}
_DEFAULT_IDLE_STATES = frozenset({"stopped", "stopping", "terminated", "deleting", "shutting-down"})

# EBS volumes arrive with `service = "ec2"` like instances do, so they are told
# apart by resource type rather than by service.
_VOLUME_RESOURCE_TYPE = "AWS::EC2::Volume"


@dataclass(frozen=True)
class Utilization:
    """A utilization figure and the scope it was computed over.

    `used` and `provisioned` travel with the ratio deliberately: FR-018's
    number means nothing without the population it was measured against, and
    R-509 requires the dashboard to state that scope rather than imply a claim
    over the whole inventory.
    """

    used: int
    provisioned: int

    @property
    def has_enough_data(self) -> bool:
        return self.provisioned > 0

    @property
    def percent(self) -> float | None:
        """`None`, never 0.0 or 100.0, when nothing is measurable.

        An account with no enriched resources has no utilization -- reporting
        either extreme would be a claim this data cannot support, and a
        divide-by-zero would be an outage where an honest "not enough data"
        belongs.
        """
        if not self.has_enough_data:
            return None
        return round(self.used * 100 / self.provisioned, 1)


def is_idle(service: str | None, resource_type: str | None, state: str) -> bool:
    """R-509's classification, as a lookup rather than a branch chain."""
    if resource_type == _VOLUME_RESOURCE_TYPE:
        return state.lower() in _IDLE_STATES["ec2-volume"]
    idle = _IDLE_STATES.get((service or "").lower(), _DEFAULT_IDLE_STATES)
    return state.lower() in idle


def classify(rows: list[tuple[str | None, str | None, str | None]]) -> Utilization:
    """Count `(service, resource_type, state)` triples into used/provisioned.

    Pure, so R-509's whole classification is unit-testable without a database
    -- and so the NULL-exclusion rule is provable rather than asserted.
    """
    used = 0
    provisioned = 0
    for service, resource_type, state in rows:
        if state is None:
            continue  # never enriched: no evidence either way
        provisioned += 1
        if not is_idle(service, resource_type, state):
            used += 1
    return Utilization(used=used, provisioned=provisioned)


def compute_utilization(
    session: TenantSession,
    *,
    account_id: uuid.UUID | None = None,
    sda_id: uuid.UUID | None = None,
) -> Utilization:
    """FR-018, computed live (R-509: no precomputation, no worker, no schedule).

    Soft-deleted resources are excluded: spec 002 marks `deleted_at` rather
    than removing the row, and counting a deleted resource as provisioned would
    keep dragging utilization down for something that no longer exists.
    """
    statement = session.scoped(
        select(ResourceRow.service, ResourceRow.resource_type, ResourceRow.state), ResourceRow
    ).where(ResourceRow.deleted_at.is_(None))
    if account_id is not None:
        statement = statement.where(ResourceRow.cloud_account_id == account_id)
    if sda_id is not None:
        statement = statement.where(ResourceRow.sda_id == sda_id)
    rows = session.raw.execute(statement).all()
    return classify([(service, resource_type, state) for service, resource_type, state in rows])


def utilization_by_account(session: TenantSession) -> dict[uuid.UUID, Utilization]:
    """One row per account, in a single query rather than one per account."""
    return _grouped(session, ResourceRow.cloud_account_id)


def utilization_by_sda(
    session: TenantSession, *, account_id: uuid.UUID | None = None
) -> dict[uuid.UUID | None, Utilization]:
    """One row per project, with `None` keying the "No SDA" bucket -- the same
    bucket spend and inventory already use for unattributed resources."""
    return _grouped(session, ResourceRow.sda_id, account_id=account_id)


def _grouped(
    session: TenantSession, key_column: Any, *, account_id: uuid.UUID | None = None
) -> dict[Any, Utilization]:
    statement = (
        session.scoped(
            select(
                key_column,
                ResourceRow.service,
                ResourceRow.resource_type,
                ResourceRow.state,
                func.count(),
            ),
            ResourceRow,
        )
        .where(ResourceRow.deleted_at.is_(None))
        .group_by(key_column, ResourceRow.service, ResourceRow.resource_type, ResourceRow.state)
    )
    if account_id is not None:
        statement = statement.where(ResourceRow.cloud_account_id == account_id)
    rows = session.raw.execute(statement).all()

    buckets: dict[Any, list[tuple[str | None, str | None, str | None]]] = {}
    for key, service, resource_type, state, count in rows:
        buckets.setdefault(key, []).extend([(service, resource_type, state)] * count)
    return {key: classify(triples) for key, triples in buckets.items()}


__all__ = [
    "Utilization",
    "classify",
    "compute_utilization",
    "is_idle",
    "utilization_by_account",
    "utilization_by_sda",
]
