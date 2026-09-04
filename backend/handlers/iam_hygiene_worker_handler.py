"""Weekly EventBridge entrypoint for IAM hygiene (spec 005, T046, FR-019,
research.md R-503, R-510).

**Weekly, not daily.** IAM last-used data changes slowly -- the analysis window
is 90 days -- so a daily run would spend seven times the invocations and the
IAM API calls to move a flag at most a day sooner. R-510's cheapest-cadence
rule, applied to a feature whose whole output is a recommendation a human reads
at their leisure.

This module owns the AWS client; `app.governance.iam_hygiene` owns the
judgement (Principle V, FR-054), which is what lets FR-020's no-false-flag rule
be tested without an AWS client at all.

**Runtime limitation, stated plainly**: like `cost-ingestion-worker`, this is
VPC-attached with no NAT gateway, and the `iam:*` calls it makes have no VPC
interface endpoint at all -- an AWS platform limitation, not a configuration
choice (research.md R-503, R-511). Every rule here is proven by the mocked
tests; the live calls cannot succeed from inside the VPC until R-407 is funded.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.db import get_engine, tenant_session
from app.core.logging import logger
from app.governance import iam_hygiene
from app.models.core import CloudAccount
from app.models.enums import AccountStatus, ConnectionMode
from connectors.aws import iam_unused_analysis, read_external_id
from connectors.base import ConnectorAccount


def _to_candidates(raw: list[dict[str, Any]]) -> list[iam_hygiene.Candidate]:
    """Raw connector dicts to the governance layer's own type, dropping any
    record missing the two fields every rule depends on rather than letting a
    malformed entry decide a human-facing recommendation."""
    candidates: list[iam_hygiene.Candidate] = []
    for entry in raw:
        if not entry.get("principal_type") or not entry.get("identifier"):
            logger.warning("skipping an IAM principal with no usable identity")
            continue
        candidates.append(
            iam_hygiene.Candidate(
                principal_type=str(entry["principal_type"]),
                identifier=str(entry["identifier"]),
                name=str(entry.get("name") or entry["identifier"]),
                created_at=entry.get("created_at"),
                last_used_at=entry.get("last_used_at"),
                reason=entry.get("reason"),
                status=entry.get("status"),
            )
        )
    return candidates


def _handle_trigger_weekly(_event: dict[str, Any]) -> dict[str, Any]:
    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )

    analysed: list[str] = []
    flagged_total = 0
    cleared_total = 0

    with tenant_session(tenant_id) as session:
        accounts = (
            session.raw.execute(
                session.scoped(select(CloudAccount), CloudAccount).where(
                    CloudAccount.status == AccountStatus.VERIFIED
                )
            )
            .scalars()
            .all()
        )
        for account in accounts:
            try:
                external_id: str | None = None
                if (
                    account.connection_mode is ConnectionMode.ASSUME_ROLE
                    and account.external_id_ref
                ):
                    external_id = read_external_id(account.external_id_ref)
                connector_account = ConnectorAccount(
                    aws_account_id=account.aws_account_id,
                    connection_mode=account.connection_mode.value,
                    role_arn=account.role_arn,
                    external_id=external_id,
                )
                candidates = _to_candidates(iam_unused_analysis(connector_account))
                flagged, cleared = iam_hygiene.reconcile_flags(session, account.id, candidates)
                flagged_total += flagged
                cleared_total += cleared
                analysed.append(str(account.id))
            except Exception:
                # One account's failure must not block another's, and must not
                # clear that account's flags: reconcile_flags is never reached
                # for an account whose analysis raised, so its existing flags
                # stand untouched rather than being cleared on no evidence.
                logger.exception(
                    "iam hygiene analysis failed for account",
                    extra={"cloud_account_id": str(account.id)},
                )

    result = {"analysed": analysed, "flagged": flagged_total, "cleared": cleared_total}
    logger.info("iam hygiene worker completed", extra=result)
    return result


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_weekly")
    if action == "trigger_weekly":
        return _handle_trigger_weekly(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["handler"]
