"""The day-2/day-4 reminder decision rules, without a database (T018; S25,
FR-006, FR-007, FR-011).

Same split as `test_notification_due.py`: what is pure lives here, and the
parts that are a real correlated subquery against a real table -- "the day-0
attempt is old enough", "no row at this cadence point yet", and FR-011's
independent cadence for a reopened finding -- are asserted against a real
PostgreSQL in `tests/integration/test_escalation_flag.py`.

What is genuinely pure, and therefore here: FR-007's "already dealt with"
predicate in all three of its states, and the branch that turns it into a
`suppressed_finding_closed` row rather than into silence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.governance import notifications
from app.governance.notifications import (
    NotificationEmail,
    build_notification_email,
    send_due_reminders,
)
from app.models.core import Finding as FindingRow
from app.models.enums import (
    FindingKind,
    FindingSeverity,
    FindingStatus,
    NotificationCadencePoint,
    NotificationOutcome,
)

FRONTEND_URL = "https://app.example.com"
SENDER = "cloudpulse-dev@example.com"
OWNER = "owner@example.com"
ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc"


class _RecordingSession:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.raw = SimpleNamespace(flush=lambda: None)

    def add(self, instance: Any) -> None:
        self.rows.append(instance)


def _finding(
    *,
    status: FindingStatus = FindingStatus.OPEN,
    acknowledged_at: datetime | None = None,
) -> FindingRow:
    return FindingRow(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        rule_version=1,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
        status=status,
        acknowledged_at=acknowledged_at,
    )


@pytest.fixture
def stub_lookups(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub only the DB-backed lookups, leaving the branch logic under test."""

    def configure(
        due: dict[NotificationCadencePoint, list[FindingRow]], owner_email: str | None = OWNER
    ) -> None:
        monkeypatch.setattr(
            notifications,
            "due_reminder_findings",
            lambda _s, cadence_point, **_kw: due.get(cadence_point, []),
        )
        monkeypatch.setattr(notifications, "_owner_email_of", lambda _s, _f: owner_email)
        monkeypatch.setattr(notifications, "_resource_arn_of", lambda _s, _f: ARN)
        monkeypatch.setattr(notifications, "_violation_of", lambda _s, _f: "require-owner-tag")

    return configure


def _run(session: Any, send: Any) -> list[NotificationOutcome]:
    return send_due_reminders(session, send, sender=SENDER, frontend_url=FRONTEND_URL)


def test_a_reminder_says_it_is_a_reminder() -> None:
    """FR-006 asks for a reminder. An email identical to the day-0 one would
    read as a duplicate send, not as a second nudge."""
    email = build_notification_email(
        cadence_point=NotificationCadencePoint.DAY_2,
        sender=SENDER,
        recipient=OWNER,
        frontend_url=FRONTEND_URL,
        finding_id=uuid.uuid4(),
        resource_arn=ARN,
        violation="require-owner-tag",
    )
    assert email.subject.startswith("Reminder: ")
    assert "still open" in email.body


def test_a_reminder_carries_the_same_resource_violation_and_link_as_day_0() -> None:
    """A reminder that made the recipient go find the original would be worse
    than no reminder."""
    finding_id = uuid.uuid4()
    common = {
        "sender": SENDER,
        "recipient": OWNER,
        "frontend_url": FRONTEND_URL,
        "finding_id": finding_id,
        "resource_arn": ARN,
        "violation": "require-owner-tag",
    }
    day0 = build_notification_email(cadence_point=NotificationCadencePoint.DAY_0, **common)
    day2 = build_notification_email(cadence_point=NotificationCadencePoint.DAY_2, **common)
    for fragment in (ARN, "require-owner-tag", notifications.deep_link(FRONTEND_URL, finding_id)):
        assert fragment in day0.body
        assert fragment in day2.body


def test_an_open_unacknowledged_finding_is_reminded(stub_lookups: Any) -> None:
    finding = _finding()
    stub_lookups({NotificationCadencePoint.DAY_2: [finding]})
    session = _RecordingSession()
    sent: list[NotificationEmail] = []

    outcomes = _run(session, sent.append)

    assert outcomes == [NotificationOutcome.SENT]
    assert len(sent) == 1
    assert session.rows[0].cadence_point == NotificationCadencePoint.DAY_2


@pytest.mark.parametrize(
    ("label", "finding"),
    [
        ("resolved", _finding(status=FindingStatus.RESOLVED)),
        ("suppressed", _finding(status=FindingStatus.SUPPRESSED)),
        ("acknowledged", _finding(acknowledged_at=datetime(2026, 9, 1, tzinfo=UTC))),
    ],
)
def test_a_finding_already_dealt_with_is_recorded_suppressed_not_emailed(
    stub_lookups: Any, label: str, finding: FindingRow
) -> None:
    """FR-007's three states. Recorded rather than skipped: an admin auditing
    this needs to see the reminder came due and was withheld, which a missing
    row cannot express.

    The acknowledged case is the one worth stating out loud -- an acknowledged
    finding is still `open` (spec 004, FR-017), so a status-only check would
    keep emailing someone who has already said "seen it".
    """
    stub_lookups({NotificationCadencePoint.DAY_2: [finding]})
    session = _RecordingSession()
    sent: list[NotificationEmail] = []

    outcomes = _run(session, sent.append)

    assert outcomes == [NotificationOutcome.SUPPRESSED_FINDING_CLOSED], label
    assert sent == [], label
    assert session.rows[0].recipient_email is None


def test_a_suppressed_reminder_is_never_recorded_as_sent(stub_lookups: Any) -> None:
    stub_lookups(
        {
            NotificationCadencePoint.DAY_2: [_finding(status=FindingStatus.RESOLVED)],
            NotificationCadencePoint.DAY_4: [_finding(status=FindingStatus.RESOLVED)],
        }
    )
    session = _RecordingSession()

    outcomes = _run(session, lambda _e: None)

    assert NotificationOutcome.SENT not in outcomes
    assert len(outcomes) == 2


def test_day_2_is_attempted_before_day_4(stub_lookups: Any) -> None:
    """Cadence order, in case one pass finds a finding due for both."""
    stub_lookups(
        {
            NotificationCadencePoint.DAY_2: [_finding()],
            NotificationCadencePoint.DAY_4: [_finding()],
        }
    )
    session = _RecordingSession()

    _run(session, lambda _e: None)

    assert [row.cadence_point for row in session.rows] == [
        NotificationCadencePoint.DAY_2,
        NotificationCadencePoint.DAY_4,
    ]


def test_an_unresolvable_owner_is_withheld_not_suppressed(stub_lookups: Any) -> None:
    """The two non-sent outcomes mean different things: `withheld_no_owner_email`
    is "nobody to tell", `suppressed_finding_closed` is "nothing to tell them"."""
    stub_lookups({NotificationCadencePoint.DAY_2: [_finding()]}, owner_email=None)
    session = _RecordingSession()

    outcomes = _run(session, lambda _e: None)

    assert outcomes == [NotificationOutcome.WITHHELD_NO_OWNER_EMAIL]


def test_one_failing_reminder_does_not_stop_the_rest(stub_lookups: Any) -> None:
    first, second = _finding(), _finding()
    stub_lookups({NotificationCadencePoint.DAY_2: [first, second]})
    session = _RecordingSession()
    attempts: list[NotificationEmail] = []

    def flaky(email: NotificationEmail) -> None:
        attempts.append(email)
        if len(attempts) == 1:
            raise RuntimeError("SES said no")

    outcomes = _run(session, flaky)

    assert outcomes == [NotificationOutcome.SENT]
    assert len(session.rows) == 1
    assert session.rows[0].finding_id == second.id
