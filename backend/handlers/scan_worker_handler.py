"""Lambda entrypoint Step Functions invokes per unit of work (FR-023, spec 002).

One function handles three actions, selected by the event's `action` field, rather
than three separate Lambdas -- keeps the Terraform footprint to the single function
research.md R-207's cost table anticipated:

- ``scan_unit`` (default): discover + enrich + persist one scan region.
- ``finalize_scan``: aggregate the Map state's per-region outcomes into
  `scan.status` and the deleted-marker sweep (`app/scan/orchestrator.finalize_scan`).
- ``trigger_daily``: the EventBridge Scheduler's daily target (FR-026) -- starts a
  scan for every verified account.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import tenant_session
from app.core.logging import logger
from app.models.core import CloudAccount, Scan
from app.models.enums import ConnectionMode
from app.scan import discovery, enrichment, orchestrator
from connectors.aws import AwsConnector, read_external_id
from connectors.base import NormalizedResource


def _snapshot_bucket() -> str:
    import os

    bucket = os.environ.get("CLOUDPULSE_SNAPSHOT_BUCKET")
    if not bucket:
        raise RuntimeError("CLOUDPULSE_SNAPSHOT_BUCKET is not set")
    return bucket


def _write_raw_snapshot(scan_id: str, region: str, resources: list[NormalizedResource]) -> str:
    """FR-028: an immutable, unmodified record of this unit's discovery result,
    separate from the current-state view `orchestrator.persist_unit_result` writes.
    One object per (scan, region) rather than one per scan, so a unit's snapshot
    never needs the full scan's data held in memory at once (Edge Cases: a very
    large account)."""
    import boto3

    key = f"scans/{scan_id}/{region}.json"
    body = json.dumps(
        [
            {
                "provider": r.provider,
                "account_id": r.account_id,
                "resource_id": r.resource_id,
                "service": r.service,
                "resource_type": r.resource_type,
                "region": r.region,
                "name": r.name,
                "tags": r.tags,
                "state": r.state,
                "created_at": str(r.created_at) if r.created_at else None,
                "detail": r.detail,
            }
            for r in resources
        ]
    )
    boto3.client("s3").put_object(Bucket=_snapshot_bucket(), Key=key, Body=body.encode("utf-8"))
    return key


def _handle_scan_unit(event: dict[str, Any]) -> dict[str, Any]:
    scan_id = event["scan_id"]
    tenant_id = uuid.UUID(event["tenant_id"])
    cloud_account_id = uuid.UUID(event["cloud_account_id"])
    region = event["region"]

    with tenant_session(tenant_id) as session:
        account = session.raw.execute(
            session.scoped(select(CloudAccount), CloudAccount).where(
                CloudAccount.id == cloud_account_id
            )
        ).scalar_one()

        external_id: str | None = None
        if account.connection_mode is ConnectionMode.ASSUME_ROLE and account.external_id_ref:
            # Resolved fresh for this unit of work (research.md R-206), held only in
            # memory, never logged (Principle III).
            external_id = read_external_id(account.external_id_ref)

        connector = AwsConnector()
        resources = discovery.discover_account_region(
            aws_account_id=account.aws_account_id,
            connection_mode=account.connection_mode.value,
            role_arn=account.role_arn,
            external_id=external_id,
            region=region,
            connector=connector,
        )
        enriched = enrichment.enrich_resources(resources, connector=connector)
        _write_raw_snapshot(scan_id, region, enriched)
        orchestrator.persist_unit_result(
            session, cloud_account_id=cloud_account_id, resources=enriched
        )

    logger.info(
        "scan unit completed",
        extra={"scan_id": scan_id, "region": region, "resource_count": len(enriched)},
    )
    return {"status": "succeeded", "region": region}


def _normalize_unit_result(raw: dict[str, Any]) -> dict[str, str]:
    """Both the Task's own successful output and the Catch path's `UnitFailed` Pass
    output already carry this shape -- normalised defensively rather than trusted,
    since a malformed state-machine definition should degrade to "failed", not
    crash the finalize step."""
    return {"status": str(raw.get("status", "failed")), "region": str(raw.get("region", "unknown"))}


def _handle_finalize_scan(event: dict[str, Any]) -> dict[str, Any]:
    scan_id = uuid.UUID(event["scan_id"])
    tenant_id = uuid.UUID(event["tenant_id"])
    unit_results = [_normalize_unit_result(r) for r in event.get("unitResults", [])]

    with tenant_session(tenant_id) as session:
        scan = session.raw.execute(
            session.scoped(select(Scan), Scan).where(Scan.id == scan_id)
        ).scalar_one()
        final_status = orchestrator.finalize_scan(session, scan, unit_results)

    return {"scan_id": str(scan_id), "status": final_status.value}


def _handle_trigger_daily(_event: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import text

    from app.core.db import get_engine

    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )
    with tenant_session(tenant_id) as session:
        started = orchestrator.start_due_daily_scans(session)
    return {"started": started}


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "scan_unit")
    if action == "finalize_scan":
        return _handle_finalize_scan(event)
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    return _handle_scan_unit(event)


__all__ = ["handler"]
