"""SQS-triggered Lambda entrypoint for compliance validation (spec 003, T028).

Triggered by the `compliance-validation` queue -- one message per finalized
scan, enqueued by `app.scan.orchestrator.finalize_scan` (T026). Runs the
governance write pipeline: SDA matching (T011), then rule evaluation (T016),
then logs the resulting compliance score (T019) for observability -- the
score itself is never persisted, computed fresh on every
`GET .../compliance-score` call instead (data-model.md).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import tenant_session
from app.core.logging import logger
from app.governance.scoring import account_compliance_score
from app.governance.sda_matching import reclassify_account_resources
from app.governance.validation import resolve_parent_child_relationships, validate_account
from app.models.core import CloudAccount


def _process_scan(scan_id: str, tenant_id: uuid.UUID, cloud_account_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as session:
        session.raw.execute(
            session.scoped(select(CloudAccount), CloudAccount).where(
                CloudAccount.id == cloud_account_id
            )
        ).scalar_one()

        # T011's SDA matching only evaluates top-level resources
        # (`parent_resource_id IS NULL`) -- resolved here first, ahead of
        # matching, so a resource discovered for the first time this scan is
        # correctly excluded from matching if it turns out to be a child.
        # Found while wiring this handler: T028's stated call order (SDA
        # matching, then validation) would otherwise let a brand-new child
        # resource's very first scan see it as top-level, since nothing had
        # resolved `parent_resource_id` for it yet -- `validate_account`
        # below also calls this (idempotently) as part of its own contract,
        # but by then SDA matching would already have run against stale data.
        resolve_parent_child_relationships(session, cloud_account_id)
        reclassify_account_resources(session, cloud_account_id)
        validate_account(session, cloud_account_id)
        _compliant, _total, score = account_compliance_score(session, cloud_account_id)

    logger.info(
        "compliance validation worker completed",
        extra={
            "scan_id": scan_id,
            "cloud_account_id": str(cloud_account_id),
            "compliance_score": score,
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
