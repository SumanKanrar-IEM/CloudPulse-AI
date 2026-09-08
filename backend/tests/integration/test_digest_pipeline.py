"""The digest pipeline end to end, against a real PostgreSQL (T014; spec 006,
FR-001, FR-004a, FR-008, FR-008b, FR-010).

The unit tests next door prove the ranking and the notability thresholds. What
only a database can prove is the part those cannot: that one digest per tenant
per day is an invariant the store enforces rather than a convention the code
remembers, that a rejected draft leaves a rejection row and no digest, and that
a truncated run leaves nothing at all.

Every test drives `run_digest` with an `invoke` callable rather than a mocked
Bedrock client. The boundary is the point: the pipeline must be provable with no
cloud client present, which is what makes SC-001 assertable in CI while the
model is unreachable (FR-007a, R-605).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import TenantSession
from app.governance.digest import (
    AgentDraft,
    DigestCandidate,
    DigestInputs,
    build_inputs,
    collect_candidates,
    parse_sections,
    run_digest,
)
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
)

pytestmark = pytest.mark.integration

DEFINITION_HASH = "0" * 64
PERIOD = date(2026, 3, 1)

# Well inside the fallback bars (20%, $50, 5 points), so a test that means
# "nothing notable" cannot become "notable" through an unrelated figure.
QUIET_SPEND = (Decimal("1000.00"), Decimal("1004.00"))
QUIET_COMPLIANCE = (Decimal("90.0"), Decimal("91.0"))


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


def _open_finding(
    db: Session,
    tenant_id: uuid.UUID,
    account: CloudAccount,
    *,
    arn: str,
    severity: FindingSeverity = FindingSeverity.HIGH,
    escalated: bool = False,
    opened_at: datetime | None = None,
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
        status=FindingStatus.OPEN,
        opened_at=opened_at or datetime.now(UTC),
        escalated_at=datetime.now(UTC) if escalated else None,
    )
    db.add(finding)
    db.flush()
    return resource, finding


def _inputs(
    *,
    candidates: list[DigestCandidate] | None = None,
    known_references: dict[str, set[str]] | None = None,
    spend: tuple[Decimal, Decimal] = QUIET_SPEND,
    compliance: tuple[Decimal, Decimal] = QUIET_COMPLIANCE,
    period: date = PERIOD,
) -> DigestInputs:
    return DigestInputs(
        period_date=period,
        candidates=candidates or [],
        previous_spend_usd=spend[0],
        current_spend_usd=spend[1],
        previous_compliance=compliance[0],
        current_compliance=compliance[1],
        known_references=known_references or {},
    )


def _draft_naming(reference_kind: str, reference_id: str, *, cost: str = "10") -> AgentDraft:
    """A one-section draft citing exactly one reference and stating no figure."""
    return AgentDraft(
        sections=parse_sections(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Today",
                            "body": "One finding is still open.",
                            "references": [
                                {"kind": reference_kind, "id": reference_id, "label": "a finding"}
                            ],
                        }
                    ]
                }
            )
        ),
        cost_units=Decimal(cost),
    )


def _digest_rows(db: Session, tenant_id: uuid.UUID) -> list[Any]:
    return list(
        db.execute(
            text(
                "SELECT id, period_date, is_empty, content, agent_run_id FROM insight_digest "
                "WHERE tenant_id = :t ORDER BY period_date"
            ),
            {"t": tenant_id},
        ).all()
    )


# --- one per tenant per day (FR-008) -----------------------------------------


def test_a_run_produces_one_digest_for_the_period(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    _, finding = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    outcome = run_digest(
        session,
        inputs=_inputs(
            candidates=candidates,
            known_references={"finding": {str(finding.id)}},
        ),
        invoke=lambda _i, _s: _draft_naming("finding", str(finding.id)),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert outcome.digest_id is not None
    rows = _digest_rows(db, tenant_id)
    assert len(rows) == 1
    assert rows[0].period_date == PERIOD
    assert rows[0].is_empty is False


def test_a_rerun_replaces_the_days_digest_rather_than_duplicating_it(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """The unique constraint is the guarantee, not the code's good manners: two
    overlapping runs must not leave a user with two digests for one day."""
    _, finding = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)
    inputs = _inputs(candidates=candidates, known_references={"finding": {str(finding.id)}})

    first = run_digest(
        session,
        inputs=inputs,
        invoke=lambda _i, _s: _draft_naming("finding", str(finding.id)),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()
    second = run_digest(
        session,
        inputs=inputs,
        invoke=lambda _i, _s: _draft_naming("finding", str(finding.id)),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    rows = _digest_rows(db, tenant_id)
    assert len(rows) == 1
    # Same row, repointed at the newer run -- so the surface labels the digest
    # with the run that actually produced what is on screen (FR-009).
    assert first.digest_id == second.digest_id
    assert rows[0].agent_run_id == second.run_id
    assert first.run_id != second.run_id
    # Both runs are still recorded. A replaced digest does not erase the history
    # of the run that produced the version before it (FR-005).
    assert (
        db.execute(
            text("SELECT count(*) FROM agent_run WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalar_one()
        == 2
    )


def test_two_periods_each_keep_their_own_digest(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """One per tenant per *day*: yesterday's digest is not replaced by today's.

    Without this, the "replaces rather than duplicates" test above would still
    pass if the upsert keyed on tenant alone, and the platform would hold one
    digest ever.
    """
    _, finding = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)
    for period in (PERIOD, PERIOD + timedelta(days=1)):
        run_digest(
            session,
            inputs=_inputs(
                candidates=candidates,
                known_references={"finding": {str(finding.id)}},
                period=period,
            ),
            invoke=lambda _i, _s: _draft_naming("finding", str(finding.id)),
            definition_hash=DEFINITION_HASH,
        )
    db.commit()

    rows = _digest_rows(db, tenant_id)
    assert [row.period_date for row in rows] == [PERIOD, PERIOD + timedelta(days=1)]


# --- grounding (FR-001) ------------------------------------------------------


def test_a_draft_naming_an_absent_resource_is_rejected_and_recorded(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-001's whole point, at the pipeline level: the fabricated reference
    never reaches a surface, and the rejection is visible afterwards."""
    _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)
    fabricated = "arn:aws:ec2:us-east-1:123456789012:instance/i-0deadbeef"

    outcome = run_digest(
        session,
        inputs=_inputs(
            candidates=candidates,
            known_references={"resource": {"arn:aws:s3:::bucket-1"}},
        ),
        invoke=lambda _i, _s: _draft_naming("resource", fabricated),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.digest_id is None
    assert outcome.rejected_reference == fabricated
    assert _digest_rows(db, tenant_id) == []

    rejections = db.execute(
        text(
            "SELECT rejected_reference, reference_kind, agent_run_id FROM grounding_rejection "
            "WHERE tenant_id = :t"
        ),
        {"t": tenant_id},
    ).all()
    assert len(rejections) == 1
    assert rejections[0].rejected_reference == fabricated
    assert rejections[0].reference_kind == "arn"
    assert rejections[0].agent_run_id == outcome.run_id
    # Recorded as a failed run with a reason. A rejected draft that stored
    # nothing but reported success would be indistinguishable from a quiet day.
    assert outcome.status is AgentRunStatus.FAILED
    reason = db.execute(
        text("SELECT failure_reason FROM agent_run WHERE id = :r"), {"r": outcome.run_id}
    ).scalar_one()
    assert fabricated in reason


def test_a_fabricated_figure_is_rejected_the_same_way_a_fabricated_arn_is(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-001a. A real ARN with an invented dollar amount beside it is the
    likelier failure than an invented ARN, and it must fail identically."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    draft = AgentDraft(
        sections=parse_sections(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Spend",
                            "body": "Spend moved to $9999.00 this period.",
                            "references": [{"kind": "resource", "id": resource.arn, "label": "b"}],
                            "figures": [{"label": "current spend", "value": "9999.00"}],
                        }
                    ]
                }
            )
        ),
        cost_units=Decimal("10"),
    )
    outcome = run_digest(
        session,
        inputs=_inputs(
            candidates=candidates,
            known_references={"resource": {resource.arn}},
            spend=(Decimal("1000.00"), Decimal("1400.00")),
        ),
        invoke=lambda _i, _s: draft,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.digest_id is None
    assert outcome.rejected_reference == "9999.00"
    assert _digest_rows(db, tenant_id) == []
    assert (
        db.execute(
            text("SELECT reference_kind FROM grounding_rejection WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()
        == "figure"
    )


def test_a_digest_stating_a_platform_computed_figure_passes(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """The direction that must not be over-tightened (R-607): a correct digest
    quoting the platform's own number is stored, not rejected. A validator that
    only ever refuses is as useless as one that only ever accepts."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    draft = AgentDraft(
        sections=parse_sections(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Spend",
                            "body": "Spend rose to $1400.00 this period.",
                            "references": [{"kind": "resource", "id": resource.arn, "label": "b"}],
                            "figures": [{"label": "current spend", "value": "1400.00"}],
                        }
                    ]
                }
            )
        ),
        cost_units=Decimal("10"),
    )
    outcome = run_digest(
        session,
        inputs=_inputs(
            candidates=candidates,
            known_references={"resource": {resource.arn}},
            spend=(Decimal("1000.00"), Decimal("1400.00")),
        ),
        invoke=lambda _i, _s: draft,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert outcome.digest_id is not None
    content = _digest_rows(db, tenant_id)[0].content
    assert content["sections"][0]["figures"][0]["value"] == "1400.00"


# --- nothing notable (FR-010, FR-008b) ---------------------------------------


def test_a_tenant_crossing_no_threshold_gets_an_explicit_empty_digest(
    db: Session, session: TenantSession, tenant_id: uuid.UUID
) -> None:
    """FR-010: an explicit "nothing notable" state, not an absent card and not
    an empty one. The two are different answers to "is the platform working?"."""
    invoked: list[bool] = []

    def _never_called(_inputs: DigestInputs, _selected: list[DigestCandidate]) -> AgentDraft:
        invoked.append(True)
        raise AssertionError("the model must not be invoked when nothing is notable")

    outcome = run_digest(
        session,
        inputs=_inputs(),
        invoke=_never_called,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.is_empty is True
    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert invoked == []
    rows = _digest_rows(db, tenant_id)
    assert len(rows) == 1
    assert rows[0].is_empty is True
    assert rows[0].content["sections"] == []
    # The platform's own figures are still recorded on a quiet day. They are the
    # baseline the next run compares against, and skipping them here would make
    # every day after a quiet one look like a jump from nothing.
    assert rows[0].content["platform_figures"] == {
        "spend_usd": str(QUIET_SPEND[1]),
        "compliance": str(QUIET_COMPLIANCE[1]),
    }
    # Nothing was invoked, so nothing was spent -- FR-010's branch must not cost
    # a model call to reach.
    assert db.execute(
        text("SELECT cost_units FROM agent_run WHERE id = :r"), {"r": outcome.run_id}
    ).scalar_one() == Decimal("0.0000")


def test_a_tenant_crossing_a_threshold_does_not_get_an_empty_digest(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """The other half of the pair. Without it, a pipeline that marked every
    digest empty would pass the test above."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    outcome = run_digest(
        session,
        inputs=_inputs(
            candidates=candidates,
            known_references={"resource": {resource.arn}},
        ),
        invoke=lambda _i, _s: _draft_naming("resource", resource.arn),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.is_empty is False
    assert _digest_rows(db, tenant_id)[0].is_empty is False


def test_a_notable_spend_move_alone_is_enough_to_invoke(
    db: Session, session: TenantSession, tenant_id: uuid.UUID
) -> None:
    """No open findings at all, but spend moved past the absolute bar. A digest
    that only ever fired on findings would miss the whole cost half of FR-008."""
    outcome = run_digest(
        session,
        inputs=_inputs(spend=(Decimal("1000.00"), Decimal("1400.00"))),
        invoke=lambda _i, _s: AgentDraft(
            sections=parse_sections(
                json.dumps(
                    {
                        "sections": [
                            {"heading": "Spend", "body": "Spend rose sharply.", "figures": []}
                        ]
                    }
                )
            ),
            cost_units=Decimal("10"),
        ),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.is_empty is False
    assert outcome.status is AgentRunStatus.SUCCEEDED


# --- truncation (FR-004a) ----------------------------------------------------


def test_a_truncated_digest_run_discards_its_partial_output_entirely(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-004a's whole-artifact half. The digest is one thing; half of it reads
    as a complete summary of a quiet day, which is a claim the run never made."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    partial = AgentDraft(
        sections=parse_sections(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Partial",
                            "body": "One finding is still open.",
                            "references": [{"kind": "resource", "id": resource.arn, "label": "b"}],
                        }
                    ]
                }
            )
        ),
        cost_units=Decimal("500"),
        completed=False,
    )
    outcome = run_digest(
        session,
        inputs=_inputs(
            candidates=candidates,
            known_references={"resource": {resource.arn}},
        ),
        invoke=lambda _i, _s: partial,
        definition_hash=DEFINITION_HASH,
        cap_units=Decimal("500"),
    )
    db.commit()

    assert outcome.status is AgentRunStatus.TRUNCATED
    assert outcome.digest_id is None
    assert _digest_rows(db, tenant_id) == []
    # The run is still recorded, and truncation is not a failure -- an ordinary
    # budget stop must stay distinguishable from an unreachable model (FR-007a).
    assert (
        db.execute(
            text("SELECT failure_reason FROM agent_run WHERE id = :r"), {"r": outcome.run_id}
        ).scalar_one()
        is None
    )


def test_a_truncated_rerun_leaves_the_previous_days_digest_standing(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Discarding the partial output must not also discard what was already
    valid. A surface serving the last good digest (FR-007a) depends on this."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)
    inputs = _inputs(candidates=candidates, known_references={"resource": {resource.arn}})

    good = run_digest(
        session,
        inputs=inputs,
        invoke=lambda _i, _s: _draft_naming("resource", resource.arn),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()
    run_digest(
        session,
        inputs=inputs,
        invoke=lambda _i, _s: AgentDraft(sections=[], cost_units=Decimal("500"), completed=False),
        definition_hash=DEFINITION_HASH,
        cap_units=Decimal("500"),
    )
    db.commit()

    rows = _digest_rows(db, tenant_id)
    assert len(rows) == 1
    assert rows[0].id == good.digest_id
    assert rows[0].agent_run_id == good.run_id


def test_an_unreachable_model_stores_no_digest_and_records_the_reason(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-007a at the pipeline level. `invoke_agent` raises `RuntimeError`
    rather than returning a partial, and the run must absorb it into a recorded
    failure instead of letting the scheduled worker crash."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    def _unreachable(_inputs: DigestInputs, _selected: list[DigestCandidate]) -> AgentDraft:
        raise RuntimeError("bedrock agent invocation failed: endpoint unreachable")

    outcome = run_digest(
        session,
        inputs=_inputs(candidates=candidates, known_references={"resource": {resource.arn}}),
        invoke=_unreachable,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.status is AgentRunStatus.FAILED
    assert outcome.digest_id is None
    assert _digest_rows(db, tenant_id) == []
    reason = db.execute(
        text("SELECT failure_reason FROM agent_run WHERE id = :r"), {"r": outcome.run_id}
    ).scalar_one()
    assert "endpoint unreachable" in reason


def test_a_malformed_draft_is_a_recorded_failure_not_a_partial_digest(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Fail-closed parsing, at the pipeline level. A best-effort read of broken
    output would drop the malformed section silently -- and a fabricated
    reference in that section would then never reach the validator at all."""
    resource, _ = _open_finding(db, tenant_id, account, arn="arn:aws:s3:::bucket-1")
    candidates = collect_candidates(session)

    def _malformed(_inputs: DigestInputs, _selected: list[DigestCandidate]) -> AgentDraft:
        return AgentDraft(sections=parse_sections("not json at all"), cost_units=Decimal("10"))

    outcome = run_digest(
        session,
        inputs=_inputs(candidates=candidates, known_references={"resource": {resource.arn}}),
        invoke=_malformed,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.status is AgentRunStatus.FAILED
    assert _digest_rows(db, tenant_id) == []


# --- selection reaches the agent (FR-008a) -----------------------------------


def test_the_selection_handed_to_the_agent_is_the_platforms_ranking(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-008a end to end: the agent receives an already-ranked, already-capped
    list. It explains the selection; it does not make it."""
    older = datetime.now(UTC) - timedelta(days=3)
    _open_finding(db, tenant_id, account, arn="arn:aws:s3:::low", severity=FindingSeverity.LOW)
    _, critical = _open_finding(
        db,
        tenant_id,
        account,
        arn="arn:aws:s3:::critical",
        severity=FindingSeverity.CRITICAL,
        opened_at=older,
    )
    candidates = collect_candidates(session)
    seen: list[list[DigestCandidate]] = []

    def _capture(_inputs: DigestInputs, selected: list[DigestCandidate]) -> AgentDraft:
        seen.append(selected)
        return _draft_naming("finding", str(critical.id))

    run_digest(
        session,
        inputs=_inputs(candidates=candidates, known_references={"finding": {str(critical.id)}}),
        invoke=_capture,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert seen[0][0].finding_id == critical.id
    assert len(seen[0]) == 2


# --- the figures handed to the agent (FR-001a, R-607) ------------------------


def test_the_compliance_figure_is_one_a_person_would_actually_write(
    db: Session, session: TenantSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Three resources, one failing: a two-thirds score.

    Unquantised, the agent would be handed 66.66666666666666 and told not to
    round, so it would either write sixteen digits into prose or round and have
    the whole digest rejected for a figure that was correct. R-607: rejecting
    correct output is the failure direction that matters, and this is the shape
    it would have taken.
    """
    _open_finding(db, tenant_id, account, arn="arn:aws:s3:::failing")
    for name in ("clean-1", "clean-2"):
        db.add(
            Resource(
                tenant_id=tenant_id,
                cloud_account_id=account.id,
                arn=f"arn:aws:s3:::{name}",
                resource_type="AWS::S3::Bucket",
                service="s3",
                region="us-east-1",
                tags={},
            )
        )
    db.flush()

    inputs = build_inputs(session, PERIOD)

    assert inputs.current_compliance == Decimal("66.7")
    # And a digest stating it validates rather than being rejected.
    draft = AgentDraft(
        sections=parse_sections(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Compliance",
                            "body": "Compliance stands at 66.7%.",
                            "figures": [{"label": "compliance", "value": "66.7"}],
                        }
                    ]
                }
            )
        ),
        cost_units=Decimal("10"),
    )
    outcome = run_digest(
        session,
        inputs=inputs,
        invoke=lambda _i, _s: draft,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert outcome.status is AgentRunStatus.SUCCEEDED
    assert outcome.digest_id is not None
