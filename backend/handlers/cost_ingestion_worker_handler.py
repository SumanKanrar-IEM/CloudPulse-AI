"""Lambda entrypoint EventBridge Scheduler invokes daily (spec 005, FR-001,
research.md R-501/R-505).

One action only (`trigger_daily`) -- the schedule carries no per-account
knowledge, matching `scan_worker_handler.py`'s own `trigger_daily` shape
exactly: the worker itself queries which accounts are due (every verified
one, `app.governance.spend.due_accounts`) each run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import TenantSession, tenant_session
from app.core.logging import logger
from app.governance import budgets, spend
from app.models.core import Budget as BudgetRow
from app.models.enums import ConnectionMode
from connectors.aws import get_daily_spend, read_external_id
from connectors.base import ConnectorAccount

# Cost Explorer is account-wide, not per-region -- its API is only ever called
# via the us-east-1 endpoint regardless of which regions an account's own
# resources live in (an AWS platform constraint, not a CloudPulse choice).
_COST_EXPLORER_REGION = "us-east-1"

_MAX_INGESTION_ATTEMPTS = 3  # FR-002a


def _fetch_with_retries(
    account: ConnectorAccount, tag_key: str, day: date
) -> list[dict[str, Any]] | None:
    """Up to `_MAX_INGESTION_ATTEMPTS` attempts; `None` means every one failed
    (FR-002a) -- the caller writes an explicit gap rather than guessing."""
    last_error: Exception | None = None
    for attempt in range(1, _MAX_INGESTION_ATTEMPTS + 1):
        try:
            return get_daily_spend(account, _COST_EXPLORER_REGION, tag_key, day)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "spend ingestion attempt failed",
                extra={"attempt": attempt, "error": str(last_error)},
            )
    return None


def _handle_trigger_daily(_event: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import text

    from app.core.db import get_engine

    day = _yesterday_utc()
    tag_key = get_settings().project_tag_key

    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )

    ingested: list[str] = []
    with tenant_session(tenant_id) as session:
        accounts = spend.due_accounts(session)
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
                rows = _fetch_with_retries(connector_account, tag_key, day)
                spend.ingest_spend_rows(session, account, day, rows)
                ingested.append(str(account.id))
                # research.md R-505: the threshold check runs here, in the same
                # transaction as the spend that triggers it -- not in a second
                # worker that would have to either re-derive the day's total or
                # trust this one already committed. Budgets are tenant-wide, not
                # per-account, so this runs once after the account loop rather
                # than once per account.
            except Exception:
                # One account's failure must not block another's (T008) --
                # logged, not raised.
                logger.exception(
                    "cost ingestion failed for account", extra={"cloud_account_id": str(account.id)}
                )
        overruns = _check_all_budgets(session, day)
    return {"ingested": ingested, "spend_date": day.isoformat(), "budgets_checked": overruns}


def _check_all_budgets(session: TenantSession, day: date) -> int:
    """FR-015-FR-017 for every project with a budget, after the day's spend has
    landed.

    One budget's failure is logged and skipped rather than raised: an overrun
    check that blew up on a single malformed budget must not discard the whole
    run's ingestion, which has already succeeded by this point.
    """
    checked = 0
    for budget in session.raw.execute(session.scoped(select(BudgetRow), BudgetRow)).scalars().all():
        try:
            budgets.check_thresholds(session, budget, as_of=day)
            checked += 1
        except Exception:
            logger.exception("budget threshold check failed", extra={"budget_id": str(budget.id)})
    return checked


def _yesterday_utc() -> date:
    """Cost Explorer reports completed days; "today" is always still
    accruing, so the daily run always targets the most recent fully-completed
    calendar day (Assumptions: "day" is a UTC calendar boundary)."""
    from datetime import datetime

    return (datetime.now(UTC) - timedelta(days=1)).date()


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_daily")
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["handler"]
