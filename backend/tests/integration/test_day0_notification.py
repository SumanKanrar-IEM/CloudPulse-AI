"""Day-0 notification against a real database (T013; S24, FR-004, FR-005,
FR-012, FR-013, FR-014).

Two things here need a real engine rather than a stub session, which is why
they are integration tests and not part of T012's unit file:

* **"already attempted, so not due again"** is a `NOT EXISTS` against the
  `uq_notification_tenant_finding_cadence`-constrained table. It is the whole
  reason a re-run is idempotent instead of a second email, and a stub session
  can prove nothing about it.
* **the owner-email lookup** reads the `resource_owner` row spec 003's
  attribution worker wrote, joined through the finding's resource.

Every test in this file asserts the from-address, FR-014's fixed sending
identity, on every email the run produced -- deliberately not left as an
assumption checked once.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.governance.notifications import (
    NotificationEmail,
    deep_link,
    due_day0_findings,
    send_due_day0_notifications,
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
RULE_KEY = "require-owner-tag"


class _RawSession:
    """The same `TenantSession`-shaped shim `test_ownership_attribution.py`
    uses -- a real session plus the tenant filter, without needing Settings."""

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
def rule(db: Session, tenant_id: uuid.UUID) -> Rule:
    rule = Rule(tenant_id=tenant_id, key=RULE_KEY, version=1, definition={}, enabled=True)
    db.add(rule)
    db.flush()
    return rule


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


def _resource_with_owner(
    db: Session,
    tenant_id: uuid.UUID,
    account: CloudAccount,
    arn: str,
    owner_email: str | None,
) -> Resource:
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
        db.flush()
    return resource


def _open_finding(
    db: Session,
    tenant_id: uuid.UUID,
    rule: Rule,
    resource: Resource,
    *,
    opened_at: datetime | None = None,
) -> FindingRow:
    finding = FindingRow(
        tenant_id=tenant_id,
        resource_id=resource.id,
        rule_id=rule.id,
        rule_version=rule.version,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
        opened_at=opened_at or datetime.now(UTC),
    )
    db.add(finding)
    db.flush()
    return finding


def _run(session: _RawSession) -> tuple[list[NotificationEmail], list[NotificationOutcome]]:
    sent: list[NotificationEmail] = []
    outcomes = send_due_day0_notifications(
        session, sent.append, sender=SENDER, frontend_url=FRONTEND_URL
    )
    assert all(email.sender == SENDER for email in sent), "FR-014: fixed sending identity"
    return sent, outcomes


def test_a_finding_with_a_resolvable_owner_is_emailed_once_and_recorded_sent(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    resource = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    finding = _open_finding(db, tenant_id, rule, resource)

    sent, outcomes = _run(session)

    assert outcomes == [NotificationOutcome.SENT]
    assert len(sent) == 1
    assert sent[0].recipient == OWNER
    rows = db.execute(select(Notification).where(Notification.finding_id == finding.id)).scalars()
    row = next(iter(rows))
    assert row.cadence_point == NotificationCadencePoint.DAY_0
    assert row.outcome == NotificationOutcome.SENT
    assert row.recipient_email == OWNER


def test_the_link_resolves_to_that_findings_own_detail_view(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    """FR-005: the finding's own ID, not a generic findings-list URL. Asserted
    against a second finding's link too, so a hardcoded or first-row ID would
    fail rather than coincidentally pass."""
    first = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    second = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-2", OWNER)
    finding_a = _open_finding(db, tenant_id, rule, first)
    finding_b = _open_finding(db, tenant_id, rule, second)

    sent, _ = _run(session)

    link_a = deep_link(FRONTEND_URL, finding_a.id)
    link_b = deep_link(FRONTEND_URL, finding_b.id)
    bodies = [email.body for email in sent]
    assert sum(link_a in body for body in bodies) == 1
    assert sum(link_b in body for body in bodies) == 1
    # Neither email carries the other's link, which is what would happen if the
    # link were built from anything but the finding the email is about.
    assert not any(link_a in body and link_b in body for body in bodies)


def test_two_findings_for_the_same_owner_are_two_emails_never_one_bundle(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    """FR-012: one email per finding, even for the same recipient on the same
    day -- so each email carries exactly one actionable resource and link."""
    first = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    second = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-2", OWNER)
    finding_a = _open_finding(db, tenant_id, rule, first)
    finding_b = _open_finding(db, tenant_id, rule, second)

    sent, outcomes = _run(session)
    db.flush()

    assert len(sent) == 2
    assert outcomes == [NotificationOutcome.SENT, NotificationOutcome.SENT]
    assert {email.recipient for email in sent} == {OWNER}
    recorded = set(
        db.execute(
            select(Notification.finding_id).where(Notification.tenant_id == tenant_id)
        ).scalars()
    )
    assert recorded == {finding_a.id, finding_b.id}


def test_a_finding_already_attempted_is_not_due_again(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    """Any outcome counts as attempted, not only `sent` -- FR-010's "recorded,
    not retried forever". This is what makes a second daily pass idempotent."""
    resource = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    _open_finding(db, tenant_id, rule, resource)

    first_sent, _ = _run(session)
    db.flush()
    second_sent, second_outcomes = _run(session)

    assert len(first_sent) == 1
    assert second_sent == []
    assert second_outcomes == []
    assert (
        db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.tenant_id == tenant_id)
        ).scalar_one()
        == 1
    )


def test_a_withheld_attempt_also_blocks_a_second_attempt(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    resource = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", None)
    _open_finding(db, tenant_id, rule, resource)

    _, first_outcomes = _run(session)
    db.flush()
    second_sent, second_outcomes = _run(session)

    assert first_outcomes == [NotificationOutcome.WITHHELD_NO_OWNER_EMAIL]
    assert second_sent == []
    assert second_outcomes == []


def test_a_resolved_finding_is_not_due_at_all(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    resource = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    finding = _open_finding(db, tenant_id, rule, resource)
    finding.status = FindingStatus.RESOLVED
    finding.resolved_at = datetime.now(UTC)
    db.flush()

    assert due_day0_findings(session) == []


def test_a_finding_older_than_the_lookback_window_is_not_backfilled(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    """The bound's reason for existing: a first deployment must not email the
    owner of every open finding specs 003/004 ever created."""
    resource = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    _open_finding(db, tenant_id, rule, resource, opened_at=datetime.now(UTC) - timedelta(days=30))

    sent, outcomes = _run(session)

    assert sent == []
    assert outcomes == []


def test_the_email_names_the_rule_that_produced_the_finding(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, rule: Rule, account: CloudAccount
) -> None:
    """FR-004's "specific violation", read from the finding's own rule rather
    than a generic string."""
    resource = _resource_with_owner(db, tenant_id, account, "arn:aws:ec2:::i-1", OWNER)
    _open_finding(db, tenant_id, rule, resource)

    sent, _ = _run(session)

    assert RULE_KEY in sent[0].body
    assert "arn:aws:ec2:::i-1" in sent[0].subject
