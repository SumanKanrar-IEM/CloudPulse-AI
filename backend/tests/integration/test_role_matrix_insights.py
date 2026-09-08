"""The full role matrix across spec 006's P1 read surfaces (T028; S43, S44,
FR-009).

Runs against a real PostgreSQL, matching every other role-matrix suite's own
reason: a role check that passes against a mocked session proves the dependency
was called, not that the endpoint serves data to that role.

**Every cell is asserted explicitly, admin included.** Research.md R-205's
non-hierarchical-roles point -- a naive "admin can do everything" implementation
could pass every other cell while admin's own silently regressed, so admin is
never inferred from viewer working.

**Bodies are asserted, not just status codes.** A 200 carrying an empty list
would pass a status-only matrix for every role, including one that should have
been refused, and the failure would look like a role check working. Each surface
below is seeded so that an empty response is a failure.

**There is no refusal cell on these three surfaces, and that is stated rather
than assumed.** Spec 006's P1 API surface is read-only: the digest, the run
history and the rejection log. Every write is performed by a worker Lambda under
its own IAM role, never by a signed-in principal through the API -- which is
FR-002's guarantee expressed as an absence, and `test_no_remediation_execution.py`
is what asserts that absence directly. What *is* asserted here is the boundary
that does exist: no token at all is 401, and a token carrying no recognised
group is 403.

That last cell matters more than it reads. A token with no group is the shape an
agent's own machine principal would arrive as if `build_agent_principal` were
ever bypassed, and defaulting it to viewer would hand the intelligence layer a
readable surface nobody granted it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import insights as insights_router
from app.models.core import AgentRun, GroundingRejection, InsightDigest
from app.models.enums import AgentCapability, AgentRunStatus, GroundingReferenceKind

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]
EVERY_ROLE = [ADMIN, OPERATOR, VIEWER]

# A group the platform has never heard of. Not an empty list -- an unrecognised
# group is the likelier real-world shape (a Cognito group added for another
# system), and a naive membership check can treat "has groups" as "is
# authorised".
UNRECOGNISED = ["some-other-systems-group"]

SURFACES = ("/insights/digest", "/insights/runs", "/insights/rejections")
PERIOD = date(2026, 3, 1)
DEFINITION_HASH = "c" * 64
REJECTED_ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0deadbeef"


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
def seed(clean_database: Engine, real_tenant_id: uuid.UUID) -> None:
    """One digest, two runs and one rejection -- enough that an empty response
    fails these tests rather than passing them by accident.

    The second run is `failed`: a run history that only ever held successes
    would let a surface filtering them out look identical to one that does not.
    """
    session = sessionmaker(bind=clean_database)()
    succeeded = AgentRun(
        tenant_id=real_tenant_id,
        capability=AgentCapability.DIGEST,
        definition_hash=DEFINITION_HASH,
        status=AgentRunStatus.SUCCEEDED,
        cost_units=Decimal("120"),
        cost_cap_units=Decimal("200000"),
    )
    failed = AgentRun(
        tenant_id=real_tenant_id,
        capability=AgentCapability.SUGGESTER,
        definition_hash=DEFINITION_HASH,
        status=AgentRunStatus.FAILED,
        cost_units=Decimal("0"),
        cost_cap_units=Decimal("200000"),
        failure_reason="bedrock agent invocation failed: endpoint unreachable",
    )
    session.add_all([succeeded, failed])
    session.flush()

    session.add(
        InsightDigest(
            tenant_id=real_tenant_id,
            agent_run_id=succeeded.id,
            period_date=PERIOD,
            content={
                "platform_figures": {"spend_usd": "1400.00", "compliance": "91.0"},
                "sections": [
                    {
                        "heading": "Open findings",
                        "body": "One finding is still open.",
                        "references": [],
                        "figures": [],
                    }
                ],
            },
            is_empty=False,
        )
    )
    session.add(
        GroundingRejection(
            tenant_id=real_tenant_id,
            agent_run_id=failed.id,
            rejected_reference=REJECTED_ARN,
            reference_kind=GroundingReferenceKind.ARN,
        )
    )
    session.commit()
    session.close()


@pytest.fixture
def api(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(insights_router.router)
    stager = _ClaimStager(app)
    return TestClient(stager, raise_server_exceptions=False), stager


# --- every role reads every surface ------------------------------------------


@pytest.mark.parametrize("groups", EVERY_ROLE, ids=["admin", "operator", "viewer"])
def test_every_role_reads_the_digest(
    api: tuple[TestClient, _ClaimStager], real_tenant_id: uuid.UUID, seed: None, groups: list[str]
) -> None:
    client, stager = api
    _stage(stager, real_tenant_id, groups)

    response = client.get("/insights/digest")

    assert response.status_code == 200
    body = response.json()
    # The body, not the status. An `available: false` digest would be a 200 for
    # every role including one that should never have been served.
    assert body["available"] is True
    assert body["periodDate"] == PERIOD.isoformat()
    assert body["definitionHash"] == DEFINITION_HASH
    assert body["sections"][0]["heading"] == "Open findings"


@pytest.mark.parametrize("groups", EVERY_ROLE, ids=["admin", "operator", "viewer"])
def test_every_role_reads_the_run_history(
    api: tuple[TestClient, _ClaimStager], real_tenant_id: uuid.UUID, seed: None, groups: list[str]
) -> None:
    client, stager = api
    _stage(stager, real_tenant_id, groups)

    response = client.get("/insights/runs")

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) == 2
    # The failed run and its reason are visible to every role. A history that
    # showed only successes would answer "is the layer working?" with "yes"
    # whatever the truth (FR-007a).
    failed = [run for run in runs if run["status"] == "failed"]
    assert len(failed) == 1
    assert "unreachable" in failed[0]["failureReason"]


@pytest.mark.parametrize("groups", EVERY_ROLE, ids=["admin", "operator", "viewer"])
def test_every_role_reads_the_rejection_log(
    api: tuple[TestClient, _ClaimStager], real_tenant_id: uuid.UUID, seed: None, groups: list[str]
) -> None:
    """FR-006: the rejection rate must be inspectable, and by everyone who can
    see the output it guards. A grounding validator only admins can audit is a
    claim to everyone else."""
    client, stager = api
    _stage(stager, real_tenant_id, groups)

    response = client.get("/insights/rejections")

    assert response.status_code == 200
    rejections = response.json()["rejections"]
    assert len(rejections) == 1
    assert rejections[0]["rejectedReference"] == REJECTED_ARN
    assert rejections[0]["referenceKind"] == "arn"


# --- the boundary that does exist --------------------------------------------


@pytest.mark.parametrize("path", SURFACES)
def test_an_unauthenticated_caller_is_refused(
    api: tuple[TestClient, _ClaimStager], seed: None, path: str
) -> None:
    client, stager = api
    stager.claims = None

    response = client.get(path)

    assert response.status_code == 401
    assert "sections" not in response.text
    assert REJECTED_ARN not in response.text


@pytest.mark.parametrize("path", SURFACES)
def test_a_caller_with_no_recognised_group_is_refused(
    api: tuple[TestClient, _ClaimStager], real_tenant_id: uuid.UUID, seed: None, path: str
) -> None:
    """Fail-closed on the group, not default-permit.

    An unrecognised group rather than an empty list, deliberately: a membership
    check that asks "does this token have groups?" passes an empty-list test and
    still admits a token carrying somebody else's group.
    """
    client, stager = api
    _stage(stager, real_tenant_id, UNRECOGNISED)

    response = client.get(path)

    assert response.status_code == 403
    assert REJECTED_ARN not in response.text


# --- tenant scoping ----------------------------------------------------------


def test_a_valid_role_in_another_tenant_sees_nothing(
    api: tuple[TestClient, _ClaimStager], real_tenant_id: uuid.UUID, seed: None
) -> None:
    """FR-030. A correctly-authorised admin of a different tenant is the case a
    role matrix alone would miss: every role check passes, and the wrong data is
    served. Asserted on all three surfaces, since each queries independently."""
    client, stager = api
    _stage(stager, uuid.uuid4(), ADMIN)

    digest = client.get("/insights/digest")
    runs = client.get("/insights/runs")
    rejections = client.get("/insights/rejections")

    assert digest.status_code == 200
    assert digest.json()["available"] is False
    assert runs.json()["runs"] == []
    assert rejections.json()["rejections"] == []
    assert REJECTED_ARN not in rejections.text
