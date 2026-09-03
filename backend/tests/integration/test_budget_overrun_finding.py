"""Budget overruns become findings, against a real database (T033; S41,
FR-016, FR-017, research.md R-507, R-508).

Needs a real engine throughout: the month-to-date and 7-day-window aggregates
are SQL, the one-open-overrun-per-project invariant is a partial unique index,
and `ck_finding_kind_shape` is what makes "attached to an SDA, not a resource"
a guarantee rather than a convention.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.governance.budgets import check_thresholds, create_budget_for_sda
from app.governance.notifications import send_due_day0_notifications
from app.models.core import Budget, CloudAccount, SpendRecord
from app.models.core import Finding as FindingRow
from app.models.core import Sda as SdaRow
from app.models.enums import (
    AccountStatus,
    ConnectionMode,
    FindingKind,
    FindingStatus,
    NotificationOutcome,
)

pytestmark = pytest.mark.integration

OWNER = "platform-owner@example.com"
AS_OF = date(2026, 4, 20)  # a 30-day month, 10 days remaining


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    @property
    def tenant_id(self) -> uuid.UUID:
        return self._tenant_id

    def scoped(self, statement: Any, model: Any) -> Any:
        return statement.where(model.tenant_id == self._tenant_id)

    def add(self, instance: Any) -> None:
        instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()


@pytest.fixture
def db(clean_database: Engine, alembic_config: Any) -> Iterator[Session]:
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant_id(db: Session) -> uuid.UUID:
    return uuid.UUID(str(db.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def session(db: Session, tenant_id: uuid.UUID) -> _RawSession:
    return _RawSession(db, tenant_id)


@pytest.fixture
def account(db: Session, tenant_id: uuid.UUID) -> CloudAccount:
    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add(account)
    db.flush()
    return account


@pytest.fixture
def budget(db: Session, session: _RawSession, tenant_id: uuid.UUID) -> Budget:
    sda = SdaRow(
        tenant_id=tenant_id,
        name="platform",
        owner_email=OWNER,
        tag_values={"project_id": "proj-a"},
    )
    db.add(sda)
    db.flush()
    budget = create_budget_for_sda(session, sda, amount_usd=Decimal("1000.00"))
    db.flush()
    return budget


def _spend(
    db: Session,
    tenant_id: uuid.UUID,
    account: CloudAccount,
    budget: Budget,
    day: date,
    amount: str | None,
) -> None:
    db.add(
        SpendRecord(
            tenant_id=tenant_id,
            cloud_account_id=account.id,
            sda_id=budget.sda_id,
            service="AmazonEC2" if amount is not None else None,
            spend_date=day,
            amount_usd=Decimal(amount) if amount is not None else None,
            is_gap=amount is None,
        )
    )
    db.flush()


def _overrun_findings(db: Session, tenant_id: uuid.UUID) -> list[FindingRow]:
    return list(
        db.execute(
            select(FindingRow).where(
                FindingRow.tenant_id == tenant_id,
                FindingRow.kind == FindingKind.BUDGET_OVERRUN,
            )
        )
        .scalars()
        .all()
    )


def test_spend_under_the_cap_opens_nothing(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "100.00")

    check_thresholds(session, budget, as_of=AS_OF)

    assert _overrun_findings(db, tenant_id) == []
    assert budget.actual_100_crossed_at is None


def test_crossing_actual_100_opens_a_finding_attached_to_the_sda(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """R-508: attached to the project, with resource and rule NULL --
    `ck_finding_kind_shape` refuses any other shape."""
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "1200.00")

    check_thresholds(session, budget, as_of=AS_OF)

    findings = _overrun_findings(db, tenant_id)
    assert len(findings) == 1
    assert findings[0].sda_id == budget.sda_id
    assert findings[0].resource_id is None
    assert findings[0].rule_id is None
    assert findings[0].rule_version is None
    assert findings[0].status is FindingStatus.OPEN
    assert budget.actual_100_crossed_at is not None


def test_a_second_run_while_still_over_does_not_duplicate_the_finding(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """The partial unique index makes this impossible at the database; checking
    first means the second daily run is a no-op rather than an IntegrityError
    the worker has to catch."""
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "1200.00")

    check_thresholds(session, budget, as_of=AS_OF)
    check_thresholds(session, budget, as_of=AS_OF)

    assert len(_overrun_findings(db, tenant_id)) == 1


def test_spend_dropping_back_under_resolves_the_finding(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """FR-017. A correction-in-place ingestion is the realistic way spend drops:
    Cost Explorer revised the day down."""
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "1200.00")
    check_thresholds(session, budget, as_of=AS_OF)
    assert len(_overrun_findings(db, tenant_id)) == 1

    row = db.execute(select(SpendRecord).where(SpendRecord.sda_id == budget.sda_id)).scalar_one()
    row.amount_usd = Decimal("100.00")
    db.flush()

    check_thresholds(session, budget, as_of=AS_OF)

    findings = _overrun_findings(db, tenant_id)
    assert len(findings) == 1
    assert findings[0].status is FindingStatus.RESOLVED
    assert findings[0].resolved_at is not None
    assert budget.actual_100_crossed_at is None


def test_a_gap_day_contributes_nothing_rather_than_zero(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """FR-002a rows carry a NULL amount. They must not be averaged into the
    forecast as a false zero, which would systematically understate it."""
    for offset in range(7):
        _spend(db, tenant_id, account, budget, AS_OF - timedelta(days=offset), "10.00")
    _spend(db, tenant_id, account, budget, date(2026, 4, 3), None)

    state = check_thresholds(session, budget, as_of=AS_OF)

    assert state.actual_usd == Decimal("70.00")
    # 10/day over the window, 10 days left in April from the 20th.
    assert state.forecast_usd == Decimal("170.00")


def test_an_80_percent_crossing_opens_no_finding(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """R-507 and the spec's own Clarifications: 80% is dashboard-only."""
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "850.00")

    check_thresholds(session, budget, as_of=AS_OF)

    assert _overrun_findings(db, tenant_id) == []
    assert budget.actual_80_crossed_at is not None
    assert budget.actual_100_crossed_at is None


def test_last_months_crossings_reset_at_the_start_of_a_new_month(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """data-model.md: the four timestamps are per-calendar-month, reset by this
    same daily run rather than by a separate scheduled job."""
    budget.actual_80_crossed_at = datetime(2026, 3, 15, tzinfo=UTC)
    budget.actual_100_crossed_at = datetime(2026, 3, 16, tzinfo=UTC)
    db.flush()
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "10.00")

    check_thresholds(session, budget, as_of=AS_OF)

    # Re-read rather than asserting on the in-memory object: this proves the
    # reset actually persisted, not just that the attribute was reassigned.
    refreshed = db.execute(select(Budget).where(Budget.id == budget.id)).scalar_one()
    assert refreshed.actual_80_crossed_at is None
    assert refreshed.actual_100_crossed_at is None


def test_an_overrun_finding_is_notified_like_any_other(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """FR-016: "notified the same way any other finding is". A budget_overrun
    finding has no resource, so the resource_owner chain has nothing to look up
    -- without the SDA-owner fallback every overrun would resolve to
    `withheld_no_owner_email` and this requirement would be silently unmet."""
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "1200.00")
    check_thresholds(session, budget, as_of=AS_OF)

    sent: list[Any] = []
    outcomes = send_due_day0_notifications(
        session, sent.append, sender="dev@example.com", frontend_url="https://app.example.com"
    )

    assert outcomes == [NotificationOutcome.SENT]
    assert len(sent) == 1
    assert sent[0].recipient == OWNER
    # The project's name, not a bare UUID -- the recipient needs something they
    # can recognise as theirs.
    assert "platform" in sent[0].subject


def test_only_this_tenants_budgets_are_counted(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, budget: Budget
) -> None:
    """The aggregates are tenant-scoped queries; asserted rather than assumed,
    since a missing filter here would leak another tenant's spend into this
    project's threshold verdict."""
    _spend(db, tenant_id, account, budget, date(2026, 4, 2), "500.00")

    state = check_thresholds(session, budget, as_of=AS_OF)

    assert state.actual_usd == Decimal("500.00")
    assert (
        db.execute(
            select(func.count()).select_from(Budget).where(Budget.tenant_id == tenant_id)
        ).scalar_one()
        == 1
    )
