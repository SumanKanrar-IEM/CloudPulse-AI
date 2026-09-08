"""The insight digest: what it covers, and how it is assembled (spec 006, T013,
T015; FR-008, FR-008a, FR-008b, FR-009, FR-010, research.md R-606a, R-610).

**The platform selects; the agent explains.** Finding selection is a
deterministic query performed before the agent is invoked (FR-008a). Ranking is
a scoring decision and Principle IV reserves scoring for the deterministic core.
It is also the only version that is verifiable: the grounding validator can
confirm a finding exists, but has no way to confirm that a model-chosen finding
was genuinely the most urgent. A claim nobody can check is not a requirement.

Notability is decided here too (FR-008b), against configured thresholds rather
than by the agent. Leaving "notable" to the model would make FR-010's
nothing-notable branch unverifiable -- the validator can confirm a figure is
real, but not that omitting it was correct.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import TenantSession
from app.core.logging import logger
from app.governance.agent_runs import RunBudget, default_cost_cap_units, outcome_for
from app.governance.grounding import Figure, Reference, Section, validate_output
from app.governance.scoring import tenant_compliance_score
from app.models.core import AgentRun, GroundingRejection, InsightDigest
from app.models.core import Finding as FindingRow
from app.models.core import Resource as ResourceRow
from app.models.core import SpendRecord as SpendRecordRow
from app.models.enums import AgentCapability, AgentRunStatus, FindingSeverity, FindingStatus

# A digest naming forty findings answers "what should I care about today?" no
# better than the findings list it exists to summarise.
DIGEST_FINDING_LIMIT = 5

# FR-008a's first key. Declared explicitly because the enum's declaration order
# is not its urgency order, and sorting the string values would rank `low` above
# `medium` and `critical` below both.
_SEVERITY_RANK: dict[FindingSeverity, int] = {
    FindingSeverity.CRITICAL: 4,
    FindingSeverity.HIGH: 3,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 1,
}

# FR-008b, read from the environment at point of use per R-612 -- not added to
# the shared `Settings` model, which spec 005 tried and paid for in its T029a.
_SPEND_PERCENT_ENV = "CLOUDPULSE_DIGEST_SPEND_NOTABLE_PERCENT"
_SPEND_ABSOLUTE_ENV = "CLOUDPULSE_DIGEST_SPEND_NOTABLE_USD"
_COMPLIANCE_POINTS_ENV = "CLOUDPULSE_DIGEST_COMPLIANCE_NOTABLE_POINTS"

_FALLBACK_SPEND_PERCENT = Decimal("20")
_FALLBACK_SPEND_ABSOLUTE = Decimal("50")
_FALLBACK_COMPLIANCE_POINTS = Decimal("5")


@dataclass(frozen=True)
class DigestCandidate:
    """One finding eligible for the digest, reduced to what ranking needs.

    A plain value rather than an ORM row so selection stays pure and provable
    without a database -- FR-008a's reproducibility clause is the requirement,
    and a function that needed a session to demonstrate it would be a weaker
    proof.
    """

    finding_id: uuid.UUID
    severity: FindingSeverity
    escalated: bool
    opened_at: datetime
    label: str


@dataclass(frozen=True)
class NotabilityThresholds:
    """FR-008b's configured bars for "notable"."""

    spend_percent: Decimal
    spend_absolute_usd: Decimal
    compliance_points: Decimal


def select_digest_findings(
    candidates: list[DigestCandidate], *, limit: int = DIGEST_FINDING_LIMIT
) -> list[DigestCandidate]:
    """FR-008a: severity descending, then escalated first, then oldest first.

    `sorted` rather than `list.sort`: the caller may still need its own ordering,
    and sorting in place would be an invisible side effect on a shared list.
    """
    return sorted(
        candidates,
        key=lambda c: (-_SEVERITY_RANK[c.severity], not c.escalated, c.opened_at),
    )[:limit]


def _decimal_from_env(name: str, fallback: Decimal) -> Decimal:
    """R-612: a malformed or non-positive threshold falls back rather than
    raising. A bad configuration value must not take a scheduled digest run
    down, and a conservative default is a better answer than a crash."""
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.warning(
            "ignoring an unparseable digest threshold; using the fallback",
            extra={"env_var": name, "fallback": str(fallback)},
        )
        return fallback
    if value <= 0:
        logger.warning(
            "ignoring a non-positive digest threshold; using the fallback",
            extra={"env_var": name, "fallback": str(fallback)},
        )
        return fallback
    return value


def notability_thresholds() -> NotabilityThresholds:
    """FR-008b's thresholds, as configuration rather than literals."""
    return NotabilityThresholds(
        spend_percent=_decimal_from_env(_SPEND_PERCENT_ENV, _FALLBACK_SPEND_PERCENT),
        spend_absolute_usd=_decimal_from_env(_SPEND_ABSOLUTE_ENV, _FALLBACK_SPEND_ABSOLUTE),
        compliance_points=_decimal_from_env(_COMPLIANCE_POINTS_ENV, _FALLBACK_COMPLIANCE_POINTS),
    )


def is_spend_change_notable(
    previous: Decimal, current: Decimal, thresholds: NotabilityThresholds
) -> bool:
    """FR-008b: notable when the move clears **either** bar.

    Either, not both, deliberately. A percentage alone calls every jitter on a
    tiny project notable; an absolute alone stays silent on a large project
    moving a meaningful fraction of its spend. Each covers the other's blind
    spot, so the first to trigger wins.
    """
    delta = abs(current - previous)
    if delta >= thresholds.spend_absolute_usd:
        return True
    if previous <= 0:
        # No baseline to take a percentage of. A project's first spend is
        # notable only if it clears the absolute bar, which the check above
        # already decided -- treating it as an infinite percentage increase
        # would make every new project's first day notable.
        return False
    return (delta / previous) * Decimal("100") >= thresholds.spend_percent


def is_compliance_move_notable(
    previous: Decimal, current: Decimal, thresholds: NotabilityThresholds
) -> bool:
    """FR-008b: a compliance move of at least the configured points, in either
    direction. A score that improved sharply is as worth reporting as one that
    fell -- a digest that only ever delivers bad news gets read as noise."""
    return abs(current - previous) >= thresholds.compliance_points


def collect_candidates(session: TenantSession) -> list[DigestCandidate]:
    """Every open finding this tenant holds, reduced to what ranking needs.

    Deliberately unranked and unlimited: `select_digest_findings` applies
    FR-008a's order and FR-008's limit. Splitting the query from the ranking is
    what lets the ranking be proved without a database.

    `label` is the finding kind, not a rule name. The agent receives the finding
    id as a reference and reads the detail through its action group (FR-003,
    R-602); a label joined in here would be a second source of the same text,
    and the two would eventually disagree.
    """
    stmt = session.scoped(select(FindingRow), FindingRow).where(
        FindingRow.status == FindingStatus.OPEN
    )
    return [
        DigestCandidate(
            finding_id=row.id,
            severity=row.severity,
            escalated=row.escalated_at is not None,
            opened_at=row.opened_at,
            label=row.kind.value,
        )
        for row in session.raw.execute(stmt).scalars()
    ]


@dataclass(frozen=True)
class DigestInputs:
    """Everything the platform computed before the agent was consulted.

    Every quantity here is a figure the agent is permitted to state, and nothing
    else is (FR-001a). Passing them in rather than querying them inside the run
    keeps the notability decision and the grounding vocabulary the same object,
    so a figure can never be offered to the model without also being declared to
    the validator.
    """

    period_date: date
    candidates: list[DigestCandidate]
    previous_spend_usd: Decimal
    current_spend_usd: Decimal
    previous_compliance: Decimal
    current_compliance: Decimal
    known_references: dict[str, set[str]]


@dataclass(frozen=True)
class AgentDraft:
    """What one invocation produced, before anything has been believed.

    `completed` is the model's own report that it finished. A draft that arrived
    but did not complete is a truncation, and for the digest that means the
    output is discarded whole (FR-004a) -- half a summary implies that nothing
    else was notable, which is a claim the run never established.
    """

    sections: list[Section]
    cost_units: Decimal
    completed: bool = True


@dataclass(frozen=True)
class DigestOutcome:
    """What a run did, in the terms the surfaces and the tests both need."""

    run_id: uuid.UUID
    status: AgentRunStatus
    digest_id: uuid.UUID | None
    is_empty: bool
    rejected_reference: str | None = None


def spend_totals(session: TenantSession, period_date: date) -> tuple[Decimal, Decimal]:
    """FR-008b's day-over-day pair: (previous day, this day).

    Gap rows are excluded rather than counted as zero. A day ingestion never
    produced is not a day that cost nothing, and treating it as one would report
    a total collapse in spend as a notable saving (spec 005's FR-002a).
    """

    def _total(day: date) -> Decimal:
        stmt = session.scoped(
            select(func.coalesce(func.sum(SpendRecordRow.amount_usd), 0)), SpendRecordRow
        ).where(SpendRecordRow.spend_date == day, SpendRecordRow.is_gap.is_(False))
        return Decimal(str(session.raw.execute(stmt).scalar_one()))

    return _total(period_date - timedelta(days=1)), _total(period_date)


def last_recorded_compliance(session: TenantSession, before: date) -> Decimal | None:
    """The compliance score the most recent earlier digest recorded.

    `None` on the first run ever, which the caller reads as "no movement" rather
    than as a fall from zero -- a brand-new tenant's first digest announcing a
    catastrophic compliance drop would be both wrong and the first thing anyone
    saw.
    """
    stmt = (
        session.scoped(select(InsightDigest.content), InsightDigest)
        .where(InsightDigest.period_date < before)
        .order_by(InsightDigest.period_date.desc())
        .limit(1)
    )
    content = session.raw.execute(stmt).scalar_one_or_none()
    if not content:
        return None
    raw = content.get("platform_figures", {}).get("compliance")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def build_inputs(session: TenantSession, period_date: date) -> DigestInputs:
    """Everything the platform computes before the agent is consulted.

    `known_references` is built from the *selected* findings only. Handing the
    validator every identifier the tenant owns would let the agent cite a
    resource it was never shown and have the citation resolve -- technically
    grounded, and still an answer to a question nobody asked.
    """
    candidates = collect_candidates(session)
    previous_spend, current_spend = spend_totals(session, period_date)
    _, _, score = tenant_compliance_score(session)
    current_compliance = Decimal(str(score)) * Decimal("100")
    previous_compliance = last_recorded_compliance(session, period_date)

    selected = select_digest_findings(candidates)
    finding_ids = [c.finding_id for c in selected]
    resources = (
        session.raw.execute(
            session.scoped(select(ResourceRow), ResourceRow).where(
                ResourceRow.id.in_(
                    select(FindingRow.resource_id).where(FindingRow.id.in_(finding_ids))
                )
            )
        )
        .scalars()
        .all()
        if finding_ids
        else []
    )
    known_references = {
        "finding": {str(fid) for fid in finding_ids},
        "resource": {r.arn for r in resources},
        "sda": {str(r.sda_id) for r in resources if r.sda_id is not None},
    }

    return DigestInputs(
        period_date=period_date,
        candidates=candidates,
        previous_spend_usd=previous_spend,
        current_spend_usd=current_spend,
        previous_compliance=(
            current_compliance if previous_compliance is None else previous_compliance
        ),
        current_compliance=current_compliance,
        known_references=known_references,
    )


def known_figures(inputs: DigestInputs) -> set[Decimal]:
    """The quantities the platform computed for this run (FR-001a).

    Deltas are included because a digest that reports a change without naming
    its size is not worth reading, and a delta the agent had to derive itself
    would be rejected as unresolvable -- correctly, since nothing on the
    platform would have computed it.
    """
    return {
        inputs.previous_spend_usd,
        inputs.current_spend_usd,
        inputs.current_spend_usd - inputs.previous_spend_usd,
        abs(inputs.current_spend_usd - inputs.previous_spend_usd),
        inputs.previous_compliance,
        inputs.current_compliance,
        inputs.current_compliance - inputs.previous_compliance,
        abs(inputs.current_compliance - inputs.previous_compliance),
    }


def has_anything_notable(inputs: DigestInputs, thresholds: NotabilityThresholds) -> bool:
    """FR-010's branch, decided by the platform before any spend is incurred.

    An open finding counts on its own: FR-008b's configured bars govern how far
    spend or compliance must move to be worth reporting, and a finding is not a
    move. A tenant with nothing open and neither figure past its bar has a
    genuinely empty day, and invoking a model to be told so would be paying for
    an answer already known.
    """
    if select_digest_findings(inputs.candidates):
        return True
    if is_spend_change_notable(inputs.previous_spend_usd, inputs.current_spend_usd, thresholds):
        return True
    return is_compliance_move_notable(
        inputs.previous_compliance, inputs.current_compliance, thresholds
    )


def parse_sections(output_text: str) -> list[Section]:
    """The digest prompt's output contract (R-610), parsed fail-closed.

    Anything malformed raises rather than degrading to a best-effort read. A
    partially-parsed digest would reach the validator with the fabricated part
    silently dropped, which is exactly the outcome FR-001 exists to prevent --
    the reference the model invented would never be seen, so it could never be
    rejected.

    Figures are declared, never scraped from prose (FR-001a). The validator
    sweeps the prose separately and rejects anything numeric it finds that this
    list does not account for.
    """
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"digest output was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
        raise ValueError("digest output must be an object with a 'sections' list")

    sections: list[Section] = []
    for raw in payload["sections"]:
        if not isinstance(raw, dict):
            raise ValueError("every digest section must be an object")
        try:
            sections.append(
                Section(
                    heading=str(raw["heading"]),
                    body=str(raw["body"]),
                    references=[
                        Reference(
                            kind=str(r["kind"]), id=str(r["id"]), label=str(r.get("label", ""))
                        )
                        for r in raw.get("references", [])
                    ],
                    figures=[
                        Figure(label=str(f["label"]), value=Decimal(str(f["value"])))
                        for f in raw.get("figures", [])
                    ],
                )
            )
        except (KeyError, TypeError, InvalidOperation) as exc:
            raise ValueError(f"malformed digest section: {exc}") from exc
    return sections


def _content(sections: list[Section], inputs: DigestInputs) -> dict[str, Any]:
    """R-610: structured sections, not rendered markup. Figures are stored as
    strings because JSONB has no exact decimal -- round-tripping through a float
    would move a currency amount that the grounding validator had just
    confirmed matched the platform's own to the cent.

    `platform_figures` records what the platform computed for this run, beside
    what the agent wrote about it. It is the compliance baseline the next run
    reads: nothing stores a historical compliance score, and recomputing one
    from `resource.created_at` would date a resource to when the scanner first
    saw it rather than to when it existed. "Since the last digest" is a weaker
    claim than "since yesterday", and it is the one the data actually supports.
    """
    return {
        "platform_figures": {
            "spend_usd": str(inputs.current_spend_usd),
            "compliance": str(inputs.current_compliance),
        },
        "sections": [
            {
                "heading": s.heading,
                "body": s.body,
                "references": [
                    {"kind": r.kind, "id": r.id, "label": r.label} for r in s.references
                ],
                "figures": [{"label": f.label, "value": str(f.value)} for f in s.figures],
            }
            for s in sections
        ],
    }


def _store_digest(
    session: TenantSession,
    *,
    run_id: uuid.UUID,
    inputs: DigestInputs,
    sections: list[Section],
    is_empty: bool,
) -> uuid.UUID:
    """One digest per tenant per day (FR-008): a re-run replaces rather than
    appends. The upsert rather than a delete-then-insert is deliberate -- two
    overlapping runs would leave a window with no digest at all, and the surface
    would render the not-enough-data state for a tenant that has plenty."""
    stmt = (
        pg_insert(InsightDigest)
        .values(
            tenant_id=session.tenant_id,
            agent_run_id=run_id,
            period_date=inputs.period_date,
            content=_content(sections, inputs),
            is_empty=is_empty,
        )
        .on_conflict_do_update(
            constraint="uq_insight_digest_tenant_date",
            set_={
                "agent_run_id": run_id,
                "content": _content(sections, inputs),
                "is_empty": is_empty,
                "created_at": datetime.now(UTC),
            },
        )
        .returning(InsightDigest.id)
    )
    return uuid.UUID(str(session.raw.execute(stmt).scalar_one()))


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
        capability=AgentCapability.DIGEST,
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


def run_digest(
    session: TenantSession,
    *,
    inputs: DigestInputs,
    invoke: Callable[[DigestInputs, list[DigestCandidate]], AgentDraft],
    definition_hash: str,
    cap_units: Decimal | None = None,
) -> DigestOutcome:
    """Assemble, invoke, validate, persist (FR-001, FR-004a, FR-008, FR-010).

    `invoke` is passed in rather than imported: the Bedrock client lives in
    `connectors/aws.py` (Principle V) and the handler owns the wiring, the same
    boundary `governance/notifications.py` established for SES. It also makes
    every branch below provable with no cloud client at all, which is what lets
    SC-001 be asserted in CI while the model is unreachable.

    Every path writes exactly one `agent_run` row. A run that produced nothing
    still happened and still cost something, and a digest that silently did not
    appear is indistinguishable from a scheduler that never fired (FR-005).
    """
    started_at = datetime.now(UTC)
    thresholds = notability_thresholds()
    budget = RunBudget(cap_units if cap_units is not None else default_cost_cap_units())

    if not has_anything_notable(inputs, thresholds):
        # FR-010: an explicit nothing-notable digest, not an absent one. The
        # model is never invoked, so this costs nothing.
        run = _record_run(
            session,
            definition_hash=definition_hash,
            status=AgentRunStatus.SUCCEEDED,
            failure_reason=None,
            budget=budget,
            started_at=started_at,
        )
        digest_id = _store_digest(
            session,
            run_id=run.id,
            inputs=inputs,
            sections=[],
            is_empty=True,
        )
        logger.info(
            "digest run found nothing notable",
            extra={"tenant_id": str(session.tenant_id), "agent_run_id": str(run.id)},
        )
        return DigestOutcome(
            run_id=run.id, status=AgentRunStatus.SUCCEEDED, digest_id=digest_id, is_empty=True
        )

    selected = select_digest_findings(inputs.candidates)
    draft: AgentDraft | None = None
    error: str | None = None
    try:
        draft = invoke(inputs, selected)
    except (RuntimeError, ValueError) as exc:
        # FR-007a: an unreachable model, and a draft that would not parse, are
        # both recorded failures rather than exceptions escaping the run. The
        # surfaces then serve the last valid digest.
        error = str(exc)
    if draft is not None:
        budget.charge(draft.cost_units)

    status, failure_reason = outcome_for(
        budget, completed=draft is not None and draft.completed, error=error
    )

    if status is AgentRunStatus.SUCCEEDED and draft is not None:
        verdict = validate_output(
            draft.sections,
            known_references=inputs.known_references,
            known_figures=known_figures(inputs),
        )
        if not verdict.ok:
            # FR-001: nothing is stored. The rejection row records what failed;
            # the draft itself is not kept, deliberately -- retaining it would
            # put a fabricated reference inside the platform, which is the thing
            # the check exists to prevent.
            status = AgentRunStatus.FAILED
            failure_reason = (
                f"grounding rejected {verdict.reference_kind}: {verdict.rejected_reference}"
            )
            run = _record_run(
                session,
                definition_hash=definition_hash,
                status=status,
                failure_reason=failure_reason,
                budget=budget,
                started_at=started_at,
            )
            session.add(
                GroundingRejection(
                    agent_run_id=run.id,
                    rejected_reference=str(verdict.rejected_reference),
                    reference_kind=verdict.reference_kind,
                )
            )
            session.flush()
            logger.warning(
                "digest output rejected before display",
                extra={
                    "tenant_id": str(session.tenant_id),
                    "agent_run_id": str(run.id),
                    "reference_kind": str(verdict.reference_kind),
                },
            )
            return DigestOutcome(
                run_id=run.id,
                status=status,
                digest_id=None,
                is_empty=False,
                rejected_reference=str(verdict.rejected_reference),
            )

        run = _record_run(
            session,
            definition_hash=definition_hash,
            status=status,
            failure_reason=None,
            budget=budget,
            started_at=started_at,
        )
        digest_id = _store_digest(
            session,
            run_id=run.id,
            inputs=inputs,
            sections=draft.sections,
            is_empty=False,
        )
        return DigestOutcome(run_id=run.id, status=status, digest_id=digest_id, is_empty=False)

    # Failed, or truncated. `keeps_partial_output` says the digest keeps nothing
    # (FR-004a): it is one artifact, and half of it reads as a complete summary
    # of a quiet day. No digest row is written, so the surface keeps serving
    # yesterday's valid one rather than today's fragment.
    run = _record_run(
        session,
        definition_hash=definition_hash,
        status=status,
        failure_reason=failure_reason,
        budget=budget,
        started_at=started_at,
    )
    logger.warning(
        "digest run stored no output",
        extra={
            "tenant_id": str(session.tenant_id),
            "agent_run_id": str(run.id),
            "status": str(status),
        },
    )
    return DigestOutcome(run_id=run.id, status=status, digest_id=None, is_empty=False)


__all__ = [
    "DIGEST_FINDING_LIMIT",
    "AgentDraft",
    "DigestCandidate",
    "DigestInputs",
    "DigestOutcome",
    "NotabilityThresholds",
    "collect_candidates",
    "has_anything_notable",
    "is_compliance_move_notable",
    "is_spend_change_notable",
    "build_inputs",
    "known_figures",
    "last_recorded_compliance",
    "notability_thresholds",
    "parse_sections",
    "run_digest",
    "select_digest_findings",
    "spend_totals",
]
