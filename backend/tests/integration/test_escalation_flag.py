"""The cadence and the escalation flag against a real database (T019; S25,
FR-006, FR-007, FR-008, FR-009, FR-011).

Everything here needs a real engine. The reminder due-query is a correlated
subquery over `notification.attempted_at`; FR-011's independence rests on the
`uq_notification_tenant_finding_cadence` constraint being per `Finding.id`;
and the escalated flag has to survive a round trip through the API.

**Deviation from T019 as written**: T019 says `GET /findings/{findingId}`
reflects the flag. No single-finding GET endpoint exists -- spec 004 shipped
`GET /findings` (a list) plus the two `/{findingId}/...` sub-resources, and
inventing a third shape here to satisfy a task's phrasing would be worse than
asserting against the endpoint that actually serves findings to the dashboard.
Recorded as T019a in tasks.md.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import findings as findings_router
from app.governance.notifications import (
    NotificationEmail,
    due_reminder_findings,
    flag_stale_escalations,
    send_due_day0_notifications,
    send_due_reminders,
)
from app.models.core import CloudAccount, Notification, Resource, ResourceOwner, Rule
from app.models.core import Finding as FindingRow
from app.models.enums import (
    AccountStatus,
    ConnectionMode,
    FindingKind,
    FindingSeverity,
    FindingStatus,
    NotificationCadencePoint,
    NotificationOutcome,
    OwnerConfidence,
)

pytestmark = pytest.mark.integration

FRONTEND_URL = "https://app.example.com"
SENDER = "cloudpulse-dev@example.com"
OWNER = "owner@example.com"
VIEWER = ["cloudpulse-viewers"]


class _RawSession:
    """The `TenantSession`-shaped shim this suite already uses elsewhere."""

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


class _ClaimStager:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.claims: dict[str, Any] | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


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
def api(
    clean_database: Engine, db: Session, tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(findings_router.router)
    stager = _ClaimStager(app)
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": VIEWER,
        "custom:tenant_id": str(tenant_id),
    }
    return TestClient(stager, raise_server_exceptions=False)


@pytest.fixture
def fixtures(db: Session, tenant_id: uuid.UUID) -> tuple[Rule, CloudAccount]:
    rule = Rule(
        tenant_id=tenant_id, key="require-owner-tag", version=1, definition={}, enabled=True
    )
    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add_all([rule, account])
    db.flush()
    return rule, account


def _finding_with_owner(
    db: Session,
    tenant_id: uuid.UUID,
    fixtures: tuple[Rule, CloudAccount],
    arn: str,
    *,
    owner_email: str | None = OWNER,
) -> FindingRow:
    rule, account = fixtures
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn=arn,
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    db.add(resource)
    db.flush()
    if owner_email is not None:
        db.add(
            ResourceOwner(
                tenant_id=tenant_id,
                resource_id=resource.id,
                owner_email=owner_email,
                evidence={"source": "test"},
                confidence=OwnerConfidence.HIGH,
            )
        )
    finding = FindingRow(
        tenant_id=tenant_id,
        resource_id=resource.id,
        rule_id=rule.id,
        rule_version=rule.version,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    db.add(finding)
    db.flush()
    return finding


def _day0(
    db: Session, tenant_id: uuid.UUID, finding: FindingRow, *, days_ago: float
) -> Notification:
    """A day-0 attempt already on the record, backdated -- the anchor FR-006
    measures both reminders from."""
    row = Notification(
        tenant_id=tenant_id,
        finding_id=finding.id,
        cadence_point=NotificationCadencePoint.DAY_0,
        outcome=NotificationOutcome.SENT,
        recipient_email=OWNER,
        attempted_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(row)
    db.flush()
    return row


def _run_reminders(session: _RawSession) -> tuple[list[NotificationEmail], list[Any]]:
    sent: list[NotificationEmail] = []
    outcomes = send_due_reminders(session, sent.append, sender=SENDER, frontend_url=FRONTEND_URL)
    assert all(email.sender == SENDER for email in sent), "FR-014: fixed sending identity"
    return sent, outcomes


def test_a_finding_two_days_past_its_day_0_is_due_for_day_2_only(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=2.5)

    assert [f.id for f in due_reminder_findings(session, NotificationCadencePoint.DAY_2)] == [
        finding.id
    ]
    assert due_reminder_findings(session, NotificationCadencePoint.DAY_4) == []


def test_a_finding_one_day_past_its_day_0_is_due_for_neither(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=1)

    assert due_reminder_findings(session, NotificationCadencePoint.DAY_2) == []
    assert due_reminder_findings(session, NotificationCadencePoint.DAY_4) == []


def test_a_finding_with_no_day_0_row_is_never_due_for_a_reminder(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    """The cadence is anchored on the day-0 attempt, so a finding that never
    got one cannot skip straight to being chased."""
    _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")

    assert due_reminder_findings(session, NotificationCadencePoint.DAY_2) == []


def test_a_reminder_already_sent_is_not_sent_again(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=2.5)

    first, _ = _run_reminders(session)
    db.flush()
    second, second_outcomes = _run_reminders(session)

    assert len(first) == 1
    assert second == []
    assert second_outcomes == []


def test_a_finding_resolved_before_its_reminder_is_recorded_suppressed(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    """FR-007, and the row that makes it auditable."""
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=2.5)
    finding.status = FindingStatus.RESOLVED
    finding.resolved_at = datetime.now(UTC)
    db.flush()

    sent, outcomes = _run_reminders(session)
    db.flush()

    assert sent == []
    assert outcomes == [NotificationOutcome.SUPPRESSED_FINDING_CLOSED]
    row = db.execute(
        select(Notification).where(
            Notification.finding_id == finding.id,
            Notification.cadence_point == NotificationCadencePoint.DAY_2,
        )
    ).scalar_one()
    assert row.outcome == NotificationOutcome.SUPPRESSED_FINDING_CLOSED


def test_a_reopened_finding_starts_its_own_cadence(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    """FR-011. A reopened finding is a fresh `Finding.id` (spec 003's re-open
    semantics), and the cadence is keyed per finding, so the prior occurrence's
    rows neither block nor accelerate the new one -- asserted rather than
    assumed, since it is the whole reason no "cycle number" column exists."""
    rule, _ = fixtures
    old = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    for cadence in NotificationCadencePoint:
        db.add(
            Notification(
                tenant_id=tenant_id,
                finding_id=old.id,
                cadence_point=cadence,
                outcome=NotificationOutcome.SENT,
                recipient_email=OWNER,
            )
        )
    old.status = FindingStatus.RESOLVED
    old.resolved_at = datetime.now(UTC)
    db.flush()

    # The same resource fails the same rule again -- a new row, per FR-011.
    reopened = FindingRow(
        tenant_id=tenant_id,
        resource_id=old.resource_id,
        rule_id=rule.id,
        rule_version=rule.version,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    db.add(reopened)
    db.flush()

    send_due_day0_notifications(session, lambda _e: None, sender=SENDER, frontend_url=FRONTEND_URL)
    db.flush()

    fresh = (
        db.execute(select(Notification).where(Notification.finding_id == reopened.id))
        .scalars()
        .all()
    )
    # Its own day-0, and only that: the prior occurrence's completed day-2/day-4
    # rows neither block the new cadence nor start it partway through.
    assert [row.cadence_point for row in fresh] == [NotificationCadencePoint.DAY_0]
    assert due_reminder_findings(session, NotificationCadencePoint.DAY_2) == []
    assert due_reminder_findings(session, NotificationCadencePoint.DAY_4) == []


def test_a_still_open_finding_is_escalated_once_its_day_4_row_exists(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=4.5)

    _run_reminders(session)
    db.flush()
    flagged = flag_stale_escalations(session)

    assert flagged == 1
    assert finding.escalated_at is not None


def test_escalation_is_idempotent(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=4.5)
    _run_reminders(session)
    db.flush()

    flag_stale_escalations(session)
    first_flagged_at = finding.escalated_at
    assert flag_stale_escalations(session) == 0
    assert finding.escalated_at == first_flagged_at


def test_a_finding_with_only_a_day_2_row_is_not_escalated(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    """FR-008 is specific: after the *day-4* reminder, not after any reminder."""
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=2.5)
    _run_reminders(session)
    db.flush()

    assert flag_stale_escalations(session) == 0
    assert finding.escalated_at is None


def test_a_resolved_finding_is_never_escalated(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any
) -> None:
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=4.5)
    _run_reminders(session)
    finding.status = FindingStatus.RESOLVED
    finding.resolved_at = datetime.now(UTC)
    db.flush()

    assert flag_stale_escalations(session) == 0
    assert finding.escalated_at is None


def test_the_api_shows_an_escalated_finding_as_escalated(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any, api: TestClient
) -> None:
    """FR-009, via the endpoint that actually serves findings to the dashboard
    (see this module's docstring on T019's `GET /findings/{findingId}`)."""
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=4.5)
    _run_reminders(session)
    flag_stale_escalations(session)
    db.commit()

    body = api.get("/findings").json()

    assert len(body["findings"]) == 1
    assert body["findings"][0]["escalatedAt"] is not None


def test_acknowledging_an_escalated_finding_stops_it_displaying_as_escalated(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, fixtures: Any, api: TestClient
) -> None:
    """FR-009's second half. The stored `escalated_at` is deliberately left
    alone -- it is the honest record of when escalation happened; what changes
    is whether the finding still *displays* as escalated."""
    finding = _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    _day0(db, tenant_id, finding, days_ago=4.5)
    _run_reminders(session)
    flag_stale_escalations(session)
    db.commit()
    assert api.get("/findings").json()["findings"][0]["escalatedAt"] is not None

    finding.acknowledged_at = datetime.now(UTC)
    db.commit()

    assert api.get("/findings").json()["findings"][0]["escalatedAt"] is None
    assert finding.escalated_at is not None


def test_a_finding_not_yet_escalated_reports_no_escalation(
    db: Session, tenant_id: uuid.UUID, fixtures: Any, api: TestClient
) -> None:
    _finding_with_owner(db, tenant_id, fixtures, "arn:aws:ec2:::i-1")
    db.commit()

    assert api.get("/findings").json()["findings"][0]["escalatedAt"] is None
