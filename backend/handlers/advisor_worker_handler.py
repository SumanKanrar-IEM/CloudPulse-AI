"""Lambda entrypoint EventBridge Scheduler invokes daily for the coverage
advisor (spec 006, T038b; FR-015, FR-015a, FR-018).

This module owns the one thing the run cannot own itself -- reading the
enrichment registry -- and `app.governance.advisor` owns the rules, the same
boundary the digest and suggester workers keep (Principle V, FR-054).

**No Bedrock wiring here, unlike those two.** The advisor run is deterministic
(see `app.governance.advisor`'s docstring for why), so this worker needs no
agent id, no alias, no VPC endpoint to Bedrock and no cost to cap. It is also
the one spec 006 worker that R-605's VPC-reachability gap does not touch: it
reads the database and writes the database.

The registry is read here rather than in the governance module because
`connectors/aws.py` imports boto3, and `handlers/` is where the connector
boundary check permits that to be reached. Only the *names* cross into the run.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from app.core.db import get_engine, tenant_session
from app.core.logging import logger
from app.governance.advisor import run_advisor
from app.governance.definition_hash import AGENTS_ROOT, hash_definition

DEFINITION_FILES = ("prompts/advisor.md", "definitions/advisor.json")


def advisor_definition_hash() -> str:
    """FR-005/R-608. Hashed even though no model reads the prompt today: the
    definition is the capability's contract, and the run row should say which
    version of it produced these proposals."""
    return hash_definition(*(AGENTS_ROOT / name for name in DEFINITION_FILES))


def known_enrichers() -> set[str]:
    """The enrichment function names present in this build.

    Names only. A gap is proposable when the name its candidate entry points at
    is in this set (R-603 class 2); passing the callables would hand the
    governance layer something it has no reason to hold.
    """
    from connectors.aws import ENRICHMENT_FUNCTIONS

    return set(ENRICHMENT_FUNCTIONS)


def _handle_trigger_daily(_event: dict[str, Any]) -> dict[str, Any]:
    with get_engine().connect() as conn:
        tenant_id = uuid.UUID(
            str(
                conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()
            )
        )

    with tenant_session(tenant_id) as session:
        outcome = run_advisor(
            session,
            known_enrichers=known_enrichers(),
            definition_hash=advisor_definition_hash(),
        )

    result = {
        "agent_run_id": str(outcome.run_id),
        "status": outcome.status.value,
        "proposed": outcome.proposed,
        "advisory": outcome.advisory,
    }
    logger.info("advisor worker completed", extra=result)
    return result


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    action = event.get("action", "trigger_daily")
    if action == "trigger_daily":
        return _handle_trigger_daily(event)
    raise ValueError(f"unknown action: {action!r}")


__all__ = ["advisor_definition_hash", "handler", "known_enrichers"]
