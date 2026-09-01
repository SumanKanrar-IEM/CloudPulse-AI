"""GET/PUT /findings/{findingId}/suggestion (FR-018-FR-020a, FR-028a).

Runs against a real PostgreSQL container: the upsert-on-`(tenant_id,
finding_id)` behavior and the fact that this write path can never produce
`ai_generated` are both facts about the actual row, not something a mock
would catch drifting.
"""

from __future__ import annotations

import uuid
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
from app.api.routers import findings as findings_router
from app.models.core import CloudAccount, Finding, FindingRemediationSuggestion, Resource
from app.models.core import Rule as RuleRow
from app.models.enums import AccountStatus, ConnectionMode, FindingSeverity, FindingStatus

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]


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
def findings_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(findings_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    _stage(stager, real_tenant_id, ADMIN)
    return client, stager, real_tenant_id


@pytest.fixture
def seed(clean_database: Engine, real_tenant_id: uuid.UUID) -> dict[str, Any]:
    session: Session = sessionmaker(bind=clean_database)()
    account = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    session.add(account)
    session.flush()
    owner_rule = (
        session.query(RuleRow).filter_by(tenant_id=real_tenant_id, key="owner", version=1).one()
    )
    resource = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:s3:::bucket-1",
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-east-1",
        tags={},
    )
    session.add(resource)
    session.flush()
    finding = Finding(
        tenant_id=real_tenant_id,
        resource_id=resource.id,
        rule_id=owner_rule.id,
        rule_version=1,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
    )
    session.add(finding)
    session.commit()
    ids = {"finding_id": str(finding.id)}
    session.close()
    return ids


def test_a_finding_with_no_suggestion_shows_the_no_suggestion_state_not_an_error(
    findings_app, seed
) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    response = client.get(f"/findings/{seed['finding_id']}/suggestion")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["findingId"] == seed["finding_id"]
    assert body.get("suggestionText") is None
    assert body.get("source") is None


def test_admin_can_seed_a_suggestion_and_it_displays_like_a_real_one(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    response = client.put(
        f"/findings/{seed['finding_id']}/suggestion",
        json={"suggestionText": "Add the owner tag.", "blastRadiusNote": "Low: tag-only change."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggestionText"] == "Add the owner tag."
    assert body["blastRadiusNote"] == "Low: tag-only change."
    assert body["source"] == "admin_seeded"

    fetched = client.get(f"/findings/{seed['finding_id']}/suggestion")
    assert fetched.json() == body


def test_seeding_never_writes_ai_generated_regardless_of_input(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    """FR-020a: the endpoint has no parameter that can select `ai_generated` --
    the request body has no `source` field at all."""
    client, _, _ = findings_app
    response = client.put(
        f"/findings/{seed['finding_id']}/suggestion",
        json={
            "suggestionText": "x",
            "blastRadiusNote": "y",
            "source": "ai_generated",  # not part of the schema; must be ignored, not honored
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "admin_seeded"


def test_seeding_twice_upserts_rather_than_duplicating(
    findings_app, seed, clean_database, real_tenant_id
) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    client.put(
        f"/findings/{seed['finding_id']}/suggestion",
        json={"suggestionText": "first", "blastRadiusNote": "first note"},
    )
    second = client.put(
        f"/findings/{seed['finding_id']}/suggestion",
        json={"suggestionText": "second", "blastRadiusNote": "second note"},
    )
    assert second.json()["suggestionText"] == "second"

    session: Session = sessionmaker(bind=clean_database)()
    count = (
        session.query(FindingRemediationSuggestion)
        .filter_by(tenant_id=real_tenant_id, finding_id=uuid.UUID(seed["finding_id"]))
        .count()
    )
    session.close()
    assert count == 1


def test_operator_is_forbidden_from_seeding_a_suggestion(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = findings_app
    _stage(stager, tenant_id, OPERATOR)
    response = client.put(
        f"/findings/{seed['finding_id']}/suggestion",
        json={"suggestionText": "x", "blastRadiusNote": "y"},
    )
    assert response.status_code == 403


def test_viewer_can_view_a_seeded_suggestion(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = findings_app
    client.put(
        f"/findings/{seed['finding_id']}/suggestion",
        json={"suggestionText": "x", "blastRadiusNote": "y"},
    )
    _stage(stager, tenant_id, VIEWER)
    response = client.get(f"/findings/{seed['finding_id']}/suggestion")
    assert response.status_code == 200, response.text
    assert response.json()["suggestionText"] == "x"


def test_seeding_a_suggestion_for_a_nonexistent_finding_is_a_404(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    response = client.put(
        f"/findings/{uuid.uuid4()}/suggestion",
        json={"suggestionText": "x", "blastRadiusNote": "y"},
    )
    assert response.status_code == 404
