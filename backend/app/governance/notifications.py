"""Owner notification: the day-0 email for a newly-opened finding
(spec 005, FR-004, FR-005, FR-010, FR-012, FR-014).

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


def build_day0_email(
    *,
    sender: str,
    recipient: str,
    frontend_url: str,
    finding_id: uuid.UUID,
    resource_arn: str,
    violation: str,
) -> NotificationEmail:
    """FR-004: names the resource and the specific violation. FR-005: deep link."""
    link = deep_link(frontend_url, finding_id)
    return NotificationEmail(
        sender=sender,
        recipient=recipient,
        subject=f"Action needed: {violation} on {resource_arn}",
        body=(
            f"A compliance finding was opened against a resource you own.\n\n"
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
        owner_email = _owner_email_of(session, finding)
        resource_arn = _resource_arn_of(session, finding)

        if not owner_email:
            outcomes.append(
                _record(session, finding, NotificationOutcome.WITHHELD_NO_OWNER_EMAIL, None)
            )
            logger.info(
                "day-0 notification withheld: no owner email",
                extra={"finding_id": str(finding.id)},
            )
            continue

        email = build_day0_email(
            sender=sender,
            recipient=owner_email,
            frontend_url=frontend_url,
            finding_id=finding.id,
            resource_arn=resource_arn or str(finding.sda_id or finding.id),
            violation=_violation_of(session, finding),
        )
        try:
            send(email)
        except Exception:
            # Logged, not raised, and deliberately NOT recorded as an attempt: no
            # Notification row means the next daily pass retries it, which is the
            # right behaviour for a transient send failure. FR-010's "never
            # retried forever" is about an unnotifiable *address*, not a
            # transport error.
            logger.exception(
                "day-0 notification send failed", extra={"finding_id": str(finding.id)}
            )
            continue

        outcomes.append(_record(session, finding, NotificationOutcome.SENT, owner_email))

    session.raw.flush()
    return outcomes


def _record(
    session: TenantSession,
    finding: FindingRow,
    outcome: NotificationOutcome,
    recipient_email: str | None,
) -> NotificationOutcome:
    """FR-013's auditable trail: one row per attempt, whatever the outcome."""
    session.add(
        NotificationRow(
            finding_id=finding.id,
            cadence_point=NotificationCadencePoint.DAY_0,
            outcome=outcome,
            recipient_email=recipient_email,
        )
    )
    return outcome


__all__ = [
    "NotificationEmail",
    "build_day0_email",
    "deep_link",
    "due_day0_findings",
    "send_due_day0_notifications",
]
