"""SQS-triggered Lambda entrypoint for ownership attribution (spec 003, T027,
research.md R-302, R-303).

Triggered by the `ownership-attribution` queue -- one message per finalized
scan, enqueued by `app.scan.orchestrator.finalize_scan` (T026). Runs the bulk
CloudTrail sweep (`connectors.aws.sweep_cloudtrail_events`, R-302) once per
scan region, then correlates the combined event map against the account's
resource set in one call (`app.governance.ownership.attribute_ownership`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.db import tenant_session
from app.core.logging import logger
from app.governance.ownership import attribute_ownership
from app.models.core import CloudAccount
from app.models.enums import ConnectionMode
from connectors.aws import read_external_id, sweep_cloudtrail_events
from connectors.base import ConnectorAccount

# FR-020: "the preceding 90 days."
_LOOKBACK_DAYS = 90


def _process_scan(scan_id: str, tenant_id: uuid.UUID, cloud_account_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as session:
        account = session.raw.execute(
            session.scoped(select(CloudAccount), CloudAccount).where(
                CloudAccount.id == cloud_account_id
            )
        ).scalar_one()

        external_id: str | None = None
        if account.connection_mode is ConnectionMode.ASSUME_ROLE and account.external_id_ref:
            # Resolved fresh for this worker invocation (research.md R-206),
            # held only in memory, never logged (Principle III).
            external_id = read_external_id(account.external_id_ref)

        connector_account = ConnectorAccount(
            aws_account_id=account.aws_account_id,
            connection_mode=account.connection_mode.value,
            role_arn=account.role_arn,
            external_id=external_id,
        )

        since = datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)
        events_by_resource: dict[str, dict[str, Any]] = {}
        for region in account.scan_regions:
            events_by_resource.update(
                sweep_cloudtrail_events(connector_account, region, since=since)
            )

        attributed = attribute_ownership(session, cloud_account_id, events_by_resource)

    logger.info(
        "ownership attribution worker completed",
        extra={
            "scan_id": scan_id,
            "cloud_account_id": str(cloud_account_id),
            "resources_attributed": attributed,
        },
    )


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """SQS batch entrypoint -- one message per finalized scan (batch_size=1 in
    Terraform, so `Records` is normally a single-element list; iterated
    anyway rather than assumed, since SQS batching is a delivery detail, not
    a contract)."""
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        _process_scan(
            body["scan_id"], uuid.UUID(body["tenant_id"]), uuid.UUID(body["cloud_account_id"])
        )
    return {"processed": len(event.get("Records", []))}


__all__ = ["handler"]
