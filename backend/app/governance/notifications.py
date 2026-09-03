"""Owner notification: the day-0 email, the day-2/day-4 reminders, and the
day-4 escalation flag (spec 005, FR-004-FR-014).

No AWS SDK import here, deliberately. The actual send is passed in as a
callable by `handlers/notification_worker_handler.py`, which owns the SES
client -- the same boundary `ownership_attribution_worker_handler.py`
established and `governance/spend.py` follows (Principle V, FR-054). It also
makes every rule below testable without mocking a cloud client at all.

One `Notification` row is written per attempt regardless of outcome (FR-010:
recorded as unnotifiable, never retried forever or silently dropped), and the
`uq_notification_tenant_finding_cadence` unique constraint is what makes a
re-run idempotent rather than a second email.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import Finding as FindingRow
from app.models.core import Notification as NotificationRow
from app.models.core import Resource as ResourceRow
from app.models.core import ResourceOwner as ResourceOwnerRow
from app.models.core import Rule as RuleRow
from app.models.enums import FindingStatus, NotificationCadencePoint, NotificationOutcome

# How far back a day-0 pass will look for a finding it has never notified on.
#
# Not a calendar-day boundary, on purpose. The worker runs once daily (R-501),
# so a strict "opened today" filter would permanently skip every finding that
# opened *after* the run -- they would be "yesterday" by the next pass and never
# get a day-0 email at all, which is how SC-003 would fail outright rather than
# by its allowed 5% margin. A 48-hour window guarantees one daily pass always
# covers a full day.
#
# The bound's other job is the reason it exists at all rather than being omitted:
# without it, the first deployment would email the owner of every open finding
# specs 003/004 ever created -- a mass unsolicited send, not a backfill.
_DAY0_LOOKBACK = timedelta(hours=48)


@dataclass(frozen=True)
class NotificationEmail:
    """What FR-004/FR-005 require an email to carry. Wording and layout are
    deliberately left to this module (spec.md: templates are out of scope in
    detail); the resource, the violation, and the deep link are not.

    `sender` carries FR-014's fixed, per-environment sending identity on the
    message itself rather than leaving it for the SES client to fill in. That
    is what makes "every email leaves from the one configured identity"
    assertable without mocking a cloud client -- the handler passes the
    configured value straight through, and the transport just uses it.
    """

    sender: str
    recipient: str
    subject: str
    body: str


def deep_link(frontend_url: str, finding_id: uuid.UUID) -> str:
    """FR-005: the finding's own detail view, not the findings list.

    Matches spec 004's existing `/findings/{id}` route shape rather than
    inventing a second URL convention for the same page.
    """
    return f"{frontend_url.rstrip('/')}/findings/{finding_id}"


def build_notification_email(
    *,
    cadence_point: NotificationCadencePoint,
    sender: str,
    recipient: str,
    frontend_url: str,
    finding_id: uuid.UUID,
    resource_arn: str,
    violation: str,
) -> NotificationEmail:
    """FR-004: names the resource and the specific violation. FR-005: deep link.

    A day-2/day-4 reminder (FR-006) says so in its subject and opening line. The
    resource, violation and link are identical to the day-0 email on purpose --
    a reminder that made the recipient go find the original would be a worse
    reminder, and FR-006 asks for a reminder, not a digest.
    """
    link = deep_link(frontend_url, finding_id)
    is_reminder = cadence_point is not NotificationCadencePoint.DAY_0
    opening = (
        "This compliance finding against a resource you own is still open."
        if is_reminder
        else "A compliance finding was opened against a resource you own."
    )
    return NotificationEmail(
        sender=sender,
        recipient=recipient,
        subject=(
            f"{'Reminder: ' if is_reminder else 'Action needed: '}{violation} on {resource_arn}"
        ),
        body=(
            f"{opening}\n\n"
            f"Resource: {resource_arn}\n"
            f"Violation: {violation}\n\n"
            f"Open the finding: {link}\n"
        ),
    )


def due_day0_findings(session: TenantSession, *, now: datetime | None = None) -> list[FindingRow]:
    """Open findings inside the lookback window with no day-0 attempt recorded.

    "Any outcome" is the point of the NOT EXISTS: a finding already recorded as
    `withheld_no_owner_email` is not due again (FR-010 -- recorded, not retried
    forever), exactly like one already `sent`.
    """
    now = now or datetime.now(UTC)
    # Tenant-filtered as well as correlated. A finding's notifications can only
    # belong to that finding's own tenant today, so this is belt-and-braces rather
    # than a live leak -- but FR-030's rule is that a tenant-scoped model is never
    # queried unscoped, and a subquery is still a query.
    already_attempted = select(NotificationRow.finding_id).where(
        NotificationRow.finding_id == FindingRow.id,
        NotificationRow.tenant_id == session.tenant_id,
        NotificationRow.cadence_point == NotificationCadencePoint.DAY_0,
    )
    statement = (
        session.scoped(select(FindingRow), FindingRow)
        .where(
            FindingRow.status == FindingStatus.OPEN,
            FindingRow.opened_at >= now - _DAY0_LOOKBACK,
            ~already_attempted.exists(),
        )
        .order_by(FindingRow.opened_at)
    )
    return list(session.raw.execute(statement).scalars().all())


def _violation_of(session: TenantSession, finding: FindingRow) -> str:
    """The specific violation FR-004 requires the email to name.

    A `budget_overrun` finding has no rule at all (migration 0012's
    `ck_finding_kind_shape`), so this reads the kind rather than assuming
    every finding has a rule to describe.
    """
    if finding.rule_id is None:
        return finding.kind.value.replace("_", " ")
    rule_key = session.raw.execute(
        select(RuleRow.key).where(RuleRow.id == finding.rule_id)
    ).scalar_one_or_none()
    return str(rule_key) if rule_key else finding.kind.value.replace("_", " ")


def _resource_arn_of(session: TenantSession, finding: FindingRow) -> str | None:
    if finding.resource_id is None:
        return None
    return session.raw.execute(
        select(ResourceRow.arn).where(ResourceRow.id == finding.resource_id)
    ).scalar_one_or_none()


def _owner_email_of(session: TenantSession, finding: FindingRow) -> str | None:
    """Spec 003's attribution result, unchanged.

    Reads the `resource_owner` row spec 003's ownership-attribution worker
    already wrote, rather than re-running `resolve_owner_email` here: that
    chain's inputs (the resource's tags and audit-trail principal) belong to
    the attribution pass, and re-deriving them at send time could disagree
    with what the dashboard shows for the same finding.
    """
    if finding.resource_id is None:
        return None
    return session.raw.execute(
        session.scoped(select(ResourceOwnerRow.owner_email), ResourceOwnerRow).where(
            ResourceOwnerRow.resource_id == finding.resource_id
        )
    ).scalar_one_or_none()


def send_due_day0_notifications(
    session: TenantSession,
    send: Callable[[NotificationEmail], None],
    *,
    sender: str,
    frontend_url: str,
    now: datetime | None = None,
) -> list[NotificationOutcome]:
    """Send FR-004's day-0 email for every finding due, recording each attempt.

    One email per finding, never bundled per owner (FR-012) -- which falls out
    of looping per finding rather than grouping by recipient.

    A single finding's failure is logged and recorded, never raised: one bad
    send must not stop the rest of the batch (R-501's stated per-finding
    isolation, in place of SQS retry machinery).
    """
    outcomes: list[NotificationOutcome] = []
    for finding in due_day0_findings(session, now=now):
        outcome = _attempt(
            session,
            finding,
            NotificationCadencePoint.DAY_0,
            send,
            sender=sender,
            frontend_url=frontend_url,
        )
        if outcome is not None:
            outcomes.append(outcome)

    session.raw.flush()
    return outcomes


def _attempt(
    session: TenantSession,
    finding: FindingRow,
    cadence_point: NotificationCadencePoint,
    send: Callable[[NotificationEmail], None],
    *,
    sender: str,
    frontend_url: str,
) -> NotificationOutcome | None:
    """One finding, one cadence point: resolve, send, record.

    `None` means *nothing was recorded* -- the send raised. That is deliberately
    distinct from a recorded withheld outcome: with no row, the next daily pass
    retries the finding, which is right for a transport failure. FR-010's "never
    retried forever" is about an unnotifiable *address*, not a transport error.
    """
    owner_email = _owner_email_of(session, finding)
    if not owner_email:
        logger.info(
            "notification withheld: no owner email",
            extra={"finding_id": str(finding.id), "cadence_point": cadence_point.value},
        )
        return _record(
            session, finding, cadence_point, NotificationOutcome.WITHHELD_NO_OWNER_EMAIL, None
        )

    email = build_notification_email(
        cadence_point=cadence_point,
        sender=sender,
        recipient=owner_email,
        frontend_url=frontend_url,
        finding_id=finding.id,
        resource_arn=_resource_arn_of(session, finding) or str(finding.sda_id or finding.id),
        violation=_violation_of(session, finding),
    )
    try:
        send(email)
    except Exception:
        logger.exception(
            "notification send failed",
            extra={"finding_id": str(finding.id), "cadence_point": cadence_point.value},
        )
        return None

    return _record(session, finding, cadence_point, NotificationOutcome.SENT, owner_email)


# FR-006: both reminders are measured from the day-0 *attempt*, not from when the
# finding opened. Those differ whenever the worker was down or the finding opened
# just after a daily pass, and anchoring on the attempt is what keeps the gap
# between emails the two and four days a recipient is being promised.
_REMINDER_OFFSETS: dict[NotificationCadencePoint, timedelta] = {
    NotificationCadencePoint.DAY_2: timedelta(days=2),
    NotificationCadencePoint.DAY_4: timedelta(days=4),
}


def _day0_attempted_at(session: TenantSession) -> Any:
    """Correlated subquery: when this finding's day-0 attempt was recorded."""
    return (
        select(NotificationRow.attempted_at)
        .where(
            NotificationRow.finding_id == FindingRow.id,
            NotificationRow.tenant_id == session.tenant_id,
            NotificationRow.cadence_point == NotificationCadencePoint.DAY_0,
        )
        .scalar_subquery()
    )


def due_reminder_findings(
    session: TenantSession,
    cadence_point: NotificationCadencePoint,
    *,
    now: datetime | None = None,
) -> list[FindingRow]:
    """Findings whose day-0 attempt is old enough for this reminder, and which
    carry no row at this cadence point yet.

    Deliberately *not* filtered by status here. FR-007's "do not send a reminder
    for a finding already dealt with" is recorded as a `suppressed_finding_closed`
    row by the caller, not as an absence -- an admin auditing this feature needs
    to see that the reminder came due and was withheld, which a missing row
    cannot express (R-501: a row per attempt, sent, withheld or suppressed).
    """
    now = now or datetime.now(UTC)
    already_attempted = select(NotificationRow.finding_id).where(
        NotificationRow.finding_id == FindingRow.id,
        NotificationRow.tenant_id == session.tenant_id,
        NotificationRow.cadence_point == cadence_point,
    )
    statement = (
        session.scoped(select(FindingRow), FindingRow)
        .where(
            _day0_attempted_at(session) <= now - _REMINDER_OFFSETS[cadence_point],
            ~already_attempted.exists(),
        )
        .order_by(FindingRow.opened_at)
    )
    return list(session.raw.execute(statement).scalars().all())


def _still_needs_chasing(finding: FindingRow) -> bool:
    """FR-007's three states, as one predicate.

    `acknowledged_at` is orthogonal to `status` (spec 004, FR-017) -- an
    acknowledged finding is still `open` -- so checking status alone would keep
    emailing someone who has already said "seen it", which is precisely the case
    FR-007 names first.
    """
    return finding.status is FindingStatus.OPEN and finding.acknowledged_at is None


def displayed_escalated_at(finding: FindingRow) -> datetime | None:
    """FR-009's display rule, in the one place both readers and writers agree on.

    An escalated finding stops *displaying* as escalated once it is
    acknowledged, resolved, or suppressed -- the same three states that stop
    FR-007's reminders, which is why this shares `_still_needs_chasing` rather
    than restating the list and risking the two drifting apart. The stored
    `escalated_at` is never cleared; see `models/core.py` for why deriving this
    beats nulling the column in every state transition.
    """
    return finding.escalated_at if _still_needs_chasing(finding) else None


def send_due_reminders(
    session: TenantSession,
    send: Callable[[NotificationEmail], None],
    *,
    sender: str,
    frontend_url: str,
    now: datetime | None = None,
) -> list[NotificationOutcome]:
    """FR-006's day-2 and day-4 reminders, with FR-007's suppression recorded.

    Day-2 runs before day-4 so that a finding which somehow became due for both
    in one pass gets them in cadence order rather than out of it.
    """
    outcomes: list[NotificationOutcome] = []
    for cadence_point in (NotificationCadencePoint.DAY_2, NotificationCadencePoint.DAY_4):
        for finding in due_reminder_findings(session, cadence_point, now=now):
            if not _still_needs_chasing(finding):
                outcomes.append(
                    _record(
                        session,
                        finding,
                        cadence_point,
                        NotificationOutcome.SUPPRESSED_FINDING_CLOSED,
                        None,
                    )
                )
                continue
            outcome = _attempt(
                session,
                finding,
                cadence_point,
                send,
                sender=sender,
                frontend_url=frontend_url,
            )
            if outcome is not None:
                outcomes.append(outcome)

    session.raw.flush()
    return outcomes


def flag_stale_escalations(session: TenantSession, *, now: datetime | None = None) -> int:
    """FR-008: flag a finding still open once its day-4 row has been written.

    A separate pass rather than a side effect of the day-4 send, for two
    reasons: it is idempotent, so re-running it flags nothing twice; and it
    self-heals a finding whose day-4 row was written before this function
    existed. The flag is the *only* automated consequence -- FR-008 is explicit
    that nothing else happens, no further emails and no external escalation.

    Returns how many findings were newly flagged.
    """
    now = now or datetime.now(UTC)
    day4_written = select(NotificationRow.finding_id).where(
        NotificationRow.finding_id == FindingRow.id,
        NotificationRow.tenant_id == session.tenant_id,
        NotificationRow.cadence_point == NotificationCadencePoint.DAY_4,
    )
    statement = session.scoped(select(FindingRow), FindingRow).where(
        FindingRow.status == FindingStatus.OPEN,
        FindingRow.escalated_at.is_(None),
        day4_written.exists(),
    )
    flagged = 0
    for finding in session.raw.execute(statement).scalars().all():
        finding.escalated_at = now
        flagged += 1
    session.raw.flush()
    return flagged


def _record(
    session: TenantSession,
    finding: FindingRow,
    cadence_point: NotificationCadencePoint,
    outcome: NotificationOutcome,
    recipient_email: str | None,
) -> NotificationOutcome:
    """FR-013's auditable trail: one row per attempt, whatever the outcome."""
    session.add(
        NotificationRow(
            finding_id=finding.id,
            cadence_point=cadence_point,
            outcome=outcome,
            recipient_email=recipient_email,
        )
    )
    return outcome


__all__ = [
    "NotificationEmail",
    "build_notification_email",
    "deep_link",
    "displayed_escalated_at",
    "due_day0_findings",
    "due_reminder_findings",
    "flag_stale_escalations",
    "send_due_day0_notifications",
    "send_due_reminders",
]
