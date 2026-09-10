"""Coverage gap detection and the proposal lifecycle (spec 006, T034; FR-015,
FR-015a, FR-016, FR-017, FR-018, research.md R-603).

**The split this module exists to enforce.** A gap is only proposable when
accepting it could actually take effect as configuration:

* **A rule extension** is genuinely code-free. `rule.definition` is JSONB and
  spec 003's engine evaluates it as data, so an accepted proposal changes
  behaviour on the next scan with no deployment.
* **Enabling an existing enricher** is code-free for the same reason:
  `coverage_definitions.json` maps a resource type to an enrichment function
  *name*, and the function already exists.
* **A resource type nobody has written an enricher for is not proposable at
  all.** Accepting it could not take effect without a code change, so FR-015a
  makes it read-only advisory content. `CoverageProposalKind` has exactly two
  members for this reason -- there is no third value to tempt a writer, and the
  absence is the enforcement.

An acceptance control that could not take effect would misrepresent what the
platform can do, which the spec judges worse than not surfacing the gap at all.

**The available enrichers are passed in, not imported.** The registry lives in
`connectors/aws.py` behind the connector boundary (Principle V); importing it
here would drag provider-adjacent detail into the governance core. Taking a set
of names keeps this module pure and provable without a cloud client -- the same
shape `scan/coverage.py::resolve_enrichment_function` already uses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import CoverageAdvisoryGap as AdvisoryRow
from app.models.core import CoverageProposal as ProposalRow
from app.models.enums import CoverageProposalKind, ProposalReviewState


@dataclass(frozen=True)
class InventoryType:
    """One resource type observed in a tenant's inventory, with the account that
    revealed it (FR-017's evidence, not its scope)."""

    resource_type: str
    evidence_account_id: uuid.UUID
    resource_count: int


@dataclass(frozen=True)
class ProposableGap:
    """A gap an admin could accept, because accepting it would take effect."""

    resource_type: str
    kind: CoverageProposalKind
    evidence_account_id: uuid.UUID
    proposed_change: dict[str, Any]


@dataclass(frozen=True)
class AdvisoryGap:
    """A gap that needs code (FR-015a). Never a proposal, never acceptable.

    Deliberately a different type from `ProposableGap` rather than a flag on it.
    A boolean would let one careless `if` write an advisory gap into
    `coverage_proposal`; two types make that a type error instead of a bug.
    """

    resource_type: str
    evidence_account_id: uuid.UUID
    reason: str


def detect_gaps(
    inventory: list[InventoryType],
    *,
    covered_types: set[str],
    known_enrichers: set[str],
    enricher_for_type: dict[str, str],
) -> tuple[list[ProposableGap], list[AdvisoryGap]]:
    """FR-015/FR-015a: split observed types into what can be closed as
    configuration and what cannot.

    `enricher_for_type` is the platform's knowledge of which existing enrichment
    function would suit a type that is not yet mapped to one -- the thing that
    makes ENABLE_EXISTING_ENRICHER possible. A type absent from it has no
    candidate, so it is advisory whatever else is true.

    Returns both lists rather than raising on the advisory ones: FR-015a wants
    them surfaced, just not as something to accept.
    """
    proposable: list[ProposableGap] = []
    advisory: list[AdvisoryGap] = []

    for item in inventory:
        if item.resource_type in covered_types:
            continue

        candidate = enricher_for_type.get(item.resource_type)
        if candidate is not None and candidate in known_enrichers:
            proposable.append(
                ProposableGap(
                    resource_type=item.resource_type,
                    kind=CoverageProposalKind.ENABLE_EXISTING_ENRICHER,
                    evidence_account_id=item.evidence_account_id,
                    proposed_change={
                        "resource_type": item.resource_type,
                        "enrichment_function": candidate,
                    },
                )
            )
            continue

        # Named candidate that does not exist is the dangerous case: it looks
        # closeable and is not. Called out separately so the reason a reader sees
        # is the true one.
        reason = (
            f"no enrichment routine exists for {item.resource_type}; "
            "closing this gap needs a code change, so it cannot be accepted as configuration"
        )
        if candidate is not None:
            reason = (
                f"the enrichment routine {candidate!r} named for {item.resource_type} "
                "is not present in this build; accepting would not take effect"
            )
        advisory.append(
            AdvisoryGap(
                resource_type=item.resource_type,
                evidence_account_id=item.evidence_account_id,
                reason=reason,
            )
        )

    return proposable, advisory


def already_decided_types(session: TenantSession) -> set[str]:
    """Resource types with a proposal that has already been decided.

    FR-018: a rejected proposal must not be re-proposed on the next run. Accepted
    ones are excluded too -- re-proposing something already applied would be
    noise, and the type will be covered by then anyway.
    """
    statement = session.scoped(select(ProposalRow.resource_type), ProposalRow).where(
        ProposalRow.review_state != ProposalReviewState.PENDING
    )
    return set(session.raw.execute(statement).scalars())


def record_proposals(
    session: TenantSession, *, agent_run_id: uuid.UUID, gaps: list[ProposableGap]
) -> list[uuid.UUID]:
    """Write one pending proposal per gap, skipping anything already decided.

    Pending proposals for the same type are also skipped: a daily advisor run
    must not stack duplicates while an admin takes a week to decide.
    """
    decided = already_decided_types(session)
    pending = set(
        session.raw.execute(
            session.scoped(select(ProposalRow.resource_type), ProposalRow).where(
                ProposalRow.review_state == ProposalReviewState.PENDING
            )
        ).scalars()
    )

    written: list[uuid.UUID] = []
    for gap in gaps:
        if gap.resource_type in decided or gap.resource_type in pending:
            continue
        row = ProposalRow(
            agent_run_id=agent_run_id,
            proposal_kind=gap.kind,
            resource_type=gap.resource_type,
            evidence_account_id=gap.evidence_account_id,
            proposed_change=gap.proposed_change,
            review_state=ProposalReviewState.PENDING,
        )
        session.add(row)
        session.flush()
        written.append(row.id)
        pending.add(gap.resource_type)

    return written


def record_advisory_gaps(
    session: TenantSession, *, agent_run_id: uuid.UUID, gaps: list[AdvisoryGap]
) -> None:
    """Replace the tenant's advisory set with what this run observed (FR-015a).

    A rewrite rather than an append. These rows carry a claim -- "no enrichment
    routine exists for this type" -- and a release that adds the routine makes
    the claim false. Since the run that would notice is the one running now,
    deleting what it no longer observes is what keeps the surface honest;
    keeping history here would only preserve statements the platform has since
    contradicted.
    """
    observed = {gap.resource_type for gap in gaps}
    existing = {
        row.resource_type: row
        for row in session.raw.execute(
            session.scoped(select(AdvisoryRow), AdvisoryRow)
        ).scalars()
    }

    for resource_type, row in existing.items():
        if resource_type not in observed:
            session.raw.delete(row)

    now = datetime.now(UTC)
    for gap in gaps:
        row = existing.get(gap.resource_type)
        if row is None:
            session.add(
                AdvisoryRow(
                    agent_run_id=agent_run_id,
                    resource_type=gap.resource_type,
                    evidence_account_id=gap.evidence_account_id,
                    reason=gap.reason,
                    observed_at=now,
                )
            )
            continue
        row.agent_run_id = agent_run_id
        row.evidence_account_id = gap.evidence_account_id
        row.reason = gap.reason
        row.observed_at = now

    session.flush()


def decide(
    session: TenantSession,
    proposal_id: uuid.UUID,
    *,
    accept: bool,
    decided_by: uuid.UUID,
) -> ProposalRow | None:
    """FR-016/FR-018: an explicit admin decision, recorded with who made it.

    Returns None when the proposal does not exist for this tenant. A decision on
    an already-decided proposal is refused rather than silently re-applied --
    a second accept would move `applied_at` and make the audit trail lie about
    when the change took effect.
    """
    row = session.raw.execute(
        session.scoped(select(ProposalRow), ProposalRow).where(ProposalRow.id == proposal_id)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.review_state is not ProposalReviewState.PENDING:
        raise ValueError(f"proposal {proposal_id} is already {row.review_state.value}")

    row.review_state = ProposalReviewState.ACCEPTED if accept else ProposalReviewState.REJECTED
    row.decided_by = decided_by
    row.decided_at = datetime.now(UTC)
    # `applied_at` is set here because acceptance IS the application: the change
    # is configuration, and the next scan reads it. There is no deployment step
    # in between to wait for (FR-017).
    row.applied_at = datetime.now(UTC) if accept else None
    session.flush()
    decided: ProposalRow = row

    logger.info(
        "coverage proposal decided",
        extra={
            "tenant_id": str(session.tenant_id),
            "proposal_id": str(proposal_id),
            "review_state": decided.review_state.value,
        },
    )
    return decided


def accepted_coverage_overrides(session: TenantSession) -> dict[str, str]:
    """Accepted enricher mappings, tenant-wide (FR-017).

    Returned as data for the scan path to merge over `coverage_definitions.json`
    rather than written back into that file. The file ships in the deployment
    package and is the same for every tenant; an accepted proposal is one
    tenant's decision, so merging at read time is what keeps FR-017's
    "tenant-wide" from meaning "everyone's".
    """
    statement = session.scoped(select(ProposalRow), ProposalRow).where(
        ProposalRow.review_state == ProposalReviewState.ACCEPTED,
        ProposalRow.proposal_kind == CoverageProposalKind.ENABLE_EXISTING_ENRICHER,
    )
    return {
        row.resource_type: str(row.proposed_change["enrichment_function"])
        for row in session.raw.execute(statement).scalars()
        if "enrichment_function" in row.proposed_change
    }


__all__ = [
    "AdvisoryGap",
    "InventoryType",
    "ProposableGap",
    "accepted_coverage_overrides",
    "already_decided_types",
    "decide",
    "detect_gaps",
    "record_advisory_gaps",
    "record_proposals",
]
