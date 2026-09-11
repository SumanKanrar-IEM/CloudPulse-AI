"""The advisor run end to end, against a real PostgreSQL (spec 006, T038b;
S43, FR-015, FR-015a, FR-017, FR-018).

User Story 3's independent test, as written in the spec: seed an inventory
containing a type absent from the coverage definitions, run the advisor, and
see a proposal appear. Then accept it and see the next run not raise it again.

The candidate map and the registry are both supplied here rather than read
from the repository. The shipped `enricher_candidates.json` is empty today --
deliberately, see `load_enricher_candidates` -- and a test that depended on it
would be asserting a fact about the current build rather than about the run.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import sessionmaker

import app.core.db as db_module
from app.core.db import tenant_session
from app.governance.advisor import inventory_types, run_advisor
from app.governance.coverage_advisor import decide
from app.models.core import AppUser, CloudAccount, CoverageAdvisoryGap, CoverageProposal, Resource
from app.models.enums import AccountStatus, ConnectionMode, ProposalReviewState

pytestmark = pytest.mark.integration

UNMAPPED_TYPE = "AWS::ElastiCache::CacheCluster"
CODELESS_TYPE = "AWS::Kendra::Index"
COVERED_TYPE = "AWS::S3::Bucket"
CANDIDATE_ENRICHER = "enrich_elasticache_cluster"
HASH = "e" * 64


@pytest.fixture
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def seed(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> dict[str, uuid.UUID]:
    """Two accounts; the unmapped type is in both so the evidence account is a
    choice the run has to make, and the covered type is present so the run has
    something to correctly ignore."""
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    # The candidate map is data the run reads; supplied here for the same reason
    # the registry is.
    monkeypatch.setattr(
        "app.governance.advisor.load_enricher_candidates",
        lambda: {UNMAPPED_TYPE: CANDIDATE_ENRICHER},
    )
    session = sessionmaker(bind=clean_database)()
    big = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="111111111111",
        alias="big",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    small = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="222222222222",
        alias="small",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    admin = AppUser(tenant_id=real_tenant_id, cognito_sub="admin-sub", email="admin@example.com")
    session.add_all([big, small, admin])
    session.flush()

    def resource(account: CloudAccount, resource_type: str, n: int) -> Resource:
        return Resource(
            tenant_id=real_tenant_id,
            cloud_account_id=account.id,
            arn=f"arn:aws:test:us-east-1:{account.aws_account_id}:thing/{resource_type}/{n}",
            resource_type=resource_type,
            service="test",
            region="us-east-1",
            tags={},
            detail={},
        )

    session.add_all(
        [
            resource(big, UNMAPPED_TYPE, 1),
            resource(big, UNMAPPED_TYPE, 2),
            resource(small, UNMAPPED_TYPE, 3),
            resource(big, CODELESS_TYPE, 4),
            resource(small, COVERED_TYPE, 5),
        ]
    )
    session.commit()
    ids = {"big": big.id, "small": small.id, "admin": admin.id}
    session.close()
    return ids


def _run(tenant_id: uuid.UUID) -> tuple[int, int]:
    with tenant_session(tenant_id) as session:
        outcome = run_advisor(
            session, known_enrichers={CANDIDATE_ENRICHER, "enrich_s3_bucket"}, definition_hash=HASH
        )
        session.commit()
    return outcome.proposed, outcome.advisory


def test_the_evidence_account_is_the_one_with_most_of_the_type(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    with tenant_session(real_tenant_id) as session:
        by_type = {t.resource_type: t for t in inventory_types(session)}

    assert by_type[UNMAPPED_TYPE].evidence_account_id == seed["big"]
    assert by_type[UNMAPPED_TYPE].resource_count == 2


def test_a_run_proposes_the_unmapped_type_and_advises_on_the_codeless_one(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """Acceptance scenario 1. The covered type produces nothing: the run reads
    the shipped definitions, and S3 buckets are in them."""
    proposed, advisory = _run(real_tenant_id)

    assert (proposed, advisory) == (1, 1)
    with tenant_session(real_tenant_id) as session:
        proposals = session.raw.execute(
            session.scoped(CoverageProposal.__table__.select(), CoverageProposal)
        ).all()
        gaps = session.raw.execute(
            session.scoped(CoverageAdvisoryGap.__table__.select(), CoverageAdvisoryGap)
        ).all()

    assert [(p.resource_type, p.review_state) for p in proposals] == [
        (UNMAPPED_TYPE, ProposalReviewState.PENDING)
    ]
    assert proposals[0].proposed_change == {
        "resource_type": UNMAPPED_TYPE,
        "enrichment_function": CANDIDATE_ENRICHER,
    }
    assert [g.resource_type for g in gaps] == [CODELESS_TYPE]


def test_a_second_run_does_not_stack_a_pending_proposal(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    _run(real_tenant_id)
    proposed, _ = _run(real_tenant_id)

    assert proposed == 0


def test_an_accepted_proposal_is_covered_on_the_next_run(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """Acceptance scenario 2, from the advisor's side. Once accepted, the type
    is in the merged definitions, so the next run sees no gap at all -- neither
    a proposal nor an advisory row."""
    _run(real_tenant_id)
    with tenant_session(real_tenant_id) as session:
        proposal_id = session.raw.execute(
            session.scoped(select(CoverageProposal.id), CoverageProposal)
        ).scalar_one()
        decide(session, proposal_id, accept=True, decided_by=seed["admin"])
        session.commit()

    proposed, advisory = _run(real_tenant_id)

    # Only the codeless type remains advisory; the accepted one is now covered.
    assert (proposed, advisory) == (0, 1)
    # And covered is why -- not "still pending, so skipped". A decision that
    # failed to persist would produce the same counts through the dedupe path,
    # so the state is asserted too.
    with tenant_session(real_tenant_id) as session:
        state = session.raw.execute(
            session.scoped(select(CoverageProposal.review_state), CoverageProposal)
        ).scalar_one()
    assert state is ProposalReviewState.ACCEPTED


def test_a_rejected_proposal_is_not_raised_again(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """Acceptance scenario 3. The gap still exists -- the type is still in
    inventory and still unmapped -- and the run still does not re-propose it."""
    _run(real_tenant_id)
    with tenant_session(real_tenant_id) as session:
        proposal_id = session.raw.execute(
            session.scoped(select(CoverageProposal.id), CoverageProposal)
        ).scalar_one()
        decide(session, proposal_id, accept=False, decided_by=seed["admin"])
        session.commit()

    proposed, _ = _run(real_tenant_id)

    assert proposed == 0
    with tenant_session(real_tenant_id) as session:
        states = session.raw.execute(
            session.scoped(CoverageProposal.__table__.select(), CoverageProposal)
        ).all()
    assert [s.review_state for s in states] == [ProposalReviewState.REJECTED]


def test_a_run_writes_its_own_agent_run_row_with_no_cost(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """No model is called, so the cost is zero -- and the row still exists, so
    `/insights/runs` shows the advisor ran."""
    with tenant_session(real_tenant_id) as session:
        outcome = run_advisor(session, known_enrichers=set(), definition_hash=HASH)
        session.commit()
        row = session.raw.execute(
            text("SELECT capability, cost_units, status FROM agent_run WHERE id = :id"),
            {"id": outcome.run_id},
        ).one()

    assert (row.capability, int(row.cost_units), row.status) == ("advisor", 0, "succeeded")
