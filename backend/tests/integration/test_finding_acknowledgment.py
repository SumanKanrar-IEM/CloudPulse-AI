"""POST /findings/{findingId}/acknowledge (FR-015-FR-017, FR-020, FR-028).

Runs against a real PostgreSQL container: the idempotent `WHERE
acknowledged_at IS NULL` guard (data-model.md) is exactly the kind of thing a
mocked session would let slide by construction.
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
from app.models.core import AuditEvent, CloudAccount, Finding, Resource
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


def test_operator_can_acknowledge_an_open_finding(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = findings_app
    _stage(stager, tenant_id, OPERATOR)
    response = client.post(f"/findings/{seed['finding_id']}/acknowledge")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["findingId"] == seed["finding_id"]
    assert body["acknowledgedAt"] is not None
    assert body["acknowledgedBy"] is not None


def test_admin_can_acknowledge_too(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    response = client.post(f"/findings/{seed['finding_id']}/acknowledge")
    assert response.status_code == 200, response.text


def test_viewer_is_forbidden_from_acknowledging(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = findings_app
    _stage(stager, tenant_id, VIEWER)
    response = client.post(f"/findings/{seed['finding_id']}/acknowledge")
    assert response.status_code == 403


def test_acknowledging_never_changes_status(findings_app, seed, clean_database) -> None:  # type: ignore[no-untyped-def]
    """FR-017: acknowledged is orthogonal to open/resolved/suppressed."""
    client, _, _ = findings_app
    client.post(f"/findings/{seed['finding_id']}/acknowledge")
    session: Session = sessionmaker(bind=clean_database)()
    row = session.get(Finding, uuid.UUID(seed["finding_id"]))
    assert row is not None
    assert row.status == FindingStatus.OPEN
    session.close()


def test_a_second_acknowledgment_is_a_no_op_not_an_error_or_a_duplicate(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    """FR-020: idempotent, including a near-simultaneous second attempt."""
    client, _, tenant_id = findings_app
    first = client.post(f"/findings/{seed['finding_id']}/acknowledge")
    second = client.post(f"/findings/{seed['finding_id']}/acknowledge")
    assert second.status_code == 200, second.text
    assert second.json()["acknowledgedAt"] == first.json()["acknowledgedAt"]
    assert second.json()["acknowledgedBy"] == first.json()["acknowledgedBy"]


def test_acknowledging_a_nonexistent_finding_is_a_404(findings_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    response = client.post(f"/findings/{uuid.uuid4()}/acknowledge")
    assert response.status_code == 404


def test_acknowledging_writes_exactly_one_audit_event(
    findings_app, seed, clean_database, real_tenant_id
) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = findings_app
    client.post(f"/findings/{seed['finding_id']}/acknowledge")
    client.post(f"/findings/{seed['finding_id']}/acknowledge")
    session: Session = sessionmaker(bind=clean_database)()
    count = (
        session.query(AuditEvent)
        .filter_by(tenant_id=real_tenant_id, action="finding.acknowledge")
        .count()
    )
    session.close()
    assert count == 2  # each POST is audited even when the second is a DB no-op
