"""Lambda entrypoint EventBridge Scheduler invokes daily for remediation
suggestions (spec 006, T025; FR-004, FR-011, research.md R-605).

This module owns the Bedrock wiring and `app.governance.suggester` owns the
rules -- the same boundary `digest_worker_handler.py` and, before it,
`notification_worker_handler.py` established (Principle V, FR-054).

**One invocation per finding**, which is what makes this capability item-wise
where the digest is whole-artifact: the budget can stop the pass between
findings, so FR-004's "reaching the cap MUST stop" is enforceable here rather
than merely recorded, and FR-004a's retention of already-validated suggestions
has something to retain.

**Runtime limitation, stated plainly**: this worker is VPC-attached with neither
a NAT gateway nor a Bedrock interface endpoint, per research.md R-605 and the
standing R-407 gap. The invocation below cannot reach Bedrock from inside the
VPC until that gap is funded. FR-007a makes that a recorded run failure rather
than an outage -- and everything an earlier pass already wrote stays on the
findings workbench.
"""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine, tenant_session
from app.core.logging import logger
from app.governance.definition_hash import AGENTS_ROOT, hash_definition
from app.governance.suggester import DraftedSuggestion, SuggestionTarget, parse_draft, run_suggester

DEFINITION_FILES = ("prompts/suggester.md", "definitions/suggester.json")


def suggester_definition_hash() -> str:
    """FR-005/R-608: the prompt and the definition together, for the same reason
    the digest hashes both -- a change to the action-group schema changes what
    the agent can read and therefore what it can say."""
    return hash_definition(*(AGENTS_ROOT / name for name in DEFINITION_FILES))


def _prompt(target: SuggestionTarget) -> str:
    """This one finding, and nothing about any other.

    The resource's ARN and type are sent rather than left for the agent to look
    up. FR-011's "specific to that finding's own resource" is the requirement
    most at risk here: an agent given only a rule key writes advice about the
    rule, which reads like a suggestion and is generic to the finding class.
    """
    return json.dumps(
        {
            "finding_id": str(target.finding_id),
            "severity": target.severity,
            "rule_key": target.rule_key,
            "resource": {
                "id": str(target.resource_id) if target.resource_id else None,
                "arn": target.resource_arn,
                "type": target.resource_type,
            },
        }
    )


def _bedrock_invoker(*, agent_id: str, agent_alias_id: str, region: str) -> Any:
    """The `invoke` callable `run_suggester` takes, one call per finding."""
    from connectors.aws import invoke_agent

    def invoke(target: SuggestionTarget) -> DraftedSuggestion:
        result = invoke_agent(
            agent_id=agent_id,
            agent_alias_id=agent_alias_id,
            # One session per finding. A session shared across the pass would
            # carry the previous finding's resource into this one's context,
            # which is the exact way a suggestion stops being specific to its
            # own resource (FR-011).
            session_id=f"suggester-{target.finding_id}",
            prompt=_prompt(target),
            region=region,
        )
        return parse_draft(
            target.finding_id,
            str(result["output_text"]),
            cost_units=Decimal(int(result["input_tokens"]) + int(result["output_tokens"])),
        )

    return invoke


def _handle_trigger_daily(_event: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    # R-612: read at point of use rather than added to the shared `Settings`
    # model, which every other Lambda also constructs.
    agent_id = os.environ.get("CLOUDPULSE_SUGGESTER_AGENT_ID", "")
    agent_alias_id = os.environ.get("CLOUDPULSE_SUGGESTER_AGENT_ALIAS_ID", "")
    if not agent_id or not agent_alias_id:
        raise ValueError(
            "CLOUDPULSE_SUGGESTER_AGENT_ID and CLOUDPULSE_SUGGESTER_AGENT_ALIAS_ID are "
            "required by the suggester worker"
        )

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
        outcome = run_suggester(session, invoke=invoke, definition_hash=suggester_definition_hash())

    result = {
        "agent_run_id": str(outcome.run_id),
        "status": outcome.status.value,
        "written": outcome.written,
        "rejected": outcome.rejected,
        "skipped_admin_seeded": outcome.skipped_admin_seeded,
    }
    logger.info("suggester worker completed", extra=result)
    return result


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_daily")
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["handler", "suggester_definition_hash"]
