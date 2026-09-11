"""Utilization metrics: collect, normalise, persist (spec 006, T040; FR-019,
FR-020, S50).

Spec 005's `utilization.py` answers "how much is in use right now" from
`resource.state`. This module gives that a history: one measurement per
resource, per metric, per day, from CloudWatch -- the input forecasting and
rightsizing need.

**Which metrics, as data.** `METRIC_QUERIES` maps a resource type to the
CloudWatch queries that measure it, the same data-as-config discipline
`utilization._IDLE_STATES` and `scan/coverage_definitions.json` follow. Adding a
resource type is a new entry, not a new branch.

**Every (resource, metric) pair gets a row, present or not.** A resource this
platform asks CloudWatch about and hears nothing back is recorded as
`is_unavailable`, never as zero (FR-020). That covers two different silences,
and both are honest as "unknown": a metric CloudWatch genuinely has no
datapoint for over the period, and a metric the platform does not query at all
-- EC2 memory, which needs the CloudWatch agent the platform cannot assume is
installed. A missing row would let a consumer average over the rows that exist
and call that the utilization; an unavailable row says what was not measured.

**No AWS call here.** `connectors/aws.py::get_metric_data` is the only place
`GetMetricData` appears (Principle V). This module builds the queries and reads
the results as plain dicts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import Resource as ResourceRow
from app.models.core import ResourceMetric as MetricRow
from app.models.enums import ResourceMetricKind

# One day per period. Daily is what spend ingestion already uses and what a
# 30-day retention window (FR-006a) can hold as a forecast history.
PERIOD = timedelta(days=1)

# GetMetricData accepts at most this many queries per call.
MAX_QUERIES_PER_CALL = 500

# `value` is NUMERIC(12,4); anything past that is precision CloudWatch does not
# actually have.
_VALUE_PRECISION = Decimal("0.0001")


# `value` is NUMERIC(12,4): eight integer digits. CloudWatch reports memory,
# storage and network in bytes, and 100 GB of free storage is 1e11 -- three
# digits past what the column holds. Each query therefore declares the unit it
# is stored in, and the scale that gets it there.
_BYTES_PER_GB = Decimal(1_000_000_000)
_BYTES_PER_MB = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class MetricQuery:
    kind: ResourceMetricKind
    namespace: str
    metric_name: str
    dimension_name: str
    stat: str = "Average"
    unit: str = "percent"
    scale: Decimal = Decimal(1)  # stored value = reported value * scale


# Keyed by `resource.resource_type`. The dimension value is the ARN's last
# segment for every type here -- `i-0abc` for an instance, the identifier for an
# RDS instance -- which is why `_dimension_value` has no per-type branch.
METRIC_QUERIES: dict[str, tuple[MetricQuery, ...]] = {
    "AWS::EC2::Instance": (
        MetricQuery(ResourceMetricKind.CPU, "AWS/EC2", "CPUUtilization", "InstanceId"),
        MetricQuery(
            ResourceMetricKind.NETWORK,
            "AWS/EC2",
            "NetworkIn",
            "InstanceId",
            unit="MB per datapoint",
            scale=1 / _BYTES_PER_MB,
        ),
        # No memory query: AWS/EC2 does not publish it. Left absent on purpose so
        # normalise() records it as unavailable rather than this table lying
        # about a metric that needs an agent.
    ),
    "AWS::RDS::DBInstance": (
        MetricQuery(ResourceMetricKind.CPU, "AWS/RDS", "CPUUtilization", "DBInstanceIdentifier"),
        MetricQuery(
            ResourceMetricKind.MEMORY,
            "AWS/RDS",
            "FreeableMemory",
            "DBInstanceIdentifier",
            unit="GB free",
            scale=1 / _BYTES_PER_GB,
        ),
        MetricQuery(
            ResourceMetricKind.STORAGE,
            "AWS/RDS",
            "FreeStorageSpace",
            "DBInstanceIdentifier",
            unit="GB free",
            scale=1 / _BYTES_PER_GB,
        ),
        MetricQuery(
            ResourceMetricKind.NETWORK,
            "AWS/RDS",
            "NetworkReceiveThroughput",
            "DBInstanceIdentifier",
            unit="MB per second",
            scale=1 / _BYTES_PER_MB,
        ),
    ),
}


def query_for(resource_type: str, kind: ResourceMetricKind) -> MetricQuery | None:
    return next((q for q in METRIC_QUERIES.get(resource_type, ()) if q.kind is kind), None)


# Every kind, so normalise() can emit the unavailable rows for the ones a type
# has no query for.
ALL_KINDS: tuple[ResourceMetricKind, ...] = tuple(ResourceMetricKind)


@dataclass(frozen=True, slots=True)
class MeteredResource:
    """The two things a query needs from a resource, and nothing else."""

    resource_id: uuid.UUID
    resource_type: str
    arn: str
    region: str


@dataclass(frozen=True, slots=True)
class Measurement:
    resource_id: uuid.UUID
    metric: ResourceMetricKind
    period_start: datetime
    value: Decimal | None  # None means unavailable (FR-020)


def period_start_for(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def yesterday_utc() -> date:
    """The period to collect: the last complete day. Same choice spend
    ingestion makes, and for the same reason -- today's average is not yet an
    average of anything."""
    return datetime.now(UTC).date() - timedelta(days=1)


def _dimension_value(arn: str) -> str:
    return arn.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def query_id(index: int, kind: ResourceMetricKind) -> str:
    """GetMetricData ids must match ^[a-z][a-zA-Z0-9_]*$; a UUID does not."""
    return f"m{index}_{kind.value}"


def build_queries(resources: list[MeteredResource]) -> list[dict[str, Any]]:
    """The `MetricDataQueries` list for one GetMetricData call.

    A resource whose type has no entry contributes nothing -- the caller should
    not have sent it, and `metered_resources` does not.
    """
    queries: list[dict[str, Any]] = []
    for index, resource in enumerate(resources):
        for query in METRIC_QUERIES.get(resource.resource_type, ()):
            queries.append(
                {
                    "Id": query_id(index, query.kind),
                    "MetricStat": {
                        "Metric": {
                            "Namespace": query.namespace,
                            "MetricName": query.metric_name,
                            "Dimensions": [
                                {
                                    "Name": query.dimension_name,
                                    "Value": _dimension_value(resource.arn),
                                }
                            ],
                        },
                        "Period": int(PERIOD.total_seconds()),
                        "Stat": query.stat,
                    },
                    "ReturnData": True,
                }
            )
    return queries


def normalise(
    resources: list[MeteredResource],
    results: list[dict[str, Any]],
    *,
    period_start: datetime,
) -> list[Measurement]:
    """One `Measurement` per resource per kind -- all four kinds, every time.

    `results` is GetMetricData's `MetricDataResults` as plain dicts. A result
    with no `Values` is a metric CloudWatch had nothing for; a kind with no
    result at all is one the platform never asked about. Both become
    `value=None`, and FR-020 is the reason neither becomes zero.
    """
    by_id: dict[str, list[Any]] = {
        str(r.get("Id", "")): list(r.get("Values") or []) for r in results
    }
    measurements: list[Measurement] = []
    for index, resource in enumerate(resources):
        for kind in ALL_KINDS:
            values = by_id.get(query_id(index, kind), [])
            query = query_for(resource.resource_type, kind)
            value = (
                (Decimal(str(values[0])) * query.scale).quantize(_VALUE_PRECISION)
                if values and query is not None
                else None
            )
            measurements.append(
                Measurement(
                    resource_id=resource.resource_id,
                    metric=kind,
                    period_start=period_start,
                    value=value,
                )
            )
    return measurements


def metered_resources(
    session: TenantSession, *, cloud_account_id: uuid.UUID
) -> list[MeteredResource]:
    """Live resources in one account whose type this module knows how to measure."""
    statement = (
        session.scoped(
            select(ResourceRow.id, ResourceRow.resource_type, ResourceRow.arn, ResourceRow.region),
            ResourceRow,
        )
        .where(ResourceRow.cloud_account_id == cloud_account_id)
        .where(ResourceRow.deleted_at.is_(None))
        .where(ResourceRow.resource_type.in_(list(METRIC_QUERIES)))
        .order_by(ResourceRow.arn)
    )
    return [
        MeteredResource(resource_id=rid, resource_type=rtype, arn=arn, region=region)
        for rid, rtype, arn, region in session.raw.execute(statement)
    ]


def persist_measurements(session: TenantSession, measurements: list[Measurement]) -> int:
    """Write measurements without duplicating or overwriting a collected period
    (FR-019).

    The unique constraint on (tenant, resource, metric, period) refuses a
    duplicate. On conflict the existing row stands -- with one exception: a row
    recorded as unavailable is replaced when a later run has a value. CloudWatch
    publishes with a lag, so the first collection after midnight can honestly
    find nothing and a run a day later honestly find the number. Keeping the
    earlier "unknown" over a later measurement would make the lag permanent;
    replacing a measurement with a different measurement would make the store
    disagree with itself. Neither is what FR-019 wants, so the update is
    conditional on the stored row being the unknown one.

    Returns the number of rows inserted or upgraded from unavailable.
    """
    if not measurements:
        return 0
    rows = [
        {
            "tenant_id": session.tenant_id,
            "resource_id": m.resource_id,
            "metric": m.metric,
            "period_start": m.period_start,
            "value": m.value,
            "is_unavailable": m.value is None,
        }
        for m in measurements
    ]
    statement = insert(MetricRow).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_resource_metric_tenant_resource_metric_period",
        set_={
            "value": statement.excluded.value,
            "is_unavailable": statement.excluded.is_unavailable,
            "collected_at": datetime.now(UTC),
        },
        where=(MetricRow.is_unavailable.is_(True)) & (statement.excluded.is_unavailable.is_(False)),
    )
    # RETURNING rather than rowcount: a multi-row VALUES insert reports -1
    # through psycopg, and a conflict row whose WHERE did not match is not
    # returned, so this counts exactly what changed.
    written = len(session.raw.execute(statement.returning(MetricRow.id)).all())
    logger.info(
        "resource metrics persisted",
        extra={
            "tenant_id": str(session.tenant_id),
            "offered": len(measurements),
            "written": written,
            "unavailable": sum(1 for m in measurements if m.value is None),
        },
    )
    return written


__all__ = [
    "ALL_KINDS",
    "MAX_QUERIES_PER_CALL",
    "METRIC_QUERIES",
    "PERIOD",
    "Measurement",
    "MeteredResource",
    "MetricQuery",
    "build_queries",
    "metered_resources",
    "normalise",
    "period_start_for",
    "persist_measurements",
    "query_for",
    "query_id",
    "yesterday_utc",
]
