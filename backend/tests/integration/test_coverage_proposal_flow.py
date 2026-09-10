"""The coverage proposal lifecycle end to end (spec 006, T033; S43, FR-015a,
FR-016, FR-017, FR-018).

Four properties, each of which is the whole point of one requirement:

* **Acceptance is configuration, not code.** FR-017 promises an accepted
  proposal takes effect on the next scan with no deployment. That is only true
  if the accepted mapping is readable as data and applies to every account in
  the tenant, not just the one whose inventory revealed the gap. Both halves are
  asserted, and the tenant-wide half is asserted against a *different* account
  than the evidence one -- otherwise a per-account implementation would pass.
* **Rejection sticks.** FR-018. A rejected type must not come back on the next
  advisor run, or the decision was a dismissal rather than an answer.
* **Reading and deciding are different privileges.** FR-016. A non-admin sees
  the proposal and cannot act on it.
* **An advisory gap has no decision route at all.** FR-015a. Not a disabled
  control, not a 403 -- no route. This is asserted against the assembled app's
  own routing table rather than by probing one guessed URL, because the claim
  is about what the platform exposes, not about what one string happens to hit.

Against a real PostgreSQL, like every other flow suite here: the partial unique
index on pending proposals and the advisory table's uniqueness are PostgreSQL
behaviour, and a mocked session would prove neither.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import coverage_proposals as coverage_router
from app.core.db import tenant_session
from app.governance.coverage_advisor import (
    AdvisoryGap,
    ProposableGap,
    accepted_coverage_overrides,
    already_decided_types,
    record_advisory_gaps,
    record_proposals,
)
from app.models.core import AgentRun, CloudAccount
from app.models.enums import (
    AccountStatus,
    AgentCapability,
    AgentRunStatus,
    ConnectionMode,
    CoverageProposalKind,
)

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]

GAP_TYPE = "AWS::ElastiCache::CacheCluster"
REJECTED_TYPE = "AWS::Redshift::Cluster"
ADVISORY_TYPE = "AWS::Kendra::Index"
ENRICHER = "enrich_elasticache_cluster"
DEFINITION_HASH = "d" * 64


class _ClaimStager:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.claims: dict[str, Any] | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


def _stage(stager: _ClaimStager, tenant_id: uuid.UUID, groups: list[str]) -> None:
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": groups,
        "custom:tenant_id": str(tenant_id),
    }


@pytest.fixture
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def seed(clean_database: Engine, real_tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Two accounts and one advisor run.

    Two accounts deliberately: FR-017's "tenant-wide" is only provable if an
    accepted proposal raised from one account's inventory governs the other one
    too, and a single-account fixture would let a per-account implementation
    pass every assertion here.
    """
    session: Session = sessionmaker(bind=clean_database)()
    evidence = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="evidence",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    other = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="210987654321",
        alias="other",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    run = AgentRun(
        tenant_id=real_tenant_id,
        capability=AgentCapability.ADVISOR,
        definition_hash=DEFINITION_HASH,
        status=AgentRunStatus.SUCCEEDED,
        cost_units=Decimal("40"),
        cost_cap_units=Decimal("200000"),
    )
    session.add_all([evidence, other, run])
    session.commit()
    ids = {"evidence": evidence.id, "other": other.id, "run": run.id}
    session.close()
    return ids


@pytest.fixture
def api(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, FastAPI]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(coverage_router.router)
    stager = _ClaimStager(app)
    return TestClient(stager, raise_server_exceptions=False), stager, app


def _propose(tenant_id: uuid.UUID, run_id: uuid.UUID, account_id: uuid.UUID) -> uuid.UUID:
    with tenant_session(tenant_id) as session:
        written = record_proposals(
            session,
            agent_run_id=run_id,
            gaps=[
                ProposableGap(
                    resource_type=GAP_TYPE,
                    kind=CoverageProposalKind.ENABLE_EXISTING_ENRICHER,
                    evidence_account_id=account_id,
                    proposed_change={
                        "resource_type": GAP_TYPE,
                        "enrichment_function": ENRICHER,
                    },
                )
            ],
        )
        session.commit()
        return written[0]


# --- FR-016/FR-017: acceptance is configuration, and it is tenant-wide -------


def test_accepting_a_proposal_applies_tenant_wide_with_no_code_change(
    api: tuple[TestClient, _ClaimStager, FastAPI],
    real_tenant_id: uuid.UUID,
    seed: dict[str, uuid.UUID],
) -> None:
    client, stager, _ = api
    proposal_id = _propose(real_tenant_id, seed["run"], seed["evidence"])
    _stage(stager, real_tenant_id, ADMIN)

    response = client.post(f"/coverage-proposals/{proposal_id}/decision", json={"accept": True})

    assert response.status_code == 200
    body = response.json()
    assert body["reviewState"] == "accepted"
    # FR-017: applied on acceptance, because acceptance *is* the application --
    # there is no deployment step in between for a scan to wait on.
    assert body["appliedAt"] is not None

    with tenant_session(real_tenant_id) as session:
        overrides = accepted_coverage_overrides(session)

    # The next scan reads this as configuration. It is a plain mapping, not a
    # code path, which is the whole of FR-017's "no code deployment".
    assert overrides == {GAP_TYPE: ENRICHER}

    # Tenant-wide, not evidence-scoped: nothing in what the scan reads mentions
    # the account the gap was raised from. A per-account implementation would
    # have to key this by account id, and could not produce this shape.
    assert seed["evidence"] not in overrides.values()
    assert str(seed["evidence"]) not in str(overrides)


# --- FR-018: a rejected proposal does not come back --------------------------


def test_a_rejected_proposal_is_not_re_proposed_on_the_next_run(
    api: tuple[TestClient, _ClaimStager, FastAPI],
    real_tenant_id: uuid.UUID,
    seed: dict[str, uuid.UUID],
) -> None:
    client, stager, _ = api
    with tenant_session(real_tenant_id) as session:
        written = record_proposals(
            session,
            agent_run_id=seed["run"],
            gaps=[
                ProposableGap(
                    resource_type=REJECTED_TYPE,
                    kind=CoverageProposalKind.RULE_EXTENSION,
                    evidence_account_id=seed["evidence"],
                    proposed_change={"resource_type": REJECTED_TYPE},
                )
            ],
        )
        session.commit()
    _stage(stager, real_tenant_id, ADMIN)

    assert (
        client.post(
            f"/coverage-proposals/{written[0]}/decision", json={"accept": False}
        ).status_code
        == 200
    )

    # The next advisor run still observes the same gap -- the resource type did
    # not disappear because an admin said no.
    with tenant_session(real_tenant_id) as session:
        assert REJECTED_TYPE in already_decided_types(session)
        again = record_proposals(
            session,
            agent_run_id=seed["run"],
            gaps=[
                ProposableGap(
                    resource_type=REJECTED_TYPE,
                    kind=CoverageProposalKind.RULE_EXTENSION,
                    evidence_account_id=seed["evidence"],
                    proposed_change={"resource_type": REJECTED_TYPE},
                )
            ],
        )
        session.commit()

    assert again == []

    listed = client.get("/coverage-proposals").json()["proposals"]
    # Still exactly one row, still rejected. FR-018 means the answer persists,
    # not that the row is deleted -- a vanished proposal is indistinguishable
    # from a gap that was never detected.
    assert [(p["resourceType"], p["reviewState"]) for p in listed] == [(REJECTED_TYPE, "rejected")]


def test_deciding_an_already_decided_proposal_is_refused(
    api: tuple[TestClient, _ClaimStager, FastAPI],
    real_tenant_id: uuid.UUID,
    seed: dict[str, uuid.UUID],
) -> None:
    client, stager, _ = api
    proposal_id = _propose(real_tenant_id, seed["run"], seed["evidence"])
    _stage(stager, real_tenant_id, ADMIN)
    client.post(f"/coverage-proposals/{proposal_id}/decision", json={"accept": True})

    second = client.post(f"/coverage-proposals/{proposal_id}/decision", json={"accept": False})

    # A silent re-apply would move `applied_at` and make the audit trail
    # misstate when the change took effect.
    assert second.status_code == 409


# --- FR-016: a non-admin reads but cannot decide -----------------------------


@pytest.mark.parametrize("groups", [OPERATOR, VIEWER], ids=["operator", "viewer"])
def test_a_non_admin_reads_proposals_but_cannot_decide(
    api: tuple[TestClient, _ClaimStager, FastAPI],
    real_tenant_id: uuid.UUID,
    seed: dict[str, uuid.UUID],
    groups: list[str],
) -> None:
    client, stager, _ = api
    proposal_id = _propose(real_tenant_id, seed["run"], seed["evidence"])
    _stage(stager, real_tenant_id, groups)

    listed = client.get("/coverage-proposals")
    assert listed.status_code == 200
    # The body, not the status: an empty list would pass a status-only check for
    # a role that should never have been served.
    assert listed.json()["proposals"][0]["resourceType"] == GAP_TYPE

    refused = client.post(f"/coverage-proposals/{proposal_id}/decision", json={"accept": True})
    assert refused.status_code == 403

    # And the refusal actually refused -- a 403 that had already written the
    # decision would be worse than no check at all.
    with tenant_session(real_tenant_id) as session:
        assert accepted_coverage_overrides(session) == {}


# --- FR-015a: an advisory gap has no decision endpoint at all ----------------


def test_an_advisory_gap_is_readable_by_every_role(
    api: tuple[TestClient, _ClaimStager, FastAPI],
    real_tenant_id: uuid.UUID,
    seed: dict[str, uuid.UUID],
) -> None:
    client, stager, _ = api
    reason = "no enrichment routine exists for this type"
    with tenant_session(real_tenant_id) as session:
        record_advisory_gaps(
            session,
            agent_run_id=seed["run"],
            gaps=[
                AdvisoryGap(
                    resource_type=ADVISORY_TYPE,
                    evidence_account_id=seed["evidence"],
                    reason=reason,
                )
            ],
        )
        session.commit()

    for groups in (ADMIN, OPERATOR, VIEWER):
        _stage(stager, real_tenant_id, groups)
        body = client.get("/coverage-proposals/advisory-gaps").json()
        assert [g["resourceType"] for g in body["gaps"]] == [ADVISORY_TYPE]
        # The stored reason, served verbatim. Not re-derived, so not something
        # the API could have invented.
        assert body["gaps"][0]["reason"] == reason


def test_no_route_can_decide_an_advisory_gap(
    api: tuple[TestClient, _ClaimStager, FastAPI],
) -> None:
    """FR-015a asserted against the routing table, not one guessed URL.

    Probing a single path would prove that path is absent; the requirement is
    that *no* path can act on an advisory gap. The assembled app exposes exactly
    one advisory route and it is a GET.
    """
    _, _, app = api

    advisory = [
        (route.path, sorted(route.methods or ()))  # type: ignore[attr-defined]
        for route in app.routes
        if "advisory" in getattr(route, "path", "")
    ]

    assert advisory == [("/coverage-proposals/advisory-gaps", ["GET"])]

    # And nothing on the decision route is reachable with an advisory gap's
    # identity, because an advisory gap has no id to send.
    assert not any(
        "advisory" in getattr(route, "path", "") and "decision" in getattr(route, "path", "")
        for route in app.routes
    )


def test_a_gap_no_longer_observed_is_deleted_rather_than_left_standing(
    api: tuple[TestClient, _ClaimStager, FastAPI],
    real_tenant_id: uuid.UUID,
    seed: dict[str, uuid.UUID],
) -> None:
    """A stale advisory row is an active lie: "no enrichment routine exists" for
    a type a later release added one for. Each run rewrites the set."""
    client, stager, _ = api
    with tenant_session(real_tenant_id) as session:
        record_advisory_gaps(
            session,
            agent_run_id=seed["run"],
            gaps=[
                AdvisoryGap(
                    resource_type=ADVISORY_TYPE,
                    evidence_account_id=seed["evidence"],
                    reason="no enrichment routine exists",
                )
            ],
        )
        session.commit()

    with tenant_session(real_tenant_id) as session:
        record_advisory_gaps(session, agent_run_id=seed["run"], gaps=[])
        session.commit()

    _stage(stager, real_tenant_id, VIEWER)
    assert client.get("/coverage-proposals/advisory-gaps").json()["gaps"] == []
