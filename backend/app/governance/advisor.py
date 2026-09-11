"""The coverage advisor run (spec 006, T038b; FR-015, FR-015a, FR-018).

**Deterministic, and deliberately so.** This run invokes no model. Detection is
a query over inventory and configuration (`coverage_advisor.detect_gaps`), the
proposal a gap produces is data (`proposed_change`), and the reason an advisory
gap cannot be proposed is a fact about the build, not a judgement. Every column
the API serves is fully determined before a model could be asked anything --
so asking one would spend tokens and open a grounding surface to produce
prose with nowhere to be stored. R-606a's line for the digest applies with more
force here: the platform decides; where there is nothing left to narrate, no
narrator is called.

`agents/definitions/advisor.json` and `agents/prompts/advisor.md` remain the
capability's definition, and `definition_hash` on the run row hashes them --
that is the seam for the day a stored, validated summary per gap is wanted.
Until then the run is recorded with zero cost against the standard cap, so the
run history (`/insights/runs`) shows the advisor ran and what it found.

**The registry arrives as names.** `known_enrichers` is the set of enrichment
function names present in this build, read by the handler from
`connectors/aws.py` where the boundary check permits it, and passed in here.
This module never imports the connector.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.core.db import TenantSession
from app.core.logging import logger
from app.governance.agent_runs import RunBudget, default_cost_cap_units
from app.governance.coverage_advisor import (
    InventoryType,
    accepted_coverage_overrides,
    detect_gaps,
    record_advisory_gaps,
    record_proposals,
)
from app.models.core import AgentRun
from app.models.core import Resource as ResourceRow
from app.models.enums import AgentCapability, AgentRunStatus
from app.scan.coverage import load_coverage_definitions, load_enricher_candidates


@dataclass(frozen=True)
class AdvisorOutcome:
    run_id: uuid.UUID
    status: AgentRunStatus
    proposed: int
    advisory: int


def inventory_types(session: TenantSession) -> list[InventoryType]:
    """Every resource type still present in the tenant (not soft-deleted),
    with the account that has the most of it as the evidence account.

    Grouped per (type, account) so the count is per account, then the largest
    account is kept per type. Either account is correct evidence -- FR-017 makes
    it evidence, not scope -- but "the account with most of them" is the one an
    admin would look at first.
    """
    statement = (
        session.scoped(
            select(
                ResourceRow.resource_type,
                ResourceRow.cloud_account_id,
                func.count(ResourceRow.id),
            ),
            ResourceRow,
        )
        .where(ResourceRow.deleted_at.is_(None))
        .group_by(ResourceRow.resource_type, ResourceRow.cloud_account_id)
    )
    best: dict[str, InventoryType] = {}
    for resource_type, account_id, count in session.raw.execute(statement):
        current = best.get(resource_type)
        if current is None or count > current.resource_count:
            best[resource_type] = InventoryType(
                resource_type=resource_type,
                evidence_account_id=account_id,
                resource_count=int(count),
            )
    return sorted(best.values(), key=lambda t: t.resource_type)


def run_advisor(
    session: TenantSession,
    *,
    known_enrichers: set[str],
    definition_hash: str,
    cap_units: Decimal | None = None,
) -> AdvisorOutcome:
    """One advisor pass. No model call, so no truncation and no rejections.

    Covered types are the shipped file plus this tenant's accepted overrides:
    an accepted proposal must not be raised again as a gap on the run after it
    was accepted, or FR-018's "not re-proposed" would hold for rejections only.
    """
    started_at = datetime.now(UTC)
    budget = RunBudget(cap_units if cap_units is not None else default_cost_cap_units())

    covered = set(load_coverage_definitions(overrides=accepted_coverage_overrides(session)))
    proposable, advisory = detect_gaps(
        inventory_types(session),
        covered_types=covered,
        known_enrichers=known_enrichers,
        enricher_for_type=load_enricher_candidates(),
    )

    run = AgentRun(
        capability=AgentCapability.ADVISOR,
        definition_hash=definition_hash,
        status=AgentRunStatus.SUCCEEDED,
        cost_units=budget.consumed,
        cost_cap_units=budget.cap_units,
        failure_reason=None,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()

    written = record_proposals(session, agent_run_id=run.id, gaps=proposable)
    record_advisory_gaps(session, agent_run_id=run.id, gaps=advisory)

    logger.info(
        "advisor run completed",
        extra={
            "tenant_id": str(session.tenant_id),
            "agent_run_id": str(run.id),
            "proposed": len(written),
            "advisory": len(advisory),
        },
    )
    return AdvisorOutcome(
        run_id=run.id,
        status=AgentRunStatus.SUCCEEDED,
        proposed=len(written),
        advisory=len(advisory),
    )


__all__ = ["AdvisorOutcome", "inventory_types", "run_advisor"]
