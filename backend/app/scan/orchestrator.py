"""Scan orchestration: starting executions, diffing, status transitions (FR-023,
FR-026, FR-027, FR-029-FR-032, research.md R-204, R-211).

Allowlisted in `ops/scripts/check_connector_boundary.py` for one boto3 call:
starting an execution of the platform's OWN Step Functions state machine -- not a
call into any scanned account, the same class of exception as
`app/core/db.py`'s Secrets Manager fetch for the platform's own DB credential.

**Unit-of-work granularity, a deliberate simplification from research.md R-211's
illustrative "account x region x service group"**: this spec's `Connector` protocol
(`connectors/base.py`, Phase 2, already merged) defines `discover(account, region)`
with no service-group parameter, and Phase 5's `AwsConnector.discover()` sweeps a
whole region in one call. Splitting further would mean either reworking the merged
Phase 2/5 connector interface, or re-filtering one full region sweep's results
client-side per service group -- which would not actually shrink the unit of work's
blast radius or retry cost, since the retry would just redo the same full sweep. This
spec's unit of work is therefore **one scan region** -- still independent,
still bounded-retry (FR-024), still isolated per FR-023's actual intent (a failing
region does not take down others), just coarser than R-211's example grain. Flagged
here rather than silently narrowed to match the letter of a research note that
predates the interface it would require reopening.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import CloudAccount, Resource, Scan
from app.models.enums import AccountStatus, ScanStatus, ScanTrigger
from connectors.base import NormalizedResource


class ScanAlreadyRunningError(Exception):
    """FR-027: two scans of the same account must not run concurrently."""

    def __init__(self, running_scan_id: str) -> None:
        self.running_scan_id = running_scan_id
        super().__init__(f"scan {running_scan_id} is already running for this account")


# --- Starting a scan ---------------------------------------------------------------


def start_scan(session: TenantSession, account: CloudAccount, *, trigger: ScanTrigger) -> Scan:
    """Create the `scan` row and start the Step Functions execution.

    Raises `ScanAlreadyRunningError` rather than starting a second concurrent scan of
    the same account (FR-027) -- checked here, inside the same transaction that then
    creates the new row, so two near-simultaneous callers cannot both pass the check.
    """
    existing_running = session.raw.execute(
        session.scoped(select(Scan), Scan).where(
            Scan.cloud_account_id == account.id, Scan.status == ScanStatus.RUNNING
        )
    ).scalar_one_or_none()
    if existing_running is not None:
        raise ScanAlreadyRunningError(str(existing_running.id))

    scan = Scan(
        cloud_account_id=account.id,
        trigger=trigger,
        status=ScanStatus.RUNNING,
        resource_count=0,
    )
    session.add(scan)
    session.flush()

    execution_input = _build_execution_input(scan, account)
    _start_step_functions_execution(execution_input)
    logger.info(
        "scan started",
        extra={
            "scan_id": str(scan.id),
            "cloud_account_id": str(account.id),
            "trigger": trigger.value,
        },
    )
    return scan


def _build_execution_input(scan: Scan, account: CloudAccount) -> dict[str, Any]:
    """One unit of work per scan region (research.md R-211, see module docstring)."""
    return {
        "scan_id": str(scan.id),
        "tenant_id": str(scan.tenant_id),
        "cloud_account_id": str(account.id),
        "units": [{"region": region} for region in account.scan_regions],
    }


def _step_functions_state_machine_arn() -> str:
    import os

    arn = os.environ.get("CLOUDPULSE_SCAN_STATE_MACHINE_ARN")
    if not arn:
        raise RuntimeError("CLOUDPULSE_SCAN_STATE_MACHINE_ARN is not set")
    return arn


def _start_step_functions_execution(execution_input: dict[str, Any]) -> str:
    import boto3

    client = boto3.client("stepfunctions")
    response = client.start_execution(
        stateMachineArn=_step_functions_state_machine_arn(),
        name=f"scan-{execution_input['scan_id']}",
        input=json.dumps(execution_input),
    )
    return str(response["executionArn"])


# --- Governance pipeline enqueue (spec 003, T026, research.md R-303) -----------
#
# `finalize_scan` enqueues one message per finalized scan to each of two new SQS
# queues -- not a second orchestration mechanism, an event-driven consumer of this
# scan lifecycle's own completion event, the same relationship the state machine
# above already has to the scan-worker Lambda (research.md R-303).

_GOVERNANCE_QUEUE_ENV_VARS = (
    "CLOUDPULSE_COMPLIANCE_VALIDATION_QUEUE_URL",
    "CLOUDPULSE_OWNERSHIP_ATTRIBUTION_QUEUE_URL",
)


def _enqueue_governance_messages(scan: Scan) -> None:
    import os

    import boto3

    body = json.dumps(
        {
            "scan_id": str(scan.id),
            "tenant_id": str(scan.tenant_id),
            "cloud_account_id": str(scan.cloud_account_id),
        }
    )
    client = boto3.client("sqs")
    for env_var in _GOVERNANCE_QUEUE_ENV_VARS:
        queue_url = os.environ.get(env_var)
        if not queue_url:
            raise RuntimeError(f"{env_var} is not set")
        client.send_message(QueueUrl=queue_url, MessageBody=body)


# --- Daily trigger (FR-026) ---------------------------------------------------------


def start_due_daily_scans(session: TenantSession) -> list[str]:
    """Every connected, verified account is scanned automatically daily (FR-026).

    Deactivated (FR-009a) and not-yet-verified accounts are excluded structurally --
    the query only selects `verified` accounts. An account already mid-scan is
    skipped (FR-027), not queued or retried; it will be picked up the next day.
    """
    accounts = (
        session.raw.execute(
            session.scoped(select(CloudAccount), CloudAccount).where(
                CloudAccount.status == AccountStatus.VERIFIED
            )
        )
        .scalars()
        .all()
    )
    started: list[str] = []
    for account in accounts:
        try:
            scan = start_scan(session, account, trigger=ScanTrigger.SCHEDULED)
            started.append(str(scan.id))
        except ScanAlreadyRunningError:
            logger.info(
                "daily scan skipped -- already running",
                extra={"cloud_account_id": str(account.id)},
            )
    return started


# --- Diffing / persistence (FR-029, FR-030, FR-031, FR-032, R-204) ------------------


def persist_unit_result(
    session: TenantSession,
    *,
    cloud_account_id: uuid.UUID,
    resources: list[NormalizedResource],
) -> int:
    """Upsert discovered resources for one region (FR-029).

    A resource seen for the first time gets a new row (`first_seen_at` server-
    defaulted, never touched again). A resource seen again has `last_seen_at`
    refreshed, its mutable fields updated, and `deleted_at` cleared -- a resource
    that reappears after being marked deleted is no longer deleted.

    Does NOT run the deleted-marker sweep. That is a separate, whole-scan concern
    (`sweep_deleted_resources`), run once at `finalize_scan`, never per unit -- a
    partial view of one region mid-scan must never mark anything deleted.
    """
    count = 0
    for normalized in resources:
        existing = session.raw.execute(
            session.scoped(select(Resource), Resource).where(Resource.arn == normalized.resource_id)
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Resource(
                    cloud_account_id=cloud_account_id,
                    arn=normalized.resource_id,
                    resource_type=normalized.resource_type,
                    service=normalized.service,
                    region=normalized.region,
                    tags=normalized.tags,
                    state=normalized.state,
                    detail=normalized.detail,
                )
            )
        else:
            existing.last_seen_at = datetime.now(UTC)
            existing.state = normalized.state
            existing.tags = normalized.tags
            existing.detail = normalized.detail
            existing.deleted_at = None
        count += 1
    session.flush()
    return count


def sweep_deleted_resources(
    session: TenantSession,
    *,
    cloud_account_id: uuid.UUID,
    scan_started_at: datetime,
    completed_regions: list[str],
) -> int:
    """FR-030: mark resources deleted that were not re-confirmed by this scan.

    Scoped to `completed_regions` only (FR-031/FR-032) -- a region whose unit of
    work failed contributes no deletions, ever. Identifies "not found this scan" via
    `last_seen_at < scan_started_at` rather than an explicit found-ARN list passed
    through Step Functions state: `persist_unit_result` already refreshed
    `last_seen_at` for everything this scan actually found, so a resource whose
    `last_seen_at` predates the scan simply was not seen again -- and passing full
    ARN lists between Step Functions states would risk the 256KB payload limit on a
    large account (Edge Cases: "a very large account, tens of thousands of
    resources").
    """
    if not completed_regions:
        return 0
    resources = (
        session.raw.execute(
            session.scoped(select(Resource), Resource).where(
                Resource.cloud_account_id == cloud_account_id,
                Resource.region.in_(completed_regions),
                Resource.deleted_at.is_(None),
                Resource.last_seen_at < scan_started_at,
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for resource in resources:
        resource.deleted_at = now
    session.flush()
    return len(resources)


def finalize_scan(
    session: TenantSession, scan: Scan, unit_results: list[dict[str, str]]
) -> ScanStatus:
    """running -> succeeded | partial | failed (R-204), then the deleted-marker
    sweep for completed regions only, then `resource_count` -- in that order,
    because the sweep and the count both depend on knowing the final status first.
    """
    succeeded_regions = [u["region"] for u in unit_results if u.get("status") == "succeeded"]
    failed_regions = [u["region"] for u in unit_results if u.get("status") != "succeeded"]

    if not succeeded_regions:
        final_status = ScanStatus.FAILED
    elif not failed_regions:
        final_status = ScanStatus.SUCCEEDED
    else:
        final_status = ScanStatus.PARTIAL

    scan.status = final_status
    scan.finished_at = datetime.now(UTC)

    if final_status is not ScanStatus.FAILED:
        sweep_deleted_resources(
            session,
            cloud_account_id=scan.cloud_account_id,
            scan_started_at=scan.started_at,
            completed_regions=succeeded_regions,
        )
        # T026, research.md R-303: same succeeded/partial-only gate as the sweep
        # above and Phase 5's own FR-017 validation gate -- a failed scan starts
        # no governance work at all.
        _enqueue_governance_messages(scan)

    scan.resource_count = session.raw.execute(
        select(func.count())
        .select_from(Resource)
        .where(Resource.cloud_account_id == scan.cloud_account_id, Resource.deleted_at.is_(None))
    ).scalar_one()
    session.flush()

    logger.info(
        "scan finalized",
        extra={
            "scan_id": str(scan.id),
            "status": final_status.value,
            "succeeded_regions": len(succeeded_regions),
            "failed_regions": len(failed_regions),
            "resource_count": scan.resource_count,
        },
    )
    return final_status


__all__ = [
    "ScanAlreadyRunningError",
    "start_scan",
    "start_due_daily_scans",
    "persist_unit_result",
    "sweep_deleted_resources",
    "finalize_scan",
]
