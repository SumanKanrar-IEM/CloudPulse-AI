"""The suggester pipeline against a real PostgreSQL (T022; spec 006, FR-001,
FR-004, FR-004a, FR-011-FR-014).

The rules that only a store can prove: FR-013's refusal to overwrite an
admin-seeded suggestion, which rests on a conflict clause rather than a
read-then-write; FR-014's exclusion of closed findings; and FR-004a's item-wise
retention, where a run stopped by its cost cap keeps everything it validated and
the next run picks up the rest.

That last one is the difference between this capability and the digest. The
digest makes one call and discards a partial result whole; the suggester makes
one call per finding, so its budget can genuinely stop the work mid-pass -- and
what it already wrote must survive.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import TenantSession
from app.governance.suggester import (
    DraftedSuggestion,
    SuggestionTarget,
    parse_draft,
    run_suggester,
    targets_needing_suggestions,
)
from app.governance.suggestions import get_suggestion, seed_suggestion
from app.models.core import CloudAccount, Resource
from app.models.core import Finding as FindingRow
from app.models.core import Rule as RuleRow
from app.models.enums import (
    AccountStatus,
    AgentRunStatus,
    ConnectionMode,
    FindingKind,
    FindingSeverity,
    FindingStatus,
    SuggestionSource,
)

pytestmark = pytest.mark.integration

DEFINITION_HASH = "b" * 64
UNREACHABLE = "bedrock agent invocation failed: could not connect to the endpoint URL"


@pytest.fixture
def db(clean_database: Engine, alembic_config: Any) -> Iterator[Session]:
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant_id(db: Session) -> uuid.UUID:
    return uuid.UUID(str(db.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def session(db: Session, tenant_id: uuid.UUID) -> TenantSession:
    return TenantSession(db, tenant_id)


@pytest.fixture
def account(db: Session, tenant_id: uuid.UUID) -> CloudAccount:
    row = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add(row)
    db.flush()
    return row


def _finding(
    db: Session,
    tenant_id: uuid.UUID,
    account: CloudAccount,
    *,
    arn: str,
    severity: FindingSeverity = FindingSeverity.HIGH,
    status: FindingStatus = FindingStatus.OPEN,
) -> tuple[Resource, FindingRow]:
    rule = db.query(RuleRow).filter_by(tenant_id=tenant_id, key="owner", version=1).one()
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn=arn,
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-east-1",
        tags={},
    )
    db.add(resource)
    db.flush()
    finding = FindingRow(
        tenant_id=tenant_id,
        resource_id=resource.id,
        rule_id=rule.id,
        rule_version=1,
        kind=FindingKind.TAG_VIOLATION,
        severity=severity,
        status=status,
        opened_at=datetime.now(UTC),
        resolved_at=datetime.now(UTC) if status is FindingStatus.RESOLVED else None,
    )
    db.add(finding)
    db.flush()
    return resource, finding


def _good(target: SuggestionTarget, *, cost: str = "100") -> DraftedSuggestion:
    """A well-formed suggestion citing this finding's own resource."""
    return parse_draft(
        target.finding_id,
        json.dumps(
            {
                "suggestion": "Add an owner tag to the bucket.",
                "blastRadius": "Tagging is metadata-only and changes no access.",
                "references": [
                    {"kind": "resource", "id": target.resource_arn, "label": "the bucket"}
                ],
            }
        ),
        cost_units=Decimal(cost),
    )


def _suggestions(db: Session, tenant_id: uuid.UUID) -> list[Any]:
    return list(
        db.execute(
            text(
                "SELECT finding_id, suggestion_text, blast_radius_note, source "
                "FROM finding_remediation_suggestion WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).all()
    )


# --- what gets a suggestion (FR-011, FR-014) ---------------------------------


def test_every_open_finding_gets_its_own_suggestion(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Clarification 2026-09-05: per individual finding, not per finding class.
    Two findings of the same class must produce two rows, each naming its own
    resource."""
    _finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    _finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-2")

    outcome = run_suggester(session, invoke=_good, definition_hash=DEFINITION_HASH)
    db.commit()

    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert outcome.written == 2
    rows = _suggestions(db, tenant_id)
    assert len(rows) == 2
    assert {row.source for row in rows} == {"ai_generated"}


def test_a_closed_finding_never_gets_one(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-014, enforced by never drafting rather than by hiding at display time.
    A suggestion that exists but must not be shown is one refactor away from
    being shown."""
    _finding(db, tenant_id, account, arn="arn:aws:s3:::open-one")
    _, closed = _finding(
        db, tenant_id, account, arn="arn:aws:s3:::closed-one", status=FindingStatus.RESOLVED
    )

    run_suggester(session, invoke=_good, definition_hash=DEFINITION_HASH)
    db.commit()

    assert get_suggestion(session, closed.id) is None
    assert len(_suggestions(db, tenant_id)) == 1


def test_findings_are_offered_in_the_digests_priority_order(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """One ranking, not two. A capped run must spend what it has on the same
    findings the digest calls urgent -- a reader seeing a digest and a suggestion
    queue that disagree has no way to tell which is right."""
    _finding(db, tenant_id, account, arn="arn:aws:s3:::low", severity=FindingSeverity.LOW)
    _, critical = _finding(
        db, tenant_id, account, arn="arn:aws:s3:::critical", severity=FindingSeverity.CRITICAL
    )
    _, high = _finding(
        db, tenant_id, account, arn="arn:aws:s3:::high", severity=FindingSeverity.HIGH
    )

    ordered = targets_needing_suggestions(session)

    assert [t.finding_id for t in ordered][:2] == [critical.id, high.id]


# --- FR-013: never over an admin-seeded suggestion ---------------------------


def test_an_admin_seeded_suggestion_is_never_overwritten(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-013. The finding is excluded from the queue, so no model call is spent
    on an answer the writer would refuse anyway."""
    _, finding = _finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    seed_suggestion(session, finding.id, "Ask the owner directly.", "None.")
    db.commit()

    outcome = run_suggester(session, invoke=_good, definition_hash=DEFINITION_HASH)
    db.commit()

    assert outcome.written == 0
    stored = get_suggestion(session, finding.id)
    assert stored is not None
    assert stored.source is SuggestionSource.ADMIN_SEEDED
    assert stored.suggestion_text == "Ask the owner directly."


def test_the_writer_refuses_even_when_the_queue_did_not(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """The guarantee behind the optimisation above. If an admin seeds a
    suggestion between the query and the write, the conflict clause refuses --
    a read-then-write would have overwritten it, rarely and silently, which is
    precisely what FR-013 forbids."""
    from app.governance.suggestions import write_ai_suggestion

    _, finding = _finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    seed_suggestion(session, finding.id, "Ask the owner directly.", "None.")
    db.flush()

    written = write_ai_suggestion(session, finding.id, "Add a tag.", "Metadata only.")
    db.commit()

    assert written is False
    stored = get_suggestion(session, finding.id)
    assert stored is not None
    assert stored.source is SuggestionSource.ADMIN_SEEDED


def test_an_agent_suggestion_replaces_an_earlier_agent_one(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """The other side of the conflict clause: it must refuse admin-seeded rows
    without freezing the agent's own. A `where` that matched nothing would make
    every re-run a no-op and the suggestion permanently stale."""
    from app.governance.suggestions import write_ai_suggestion

    _, finding = _finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    write_ai_suggestion(session, finding.id, "First draft.", "Metadata only.")
    db.flush()

    written = write_ai_suggestion(session, finding.id, "Better draft.", "Still metadata only.")
    db.commit()

    assert written is True
    stored = get_suggestion(session, finding.id)
    assert stored is not None
    assert stored.suggestion_text == "Better draft."


# --- FR-012: distinguishable provenance --------------------------------------


def test_the_two_sources_are_distinguishable_on_the_row(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-012 at the write layer, not at display time. Neither writer has a
    parameter that could make it write the other's `source`."""
    _, seeded = _finding(db, tenant_id, account, arn="arn:aws:s3:::seeded")
    _finding(db, tenant_id, account, arn="arn:aws:s3:::drafted")
    seed_suggestion(session, seeded.id, "Ask the owner.", "None.")
    db.commit()

    run_suggester(session, invoke=_good, definition_hash=DEFINITION_HASH)
    db.commit()

    sources = {row.finding_id: row.source for row in _suggestions(db, tenant_id)}
    assert sources[seeded.id] == "admin_seeded"
    assert set(sources.values()) == {"admin_seeded", "ai_generated"}


# --- FR-001: grounding, per suggestion ---------------------------------------


def test_a_suggestion_failing_grounding_leaves_the_finding_with_none(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-001. Nothing is stored, and the rejection is recorded against the run."""
    _, finding = _finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    fabricated = "arn:aws:ec2:us-east-1:123456789012:instance/i-0deadbeef"

    def _fabricates(target: SuggestionTarget) -> DraftedSuggestion:
        return parse_draft(
            target.finding_id,
            json.dumps(
                {
                    "suggestion": "Detach the instance first.",
                    "blastRadius": "The instance would lose the mount.",
                    "references": [{"kind": "resource", "id": fabricated, "label": "instance"}],
                }
            ),
            cost_units=Decimal("100"),
        )

    outcome = run_suggester(session, invoke=_fabricates, definition_hash=DEFINITION_HASH)
    db.commit()

    assert outcome.written == 0
    assert outcome.rejected == 1
    assert get_suggestion(session, finding.id) is None
    rejections = db.execute(
        text(
            "SELECT rejected_reference, agent_run_id FROM grounding_rejection WHERE tenant_id = :t"
        ),
        {"t": tenant_id},
    ).all()
    assert len(rejections) == 1
    assert rejections[0].rejected_reference == fabricated
    assert rejections[0].agent_run_id == outcome.run_id


def test_one_rejected_suggestion_does_not_withhold_the_others(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Item-wise means item-wise in both directions. One model producing one bad
    ARN is not a reason to leave every other finding without a suggestion, and
    the run itself still succeeded -- it did what it was asked to."""
    _, bad = _finding(db, tenant_id, account, arn="arn:aws:s3:::bad", severity=FindingSeverity.LOW)
    _finding(db, tenant_id, account, arn="arn:aws:s3:::good-1")
    _finding(db, tenant_id, account, arn="arn:aws:s3:::good-2")

    def _one_bad(target: SuggestionTarget) -> DraftedSuggestion:
        if target.finding_id == bad.id:
            return parse_draft(
                target.finding_id,
                json.dumps(
                    {
                        "suggestion": "Fix it.",
                        "blastRadius": "None.",
                        "references": [
                            {"kind": "resource", "id": "arn:aws:s3:::invented", "label": "x"}
                        ],
                    }
                ),
                cost_units=Decimal("100"),
            )
        return _good(target)

    outcome = run_suggester(session, invoke=_one_bad, definition_hash=DEFINITION_HASH)
    db.commit()

    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert outcome.written == 2
    assert outcome.rejected == 1
    assert get_suggestion(session, bad.id) is None


# --- FR-004 / FR-004a: the cap actually stops the work -----------------------


def test_a_truncated_run_keeps_every_suggestion_it_validated(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-004a's item-wise half, and the reason it differs from the digest's.

    The cap allows two calls. The third finding is never drafted, and the two
    already written survive -- discarding them would waste spend the platform
    has already incurred for results that are individually complete.
    """
    for index in (1, 2, 3):
        _finding(db, tenant_id, account, arn=f"arn:aws:s3:::bucket-{index}")

    outcome = run_suggester(
        session,
        invoke=lambda t: _good(t, cost="50"),
        definition_hash=DEFINITION_HASH,
        cap_units=Decimal("100"),
    )
    db.commit()

    assert outcome.status is AgentRunStatus.TRUNCATED
    assert outcome.written == 2
    assert len(_suggestions(db, tenant_id)) == 2
    # Truncation is not a failure: an ordinary budget stop must stay
    # distinguishable from an unreachable model (FR-007a).
    assert (
        db.execute(
            text("SELECT failure_reason FROM agent_run WHERE id = :r"), {"r": outcome.run_id}
        ).scalar_one()
        is None
    )


def test_the_next_run_picks_up_what_the_capped_run_left(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-011's coverage is reached across runs, not necessarily within one
    (spec.md). Without this, the truncation test above would pass just as well
    for a pipeline that dropped the remainder permanently."""
    for index in (1, 2, 3):
        _finding(db, tenant_id, account, arn=f"arn:aws:s3:::bucket-{index}")

    run_suggester(
        session,
        invoke=lambda t: _good(t, cost="50"),
        definition_hash=DEFINITION_HASH,
        cap_units=Decimal("100"),
    )
    db.commit()
    second = run_suggester(session, invoke=_good, definition_hash=DEFINITION_HASH)
    db.commit()

    assert second.status is AgentRunStatus.SUCCEEDED
    assert second.written == 1
    assert len(_suggestions(db, tenant_id)) == 3


def test_the_cap_is_checked_before_the_call_not_after(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-004: reaching the cap MUST stop. A check performed only after charging
    would let the run spend past its limit once per pass and report the overrun
    as if it had been authorised."""
    for index in (1, 2, 3):
        _finding(db, tenant_id, account, arn=f"arn:aws:s3:::bucket-{index}")
    calls: list[uuid.UUID] = []

    def _counting(target: SuggestionTarget) -> DraftedSuggestion:
        calls.append(target.finding_id)
        return _good(target, cost="100")

    run_suggester(
        session, invoke=_counting, definition_hash=DEFINITION_HASH, cap_units=Decimal("100")
    )
    db.commit()

    assert len(calls) == 1


def test_an_unreachable_model_ends_the_pass_and_keeps_what_was_written(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-007a and FR-004a together. The next finding would fail identically, so
    the pass stops -- but everything already validated stays, for the same reason
    a capped run keeps its work."""
    _, first = _finding(
        db, tenant_id, account, arn="arn:aws:s3:::first", severity=FindingSeverity.CRITICAL
    )
    _finding(db, tenant_id, account, arn="arn:aws:s3:::second", severity=FindingSeverity.LOW)

    def _fails_after_one(target: SuggestionTarget) -> DraftedSuggestion:
        if target.finding_id == first.id:
            return _good(target)
        raise RuntimeError(UNREACHABLE)

    outcome = run_suggester(session, invoke=_fails_after_one, definition_hash=DEFINITION_HASH)
    db.commit()

    assert outcome.status is AgentRunStatus.FAILED
    assert outcome.written == 1
    assert len(_suggestions(db, tenant_id)) == 1
    reason = db.execute(
        text("SELECT failure_reason FROM agent_run WHERE id = :r"), {"r": outcome.run_id}
    ).scalar_one()
    assert UNREACHABLE in reason


def test_a_pass_with_nothing_to_do_still_records_a_run(
    db: Session, session: TenantSession, tenant_id: uuid.UUID
) -> None:
    """A run that found no work still happened. Without the row, "the suggester
    is not running" and "there was nothing to suggest" look identical (FR-005)."""
    outcome = run_suggester(session, invoke=_good, definition_hash=DEFINITION_HASH)
    db.commit()

    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert outcome.written == 0
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM agent_run WHERE tenant_id = :t AND capability = 'suggester'"
            ),
            {"t": tenant_id},
        ).scalar_one()
        == 1
    )
