"""Lambda entrypoint EventBridge Scheduler invokes daily to collect utilization
metrics (spec 006, T042; FR-019, FR-020, S50).

This module owns the AWS wiring -- the account session and the CloudWatch call
-- and `app.governance.metrics` owns what is asked and what is stored, the same
boundary `cost_ingestion_worker_handler.py` keeps (Principle V, FR-054).

**Per account, per region, isolated.** One account's failure -- an expired
role, a region the account never enabled, a throttle -- is logged and the loop
continues. The measurements for the accounts that succeeded are already in the
store by the time a later one fails, which is FR-019's "per resource and
period" delivered as far as it can be on a bad day rather than not at all.

**A failed account is not written as unavailable.** FR-020's "unknown" is for a
resource CloudWatch was asked about and had nothing for. An account the
platform could not ask at all is a collection failure, and writing thirty
unavailable rows for it would make the next run's upgrade path the only thing
standing between that failure and a permanent hole. Leaving the period absent
lets the next run collect it cleanly.

**Runtime limitation, stated plainly**: this worker is VPC-attached and, like
the cost worker, cannot reach CloudWatch from inside the VPC until R-407's
endpoint gap is funded (research.md R-605). Until then every account fails
identically, which the per-account isolation above turns into a logged run
with nothing written -- not a crash, and not a store full of zeros.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.db import get_engine, tenant_session
from app.core.logging import logger
from app.governance import spend
from app.governance.metrics import (
    PERIOD,
    MeteredResource,
    build_queries,
    metered_resources,
    normalise,
    period_start_for,
    persist_measurements,
    yesterday_utc,
)
from app.models.core import CloudAccount
from app.models.enums import ConnectionMode
from connectors.aws import get_metric_data, read_external_id
from connectors.base import ConnectorAccount


def _connector_account(account: CloudAccount) -> ConnectorAccount:
    external_id: str | None = None
    if account.connection_mode is ConnectionMode.ASSUME_ROLE and account.external_id_ref:
        # Resolved for this call, held only in memory, never logged (Principle III).
        external_id = read_external_id(account.external_id_ref)
    return ConnectorAccount(
        aws_account_id=account.aws_account_id,
        connection_mode=account.connection_mode.value,
        role_arn=account.role_arn,
        external_id=external_id,
    )


def _collect_account(session: Any, account: CloudAccount, *, day: date) -> tuple[int, int]:
    """One account, every region it is scanned in. Returns (offered, written).

    Resources are selected once per account and queried per region, because a
    resource lives in exactly one region and CloudWatch is regional -- asking
    us-west-2 about an instance in us-east-1 returns nothing, which would be
    recorded as unavailable and then be true for the wrong reason. Grouped by
    the resource's own `region` column rather than the account's scan list: a
    resource discovered in a region since removed from the list is still a
    resource, and its metrics are still in that region.
    """
    period_start = period_start_for(day)
    connector_account = _connector_account(account)
    offered = written = 0

    by_region: dict[str, list[MeteredResource]] = {}
    for resource in metered_resources(session, cloud_account_id=account.id):
        by_region.setdefault(resource.region, []).append(resource)
    for region, in_region in by_region.items():
        results = get_metric_data(
            connector_account,
            region,
            build_queries(in_region),
            start=period_start,
            end=period_start + PERIOD,
        )
        measurements = normalise(in_region, results, period_start=period_start)
        offered += len(measurements)
        written += persist_measurements(session, measurements)
    return offered, written


def _handle_trigger_daily(_event: dict[str, Any]) -> dict[str, Any]:
    day = yesterday_utc()

    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )

    collected: list[str] = []
    failed: list[str] = []
    total_written = 0
    with tenant_session(tenant_id) as session:
        for account in spend.due_accounts(session):
            try:
                _, written = _collect_account(session, account, day=day)
                total_written += written
                collected.append(str(account.id))
            except Exception:
                # One account's failure must not block another's. Logged, not
                # raised, and nothing written for it -- see the module docstring.
                logger.exception(
                    "metrics collection failed for account",
                    extra={"cloud_account_id": str(account.id)},
                )
                failed.append(str(account.id))

    result = {
        "period_date": day.isoformat(),
        "collected": collected,
        "failed": failed,
        "written": total_written,
    }
    logger.info("metrics collector completed", extra=result)
    return result


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_daily")
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["handler"]
