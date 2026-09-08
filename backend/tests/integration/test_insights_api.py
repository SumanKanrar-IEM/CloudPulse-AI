"""The insight surfaces, including what they show when the model is unreachable
(T018, T018a; spec 006, FR-005, FR-006, FR-007a, FR-009, FR-010).

**T018a is the half of T011a that Phase 2 could not reach.** T011a asserts the
deterministic core is unchanged by the intelligence layer; the other half of
FR-007a is a claim about a *surface* -- that with the model unreachable the
dashboard serves the last valid digest or an explicit not-enough-data state, and
never a partial or placeholder one. Those routes are this phase's, so the
assertion lives here. Stubbing a route in Phase 2 to satisfy the task ordering
would have proved nothing about the route that actually ships.

Every failure below is driven through `run_digest` with an `invoke` that raises,
rather than by writing an `agent_run` row by hand. A hand-written row would
assert that the API renders a failed run correctly while leaving unproven the
thing that matters: that a failed invocation *produces* one.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
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
from app.api.routers import insights as insights_router
from app.core.db import TenantSession
from app.governance.digest import (
    AgentDraft,
    DigestCandidate,
    DigestInputs,
    collect_candidates,
    parse_sections,
    run_digest,
)
from app.models.core import CloudAccount, Resource
from app.models.core import Finding as FindingRow
from app.models.core import Rule as RuleRow
from app.models.enums import (
    AccountStatus,
    ConnectionMode,
    FindingKind,
    FindingSeverity,
    FindingStatus,
)

pytestmark = pytest.mark.integration

DEFINITION_HASH = "a" * 64
PERIOD = date(2026, 3, 1)
VIEWER = ["cloudpulse-viewers"]
UNREACHABLE = "bedrock agent invocation failed: could not connect to the endpoint URL"


class _ClaimStager:
    def __init__(self, app: Any, tenant_id: uuid.UUID) -> None:
        self.app = app
        self.claims: dict[str, Any] = {
            "sub": "s",
            "email": "e@example.com",
            "cognito:groups": VIEWER,
            "custom:tenant_id": str(tenant_id),
        }

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


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
def api(
    clean_database: Engine, db: Session, tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(insights_router.router)
    return TestClient(_ClaimStager(app, tenant_id), raise_server_exceptions=False)


@pytest.fixture
def finding(db: Session, tenant_id: uuid.UUID) -> FindingRow:
    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add(account)
    db.flush()
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:s3:::bucket-1",
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-east-1",
        tags={},
    )
    db.add(resource)
    db.flush()
    rule = db.query(RuleRow).filter_by(tenant_id=tenant_id, key="owner", version=1).one()
    row = FindingRow(
        tenant_id=tenant_id,
        resource_id=resource.id,
        rule_id=rule.id,
        rule_version=1,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def _inputs(session: TenantSession, finding: FindingRow, *, period: date = PERIOD) -> DigestInputs:
    return DigestInputs(
        period_date=period,
        candidates=collect_candidates(session),
        previous_spend_usd=Decimal("1000.00"),
        current_spend_usd=Decimal("1400.00"),
        previous_compliance=Decimal("90.0"),
        current_compliance=Decimal("91.0"),
        known_references={"finding": {str(finding.id)}},
    )


def _good_draft(finding: FindingRow) -> AgentDraft:
    return AgentDraft(
        sections=parse_sections(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Open findings",
                            "body": "One finding is still open.",
                            "references": [
                                {"kind": "finding", "id": str(finding.id), "label": "missing owner"}
                            ],
                        }
                    ]
                }
            )
        ),
        cost_units=Decimal("120"),
    )


def _unreachable(_inputs: DigestInputs, _selected: list[DigestCandidate]) -> AgentDraft:
    raise RuntimeError(UNREACHABLE)


# --- the digest surface (FR-009, FR-010) -------------------------------------


def test_a_tenant_with_no_digest_gets_the_not_enough_data_state(api: TestClient) -> None:
    """Not a 404 and not an empty digest. An error would read as a broken
    dashboard, and an empty digest would claim a run found nothing notable when
    no run has happened at all (FR-007a)."""
    response = api.get("/insights/digest")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["sections"] == []
    assert body["periodDate"] is None


def test_a_stored_digest_is_labelled_with_the_run_that_produced_it(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """FR-009. Without the run's definition hash and the period on the card, a
    digest from a week ago looks exactly like this morning's."""
    run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=lambda _i, _s: _good_draft(finding),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    body = api.get("/insights/digest").json()
    assert body["available"] is True
    assert body["periodDate"] == PERIOD.isoformat()
    assert body["definitionHash"] == DEFINITION_HASH
    assert body["selectionBasis"] == "severity_escalation_age"
    assert body["sections"][0]["references"][0]["id"] == str(finding.id)


def test_the_digest_surface_never_exposes_the_platforms_own_working(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """`platform_figures` is stored beside the sections as the next run's
    compliance baseline. It is not part of the digest, and serving it would put
    a number the grounding validator never checked in front of a reader."""
    run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=lambda _i, _s: _good_draft(finding),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert "platform_figures" not in json.dumps(api.get("/insights/digest").json())


def test_a_nothing_notable_digest_is_available_and_empty(
    db: Session, session: TenantSession, api: TestClient
) -> None:
    """FR-010's two flags are different answers and must stay separable:
    `available` says a run happened, `isEmpty` says what it found."""
    run_digest(
        session,
        inputs=DigestInputs(
            period_date=PERIOD,
            candidates=[],
            previous_spend_usd=Decimal("1000.00"),
            current_spend_usd=Decimal("1004.00"),
            previous_compliance=Decimal("90.0"),
            current_compliance=Decimal("91.0"),
            known_references={},
        ),
        invoke=_unreachable,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    body = api.get("/insights/digest").json()
    assert body["available"] is True
    assert body["isEmpty"] is True
    assert body["sections"] == []


def test_the_newest_period_wins_not_the_newest_insert(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """A backfill for an older day must not displace the current digest just by
    being written most recently."""
    run_digest(
        session,
        inputs=_inputs(session, finding, period=PERIOD),
        invoke=lambda _i, _s: _good_draft(finding),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()
    run_digest(
        session,
        inputs=_inputs(session, finding, period=date(2026, 2, 1)),
        invoke=lambda _i, _s: _good_draft(finding),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert api.get("/insights/digest").json()["periodDate"] == PERIOD.isoformat()


# --- T018a: FR-007a's surface half -------------------------------------------


def test_an_unreachable_model_leaves_the_last_valid_digest_on_the_surface(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """FR-007a. The digest a reader sees is yesterday's, unchanged and still
    labelled with the run that produced it -- not a partial, not a placeholder,
    and not an error page."""
    good = run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=lambda _i, _s: _good_draft(finding),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()
    before = api.get("/insights/digest").json()

    failed = run_digest(
        session,
        inputs=_inputs(session, finding, period=date(2026, 3, 2)),
        invoke=_unreachable,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert failed.digest_id is None
    assert api.get("/insights/digest").json() == before
    assert before["definitionHash"] == DEFINITION_HASH
    assert good.digest_id is not None


def test_the_failed_run_is_visible_with_its_reason(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """FR-007a, FR-005. The digest surface is unchanged, so the only way to see
    that today's run failed is the run history -- which is why it must carry the
    reason rather than a bare status."""
    run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=_unreachable,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    runs = api.get("/insights/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert UNREACHABLE in runs[0]["failureReason"]
    assert runs[0]["capability"] == "digest"


def test_no_surface_renders_a_partial_result_when_a_run_truncates(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """FR-004a at the surface. The half-written digest exists nowhere the reader
    can reach it, and the run history says plainly that it truncated."""
    partial = AgentDraft(
        sections=_good_draft(finding).sections,
        cost_units=Decimal("500"),
        completed=False,
    )
    run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=lambda _i, _s: partial,
        definition_hash=DEFINITION_HASH,
        cap_units=Decimal("500"),
    )
    db.commit()

    assert api.get("/insights/digest").json()["available"] is False
    runs = api.get("/insights/runs").json()["runs"]
    assert runs[0]["status"] == "truncated"
    # Truncation is not a failure. Collapsing the two would make an ordinary
    # budget stop look like the model being unreachable.
    assert runs[0]["failureReason"] is None


# --- run history and rejections (FR-005, FR-006) -----------------------------


def test_runs_are_filterable_by_status_and_capability(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=lambda _i, _s: _good_draft(finding),
        definition_hash=DEFINITION_HASH,
    )
    run_digest(
        session,
        inputs=_inputs(session, finding, period=date(2026, 3, 2)),
        invoke=_unreachable,
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    assert len(api.get("/insights/runs").json()["runs"]) == 2
    assert len(api.get("/insights/runs?status=failed").json()["runs"]) == 1
    assert len(api.get("/insights/runs?capability=digest").json()["runs"]) == 2
    assert api.get("/insights/runs?capability=suggester").json()["runs"] == []


def test_a_rejection_is_inspectable_without_exposing_what_was_rejected(
    db: Session, session: TenantSession, api: TestClient, finding: FindingRow
) -> None:
    """FR-006. The rejection rate must be auditable -- a grounding validator
    nobody can inspect is a claim, not a control. The rejected *output* is never
    stored, so it cannot be served; the reference that failed is what diagnoses
    the rejection."""
    fabricated = "arn:aws:ec2:us-east-1:123456789012:instance/i-0deadbeef"
    run_digest(
        session,
        inputs=_inputs(session, finding),
        invoke=lambda _i, _s: AgentDraft(
            sections=parse_sections(
                json.dumps(
                    {
                        "sections": [
                            {
                                "heading": "Findings",
                                "body": "A resource is misconfigured.",
                                "references": [
                                    {"kind": "resource", "id": fabricated, "label": "instance"}
                                ],
                            }
                        ]
                    }
                )
            ),
            cost_units=Decimal("100"),
        ),
        definition_hash=DEFINITION_HASH,
    )
    db.commit()

    rejections = api.get("/insights/rejections").json()["rejections"]
    assert len(rejections) == 1
    assert rejections[0]["rejectedReference"] == fabricated
    assert rejections[0]["referenceKind"] == "arn"
    # Nothing reached the digest surface.
    assert api.get("/insights/digest").json()["available"] is False
    # And the body the agent wrote is nowhere in the response.
    assert "misconfigured" not in json.dumps(rejections)
