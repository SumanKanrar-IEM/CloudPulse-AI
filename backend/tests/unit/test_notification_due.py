"""The day-0 notification decision rules, without a database (T012; S24,
FR-004, FR-005, FR-010).

**Placement note.** T012 also names the "already attempted, so not due again"
rule. That one is a real `NOT EXISTS` against a real unique-constrained table
-- there is nothing for a stub session to prove about it -- so it is asserted
against a real PostgreSQL in `tests/integration/test_day0_notification.py`
(T013) instead. Same split, and the same reason, as `test_spend_ingestion.py`'s
own docstring already records: pure logic here, anything needing a real engine
in the integration suite.

What is genuinely pure, and therefore lives here: the deep link FR-005
requires, the email content FR-004 requires, and the per-finding outcome
branch FR-010 requires -- including that an unresolvable owner is *recorded*
rather than skipped or retried forever.

There is no bounce case to test. FR-010 originally covered a previously-bounced
address by deferring to a "spec 003 bounce flagging" feature that does not
exist; the requirement was amended and the unreachable `withheld_bounced`
outcome dropped (T017a's evidence, T017b's change, migration 0014).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.governance import notifications
from app.governance.notifications import (
    NotificationEmail,
    build_notification_email,
    deep_link,
    send_due_day0_notifications,
)
from app.models.core import Finding as FindingRow
from app.models.enums import (
    FindingKind,
    FindingSeverity,
    NotificationCadencePoint,
    NotificationOutcome,
)

FRONTEND_URL = "https://app.example.com"
ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc"
OWNER = "owner@example.com"
SENDER = "cloudpulse-dev@example.com"


class _RecordingSession:
    """Everything `send_due_day0_notifications` touches once the DB-backed
    lookups are stubbed: somewhere to put rows, and a flush."""

    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.raw = SimpleNamespace(flush=lambda: None)

    def add(self, instance: Any) -> None:
        self.rows.append(instance)


def _finding() -> FindingRow:
    return FindingRow(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        rule_version=1,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
    )


@pytest.fixture
def stub_lookups(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub only the three lookups that need a database, leaving the branch
    logic under test as the real thing."""

    def configure(findings: list[FindingRow], owner_email: str | None) -> None:
        monkeypatch.setattr(notifications, "due_day0_findings", lambda _s, **_kw: findings)
        monkeypatch.setattr(notifications, "_owner_email_of", lambda _s, _f: owner_email)
        monkeypatch.setattr(notifications, "_resource_arn_of", lambda _s, _f: ARN)
        monkeypatch.setattr(notifications, "_violation_of", lambda _s, _f: "require-owner-tag")

    return configure


def test_deep_link_points_at_the_finding_not_the_findings_list() -> None:
    """FR-005: the recipient lands on the finding the email is about."""
    finding_id = uuid.uuid4()
    assert deep_link(FRONTEND_URL, finding_id) == f"{FRONTEND_URL}/findings/{finding_id}"


def test_deep_link_does_not_double_the_slash_on_a_trailing_slash_base() -> None:
    finding_id = uuid.uuid4()
    assert deep_link(f"{FRONTEND_URL}/", finding_id) == f"{FRONTEND_URL}/findings/{finding_id}"


def test_the_email_names_the_resource_the_violation_and_the_link() -> None:
    """FR-004's three required contents, in one assertion each."""
    finding_id = uuid.uuid4()
    email = build_notification_email(
        cadence_point=NotificationCadencePoint.DAY_0,
        sender=SENDER,
        recipient=OWNER,
        frontend_url=FRONTEND_URL,
        finding_id=finding_id,
        resource_arn=ARN,
        violation="require-owner-tag",
    )
    assert email.sender == SENDER
    assert email.recipient == OWNER
    assert ARN in email.subject
    assert ARN in email.body
    assert "require-owner-tag" in email.body
    assert deep_link(FRONTEND_URL, finding_id) in email.body


def test_a_resolvable_owner_produces_one_sent_row_and_one_send(stub_lookups: Any) -> None:
    finding = _finding()
    stub_lookups([finding], OWNER)
    session = _RecordingSession()
    sent: list[NotificationEmail] = []

    outcomes = send_due_day0_notifications(
        session, sent.append, sender=SENDER, frontend_url=FRONTEND_URL
    )

    assert outcomes == [NotificationOutcome.SENT]
    assert len(sent) == 1
    assert sent[0].sender == SENDER
    assert sent[0].recipient == OWNER
    assert len(session.rows) == 1
    assert session.rows[0].outcome == NotificationOutcome.SENT
    assert session.rows[0].recipient_email == OWNER


def test_an_unresolvable_owner_is_recorded_as_withheld_and_never_emailed(
    stub_lookups: Any,
) -> None:
    """FR-010: recorded as unnotifiable -- not skipped, and not retried forever."""
    stub_lookups([_finding()], None)
    session = _RecordingSession()
    sent: list[NotificationEmail] = []

    outcomes = send_due_day0_notifications(
        session, sent.append, sender=SENDER, frontend_url=FRONTEND_URL
    )

    assert outcomes == [NotificationOutcome.WITHHELD_NO_OWNER_EMAIL]
    assert sent == []
    assert len(session.rows) == 1
    assert session.rows[0].outcome == NotificationOutcome.WITHHELD_NO_OWNER_EMAIL
    assert session.rows[0].recipient_email is None


def test_no_outcome_is_ever_sent_when_there_is_no_address_to_send_to(
    stub_lookups: Any,
) -> None:
    """The "never `sent`" half of T012, stated as its own assertion so a future
    change that starts recording `sent` on a withheld attempt fails loudly."""
    stub_lookups([_finding(), _finding()], None)
    session = _RecordingSession()

    outcomes = send_due_day0_notifications(
        session, lambda _e: None, sender=SENDER, frontend_url=FRONTEND_URL
    )

    assert NotificationOutcome.SENT not in outcomes


def test_one_failing_send_does_not_stop_the_rest_of_the_batch(stub_lookups: Any) -> None:
    """research.md R-501's per-finding isolation, in place of SQS retries. The
    failed finding gets no row on purpose, so the next daily pass retries it --
    a transport failure is not an unnotifiable address."""
    first, second = _finding(), _finding()
    stub_lookups([first, second], OWNER)
    session = _RecordingSession()
    sent: list[NotificationEmail] = []

    def flaky(email: NotificationEmail) -> None:
        if not sent:
            sent.append(email)
            raise RuntimeError("SES said no")
        sent.append(email)

    outcomes = send_due_day0_notifications(session, flaky, sender=SENDER, frontend_url=FRONTEND_URL)

    assert outcomes == [NotificationOutcome.SENT]
    assert len(session.rows) == 1
    assert session.rows[0].finding_id == second.id
