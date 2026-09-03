"""Spend ingestion: SDA attribution, correction, gap handling (spec 005,
FR-001, FR-002a).

`connectors.aws.get_daily_spend` makes the one AWS call; the retry loop and
`ConnectorAccount` construction live in the worker handler
(`handlers/cost_ingestion_worker_handler.py`), matching
`ownership_attribution_worker_handler.py`'s own precedent -- a connector call
is made directly by the handler, not delegated through `app/governance/`,
keeping this module free of any AWS-SDK-adjacent code at all (the
connector-boundary rule, Principle V). This module receives already-fetched
rows (or `None`, meaning every retry failed) and does the DB-side work only:
SDA attribution (reusing spec 003's own `sda_matching.find_matching_sda`),
upsert-or-correct, and the explicit-gap fallback.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.core.db import TenantSession
from app.core.logging import logger
from app.governance.sda_matching import find_matching_sda
from app.models.core import CloudAccount
from app.models.core import Sda as SdaRow
from app.models.core import SpendRecord as SpendRecordRow
from app.models.enums import AccountStatus


def resolve_sda_id(tag_value: str | None, sdas: list[SdaRow], tag_key: str) -> uuid.UUID | None:
    """Pure: which SDA (if any) one spend row's tag value attributes to.

    `tag_value=None` (an untagged/unmatched resource, per
    `connectors.aws._parse_cost_and_usage_response`'s own convention) always
    resolves to the "No SDA" bucket (`None`) without even calling
    `find_matching_sda` -- that function's own contract requires a non-empty
    mapping to match anything (spec 003 FR-008), so a `None` tag value could
    never match regardless."""
    if tag_value is None:
        return None
    matched = find_matching_sda({tag_key: tag_value}, sdas)
    return matched.id if matched else None


def due_accounts(session: TenantSession) -> list[CloudAccount]:
    """Every verified account gets today's spend ingested -- the same
    selection `app.scan.orchestrator.start_due_daily_scans` already uses."""
    return list(
        session.raw.execute(
            session.scoped(select(CloudAccount), CloudAccount).where(
                CloudAccount.status == AccountStatus.VERIFIED
            )
        )
        .scalars()
        .all()
    )


def ingest_spend_rows(
    session: TenantSession,
    account: CloudAccount,
    day: date,
    rows: list[dict[str, Any]] | None,
) -> None:
    """Write one account/day's ingestion result.

    `rows=None` means every retry of the AWS call failed (FR-002a) -- writes
    one explicit gap row for the day rather than a guessed or zeroed amount.
    `rows=[]` (a real, successful call reporting zero cost) is NOT a gap --
    the account genuinely had no spend that day, a fact worth recording
    faithfully, not conflating with "we couldn't find out."
    """
    if rows is None:
        _write_gap(session, account, day)
        logger.warning(
            "spend ingestion failed after retries -- recorded as a gap",
            extra={"cloud_account_id": str(account.id), "spend_date": day.isoformat()},
        )
        return

    sdas = list(session.raw.execute(session.scoped(select(SdaRow), SdaRow)).scalars().all())
    tag_key = get_settings().project_tag_key
    for row in rows:
        sda_id = resolve_sda_id(row["tag_value"], sdas, tag_key)
        _upsert_spend_record(
            session,
            account_id=account.id,
            sda_id=sda_id,
            service=row["service"],
            day=day,
            amount_usd=row["amount_usd"],
        )
    session.raw.flush()


def _upsert_spend_record(
    session: TenantSession,
    *,
    account_id: uuid.UUID,
    sda_id: uuid.UUID | None,
    service: str,
    day: date,
    amount_usd: Decimal,
) -> None:
    """One (account, service, day, sda) row, corrected in place on a repeat
    ingestion. Two separate `ON CONFLICT` targets, not one -- `core.py`'s own
    `SpendRecord` docstring explains why a plain constraint including a
    nullable `sda_id` can't do this correctly (a "No SDA" row's correction
    needs the index that omits `sda_id` from its key entirely, migration
    0013)."""
    values = {
        "tenant_id": session.tenant_id,
        "cloud_account_id": account_id,
        "sda_id": sda_id,
        "service": service,
        "spend_date": day,
        "amount_usd": amount_usd,
        "is_gap": False,
    }
    stmt = pg_insert(SpendRecordRow).values(**values)
    # index_where must match the target partial index's own predicate
    # *textually*, not just logically -- Postgres's ON CONFLICT arbiter-index
    # inference failed here on the first attempt using `.is_(False)`/
    # `.is_not(None)` (renders as `IS false`/`IS NOT NULL`) against an index
    # created with the literal text below (`= false`); found live by actually
    # running this against a real Postgres, not assumed from the ORM syntax.
    if sda_id is None:
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "cloud_account_id", "service", "spend_date"],
            index_where=text("is_gap = false AND sda_id IS NULL"),
            set_={"amount_usd": amount_usd},
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "cloud_account_id", "service", "spend_date", "sda_id"],
            index_where=text("is_gap = false AND sda_id IS NOT NULL"),
            set_={"amount_usd": amount_usd},
        )
    session.raw.execute(stmt)


def _write_gap(session: TenantSession, account: CloudAccount, day: date) -> None:
    """At most one gap row per (account, day) -- `on_conflict_do_nothing`
    makes a second failed attempt for the same day idempotent rather than a
    duplicate."""
    stmt = pg_insert(SpendRecordRow).values(
        tenant_id=session.tenant_id,
        cloud_account_id=account.id,
        sda_id=None,
        service=None,
        spend_date=day,
        amount_usd=None,
        is_gap=True,
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["tenant_id", "cloud_account_id", "spend_date"],
        index_where=text("is_gap = true"),
    )
    session.raw.execute(stmt)
    session.raw.flush()


__all__ = ["due_accounts", "resolve_sda_id", "ingest_spend_rows"]
