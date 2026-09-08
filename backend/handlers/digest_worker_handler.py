"""Lambda entrypoint EventBridge Scheduler invokes daily for the insight digest
(spec 006, T017; FR-008, FR-009, FR-010, research.md R-601, R-605).

This module owns the Bedrock wiring and `app.governance.digest` owns the rules
-- the same boundary `notification_worker_handler.py` established for SES
(Principle V, FR-054). That split is what lets every branch of the pipeline be
proven with no cloud client at all, which is the whole reason SC-001 is
assertable while the model is unreachable.

The digest covers **yesterday**, not today. A run firing at 06:00 that
summarised the current date would report a few hours of spend against a full
previous day and call the difference a collapse (FR-008b's day-over-day
comparison). Yesterday is the most recent day that is actually complete.

**Runtime limitation, stated plainly**: this worker is VPC-attached with
neither a NAT gateway nor a Bedrock interface endpoint, per research.md R-605
and the standing R-407 gap. The invocation below cannot reach Bedrock from
inside the VPC until that networking gap is funded. That is a specified,
recorded state rather than an outage -- the run is written `failed` with its
reason and the surfaces serve the last valid digest (FR-007a).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine, tenant_session
from app.core.logging import logger
from app.governance.definition_hash import AGENTS_ROOT, hash_definition
from app.governance.digest import (
    AgentDraft,
    DigestCandidate,
    DigestInputs,
    build_inputs,
    parse_sections,
    run_digest,
)

DEFINITION_FILES = ("prompts/digest.md", "definitions/digest.json")


def digest_definition_hash() -> str:
    """FR-005/R-608: the prompt and the definition together.

    Both, not just the prompt. A change to the action-group schema changes what
    the agent can read and therefore what it can say, and a hash that moved only
    on prompt edits would leave that change unexplainable.
    """
    return hash_definition(*(AGENTS_ROOT / name for name in DEFINITION_FILES))


def _prompt(inputs: DigestInputs, selected: list[DigestCandidate]) -> str:
    """The run's own inputs, as JSON beside the instruction file.

    Only the selected findings and the platform's own figures are sent. Sending
    the full finding set would cost tokens for rows the agent must not rank
    (FR-008a) and would enlarge the input the run is billed on -- R-606's point
    that the lever on model cost is how much governance data each prompt
    carries, not how often runs fire.
    """
    return json.dumps(
        {
            "period_date": inputs.period_date.isoformat(),
            "findings": [
                {
                    "id": str(c.finding_id),
                    "severity": c.severity.value,
                    "escalated": c.escalated,
                    "opened_at": c.opened_at.isoformat(),
                    "kind": c.label,
                }
                for c in selected
            ],
            "figures": {
                "previous_spend_usd": str(inputs.previous_spend_usd),
                "current_spend_usd": str(inputs.current_spend_usd),
                "previous_compliance_percent": str(inputs.previous_compliance),
                "current_compliance_percent": str(inputs.current_compliance),
            },
        }
    )


def _bedrock_invoker(*, agent_id: str, agent_alias_id: str, region: str) -> Any:
    """The `invoke` callable `run_digest` takes.

    Built here rather than imported there so the pipeline never depends on the
    Bedrock client existing. `connectors.aws.invoke_agent` raises rather than
    returning a partial; `run_digest` absorbs that into a recorded failure.
    """
    from connectors.aws import invoke_agent

    def invoke(inputs: DigestInputs, selected: list[DigestCandidate]) -> AgentDraft:
        result = invoke_agent(
            agent_id=agent_id,
            agent_alias_id=agent_alias_id,
            # One session per period, so a retry of the same day reuses it and
            # two different days never share agent memory.
            session_id=f"digest-{inputs.period_date.isoformat()}",
            prompt=_prompt(inputs, selected),
            region=region,
        )
        # `completed=True` because the connector has no truncation signal to
        # report: Bedrock's event stream ends the same way whether the model
        # finished or hit its own output limit. A digest cut off mid-JSON fails
        # to parse and is discarded whole, which is the outcome FR-004a
        # prescribes for a whole-artifact capability anyway -- so the missing
        # signal costs nothing here. It would matter for an item-wise
        # capability, and T021's suggester must not inherit this assumption.
        return AgentDraft(
            sections=parse_sections(str(result["output_text"])),
            cost_units=Decimal(int(result["input_tokens"]) + int(result["output_tokens"])),
            completed=True,
        )

    return invoke


def _handle_trigger_daily(event: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    # R-612: read at point of use rather than added to the shared `Settings`
    # model, which every other Lambda also constructs and none of the others
    # has a digest agent to name.
    agent_id = os.environ.get("CLOUDPULSE_DIGEST_AGENT_ID", "")
    agent_alias_id = os.environ.get("CLOUDPULSE_DIGEST_AGENT_ALIAS_ID", "")
    if not agent_id or not agent_alias_id:
        raise ValueError(
            "CLOUDPULSE_DIGEST_AGENT_ID and CLOUDPULSE_DIGEST_AGENT_ALIAS_ID are required "
            "by the digest worker"
        )

    period_date = _period_date(event)

    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )

    invoke = _bedrock_invoker(
        agent_id=agent_id, agent_alias_id=agent_alias_id, region=settings.aws_region
    )
    with tenant_session(tenant_id) as session:
        outcome = run_digest(
            session,
            inputs=build_inputs(session, period_date),
            invoke=invoke,
            definition_hash=digest_definition_hash(),
        )

    result = {
        "period_date": period_date.isoformat(),
        "agent_run_id": str(outcome.run_id),
        "status": outcome.status.value,
        "digest_id": str(outcome.digest_id) if outcome.digest_id else None,
        "is_empty": outcome.is_empty,
    }
    logger.info("digest worker completed", extra=result)
    return result


def _period_date(event: dict[str, Any]) -> date:
    """Yesterday, unless the event names a day.

    The override exists for the backfill and live-verification passes (T030),
    and is deliberately explicit -- a worker that silently accepted a date from
    its trigger would make "which day is this digest for?" depend on scheduler
    configuration nobody reads.
    """
    raw = event.get("period_date")
    if raw:
        return date.fromisoformat(str(raw))
    return (datetime.now(UTC) - timedelta(days=1)).date()


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_daily")
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["digest_definition_hash", "handler"]
