"""The remediation suggester: what gets a suggestion, and what happens to a run
that cannot finish (spec 006, T023, T025; FR-004, FR-004a, FR-011-FR-014).

**Item-wise, where the digest is whole-artifact.** Each suggestion stands alone,
so a run that hits its cost cap keeps every one it already validated and the
remainder are picked up by the next run (FR-004a). The digest discards; this
does not. `agent_runs.keeps_partial_output` is the single place that distinction
lives, and it is consulted rather than re-decided here.

**The cap is checked between items, not after the run.** That is the difference
the digest could not exercise: with one invocation per finding, the budget can
actually stop the work, so FR-004's "reaching the cap MUST stop" is enforceable
rather than merely recorded.

Findings are processed in the digest's own priority order (FR-008a's three keys)
so a capped run spends what it has on the findings that matter most. Nothing here
decides urgency independently -- a second ranking would eventually disagree with
the first, and a user reading a digest and a suggestion queue would see two
different accounts of what is urgent.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.core.db import TenantSession
from app.core.logging import logger
from app.governance.agent_runs import (
    RunBudget,
    default_cost_cap_units,
    keeps_partial_output,
    outcome_for,
)
from app.governance.digest import collect_candidates, select_digest_findings
from app.governance.grounding import Reference, Section, validate_output
from app.governance.suggestions import write_ai_suggestion
from app.models.core import AgentRun, GroundingRejection
from app.models.core import Finding as FindingRow
from app.models.core import FindingRemediationSuggestion as SuggestionRow
from app.models.core import Resource as ResourceRow
from app.models.core import Rule as RuleRow
from app.models.enums import AgentCapability, AgentRunStatus, FindingStatus

# No limit on how many findings a run may cover -- FR-011 wants every open
# finding to have a suggestion eventually, and the cost cap is what actually
# bounds a run (spec.md: "FR-011's coverage is reached across runs rather than
# necessarily within one"). A count limit on top would be a second bound with no
# requirement behind it.


@dataclass(frozen=True)
class SuggestionTarget:
    """One open finding needing a suggestion, with the context FR-011 requires.

    The resource is carried here rather than looked up by the agent because
    FR-011's "specific to that finding's own resource" is the requirement most
    at risk: a model given only a rule key writes advice about the rule, which
    reads as a suggestion and is generic to the finding class.
    """

    finding_id: uuid.UUID
    resource_id: uuid.UUID | None
    resource_arn: str | None
    resource_type: str | None
    rule_key: str | None
    severity: str


@dataclass(frozen=True)
class DraftedSuggestion:
    """One suggestion the model produced, before anything has been believed."""

    finding_id: uuid.UUID
    suggestion_text: str
    blast_radius_note: str
    sections: list[Section]
    cost_units: Decimal


@dataclass(frozen=True)
class SuggesterOutcome:
    run_id: uuid.UUID
    status: AgentRunStatus
    written: int
    skipped_admin_seeded: int
    rejected: int


def targets_needing_suggestions(session: TenantSession) -> list[SuggestionTarget]:
    """Open findings with no suggestion yet, in the digest's priority order.

    FR-014 falls out of the `status == OPEN` filter rather than being applied at
    display time: a finding that is no longer open is never given a suggestion
    in the first place, so there is nothing to suppress later.

    A finding that already carries an `admin_seeded` suggestion is excluded here
    as well as refused by the writer. Excluding it saves a model call that
    FR-013 guarantees would be discarded -- the writer's refusal is the
    correctness guarantee, this is the cost one.
    """
    already_suggested = select(SuggestionRow.finding_id).where(
        SuggestionRow.tenant_id == session.tenant_id
    )
    statement = (
        session.scoped(select(FindingRow, ResourceRow, RuleRow), FindingRow)
        .outerjoin(ResourceRow, FindingRow.resource_id == ResourceRow.id)
        .outerjoin(RuleRow, FindingRow.rule_id == RuleRow.id)
        .where(
            FindingRow.status == FindingStatus.OPEN,
            FindingRow.id.not_in(already_suggested),
        )
    )
    rows = session.raw.execute(statement).all()

    by_id = {
        finding.id: SuggestionTarget(
            finding_id=finding.id,
            resource_id=finding.resource_id,
            resource_arn=resource.arn if resource is not None else None,
            resource_type=resource.resource_type if resource is not None else None,
            rule_key=rule.key if rule is not None else None,
            severity=finding.severity.value,
        )
        for finding, resource, rule in rows
    }
    candidates = [c for c in collect_candidates(session) if c.finding_id in by_id]
    ordered = select_digest_findings(candidates, limit=len(candidates))
    return [by_id[c.finding_id] for c in ordered]


def known_references_for(target: SuggestionTarget) -> dict[str, set[str]]:
    """What this one suggestion may cite (FR-001, FR-011).

    Scoped to the finding being worked on, not to everything the tenant owns. A
    suggestion that cited a real ARN belonging to some other finding would
    validate against a tenant-wide vocabulary and still be wrong -- FR-011's
    "specific to that finding's own resource" is exactly the property a wider
    vocabulary would stop catching.
    """
    references: dict[str, set[str]] = {"finding": {str(target.finding_id)}}
    resource_ids = {
        value
        for value in (target.resource_arn, str(target.resource_id) if target.resource_id else None)
        if value
    }
    if resource_ids:
        references["resource"] = resource_ids
    return references


def parse_draft(
    finding_id: uuid.UUID, output_text: str, *, cost_units: Decimal = Decimal("0")
) -> DraftedSuggestion:
    """The suggester prompt's output contract, parsed fail-closed.

    Same discipline as the digest's `parse_sections`: anything malformed raises
    rather than degrading to a best-effort read, because a partially-parsed
    suggestion would reach the validator with the fabricated part already
    dropped.
    """
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"suggestion output was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("suggestion output must be a JSON object")

    try:
        suggestion_text = str(payload["suggestion"]).strip()
        blast_radius_note = str(payload["blastRadius"]).strip()
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed suggestion: {exc}") from exc
    if not suggestion_text or not blast_radius_note:
        # An empty blast-radius note is not a suggestion with nothing to warn
        # about; it is a suggestion that skipped the half FR-011 asks for.
        raise ValueError("a suggestion needs both a fix and a blast-radius note")

    references = payload.get("references", [])
    if not isinstance(references, list):
        raise ValueError("references must be a list")

    try:
        parsed_references = [
            Reference(kind=str(r["kind"]), id=str(r["id"]), label=str(r.get("label", "")))
            for r in references
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed reference: {exc}") from exc

    # The prose is validated as one section covering both halves. Splitting them
    # would let a fabricated ARN in the blast-radius note pass while the fix
    # itself was clean, and the note is the half a reader acts on most cautiously.
    return DraftedSuggestion(
        finding_id=finding_id,
        suggestion_text=suggestion_text,
        blast_radius_note=blast_radius_note,
        sections=[
            Section(
                heading="suggestion",
                body=f"{suggestion_text}\n\n{blast_radius_note}",
                references=parsed_references,
            )
        ],
        cost_units=cost_units,
    )


def _record_run(
    session: TenantSession,
    *,
    definition_hash: str,
    status: AgentRunStatus,
    failure_reason: str | None,
    budget: RunBudget,
    started_at: datetime,
) -> AgentRun:
    run = AgentRun(
        capability=AgentCapability.SUGGESTER,
        definition_hash=definition_hash,
        status=status,
        cost_units=budget.consumed,
        cost_cap_units=budget.cap_units,
        failure_reason=failure_reason,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    return run


def run_suggester(
    session: TenantSession,
    *,
    invoke: Callable[[SuggestionTarget], DraftedSuggestion],
    definition_hash: str,
    cap_units: Decimal | None = None,
) -> SuggesterOutcome:
    """One suggester pass (FR-004, FR-004a, FR-011-FR-014).

    Writes exactly one `agent_run` row covering the whole pass, not one per
    finding. A run is a unit of budget, and the budget is what FR-004 caps --
    one row per finding would make "did this run hit its cap?" unanswerable
    without summing.

    Rejections are recorded per suggestion and do not stop the pass. One model
    producing one bad ARN is not a reason to withhold suggestions for every other
    finding, and the run's own status stays `succeeded`: the pass did what it was
    asked to, and `grounding_rejection` is where the refusals are counted
    (FR-006).
    """
    started_at = datetime.now(UTC)
    budget = RunBudget(cap_units if cap_units is not None else default_cost_cap_units())

    written = 0
    skipped_admin_seeded = 0
    rejections: list[tuple[str, object]] = []
    error: str | None = None
    completed = True

    for target in targets_needing_suggestions(session):
        if budget.exhausted:
            # FR-004: stop at the cap and say so. Checked before the call, not
            # after -- charging for work the budget had already forbidden would
            # make the cap a report rather than a limit.
            completed = False
            break
        try:
            draft = invoke(target)
        except (RuntimeError, ValueError) as exc:
            # FR-007a: an unreachable model ends the pass, because the next
            # finding would fail identically. Everything already written stays
            # written -- that is FR-004a's item-wise half, and it applies to a
            # failure for the same reason it applies to a cap.
            error = str(exc)
            completed = False
            break

        budget.charge(draft.cost_units)

        verdict = validate_output(
            draft.sections,
            known_references=known_references_for(target),
            known_figures=set(),
        )
        if not verdict.ok:
            rejections.append((str(verdict.rejected_reference), verdict.reference_kind))
            continue

        if write_ai_suggestion(
            session, target.finding_id, draft.suggestion_text, draft.blast_radius_note
        ):
            written += 1
        else:
            # FR-013: an admin seeded this finding between the query and the
            # write. Not an error and not a rejection -- the human's suggestion
            # is the one that should stand.
            skipped_admin_seeded += 1

    status, failure_reason = outcome_for(budget, completed=completed, error=error)
    if not keeps_partial_output(AgentCapability.SUGGESTER):  # pragma: no cover - defensive
        raise AssertionError("the suggester is item-wise; FR-004a's retention must apply to it")

    run = _record_run(
        session,
        definition_hash=definition_hash,
        status=status,
        failure_reason=failure_reason,
        budget=budget,
        started_at=started_at,
    )
    for reference, kind in rejections:
        session.add(
            GroundingRejection(
                agent_run_id=run.id,
                rejected_reference=reference,
                reference_kind=kind,
            )
        )
    session.flush()

    logger.info(
        "suggester run completed",
        extra={
            "tenant_id": str(session.tenant_id),
            "agent_run_id": str(run.id),
            "status": str(status),
            "written": written,
            "rejected": len(rejections),
            "skipped_admin_seeded": skipped_admin_seeded,
        },
    )
    return SuggesterOutcome(
        run_id=run.id,
        status=status,
        written=written,
        skipped_admin_seeded=skipped_admin_seeded,
        rejected=len(rejections),
    )


__all__ = [
    "DraftedSuggestion",
    "SuggesterOutcome",
    "SuggestionTarget",
    "known_references_for",
    "parse_draft",
    "run_suggester",
    "targets_needing_suggestions",
]
