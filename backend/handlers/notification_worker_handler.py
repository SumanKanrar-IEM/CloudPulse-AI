"""Lambda entrypoint EventBridge Scheduler invokes daily for owner
notifications (spec 005, T015; FR-004, FR-005, FR-014, research.md R-501).

One daily pass, not three separate triggers: day-0, then the day-2/day-4
reminders, then the escalation flag. They share the action rather than getting
schedules of their own because "what is due today" is one question about one
findings table -- three schedules would race each other for the same rows.

Order matters. Escalation runs last because it keys on the day-4 row the
reminder pass may have just written, so a finding reaching day 4 today is
flagged today rather than a day late.

This module owns the SES client, and `app.governance.notifications` owns the
rules -- the same boundary `ownership_attribution_worker_handler.py`
established (Principle V, FR-054). That is what lets every rule in T012/T013
be tested without mocking a cloud client at all.

**Runtime limitation, stated plainly**: the notification worker is
VPC-attached with neither a NAT gateway nor an SES interface endpoint, per
research.md R-504's declined funding decision. Every rule below is proven by
the mocked tests; the actual `ses:SendEmail` call cannot reach AWS from
inside the VPC until that networking gap is funded.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine, tenant_session
from app.core.logging import logger
from app.governance.notifications import (
    NotificationEmail,
    flag_stale_escalations,
    send_due_day0_notifications,
    send_due_reminders,
)
from app.models.enums import NotificationOutcome


def _ses_sender(region: str) -> Any:
    """boto3 imported lazily, matching `app/core/db.py`'s reason for doing the
    same: a unit test of this module's logic must not need the AWS SDK at
    import time."""
    import boto3

    client = boto3.client("ses", region_name=region)

    def send(email: NotificationEmail) -> None:
        client.send_email(
            Source=email.sender,
            Destination={"ToAddresses": [email.recipient]},
            Message={
                "Subject": {"Data": email.subject},
                "Body": {"Text": {"Data": email.body}},
            },
        )

    return send


def _handle_trigger_daily(_event: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    # Validated here rather than on the Settings model: that one model is
    # shared by every Lambda, and the API/scan/migration functions have no
    # notification configuration at all. A missing value is a real error only
    # at this point of use (see the fields' own comment in config.py).
    if not settings.frontend_url:
        raise ValueError("CLOUDPULSE_FRONTEND_URL is required by the notification worker")
    if not settings.notification_sender_email:
        raise ValueError(
            "CLOUDPULSE_NOTIFICATION_SENDER_EMAIL is required by the notification worker "
            "(FR-014's fixed sending identity)"
        )

    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )

    send = _ses_sender(settings.aws_region)
    sender = settings.notification_sender_email
    frontend_url = settings.frontend_url
    with tenant_session(tenant_id) as session:
        day0 = send_due_day0_notifications(session, send, sender=sender, frontend_url=frontend_url)
        reminders = send_due_reminders(session, send, sender=sender, frontend_url=frontend_url)
        escalated = flag_stale_escalations(session)

    result = {
        "day_0": _counts(day0),
        "reminders": _counts(reminders),
        "newly_escalated": escalated,
    }
    logger.info("notification worker completed", extra=result)
    return result


def _counts(outcomes: list[NotificationOutcome]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.value] = counts.get(outcome.value, 0) + 1
    return counts


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_daily")
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["handler"]
