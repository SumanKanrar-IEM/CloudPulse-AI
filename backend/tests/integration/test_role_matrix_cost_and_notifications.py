"""The full role matrix across spec 005's P1 read surfaces (T024; S24, S25,
S39, S42, FR-003, FR-013).

Runs against a real PostgreSQL container, matching
`test_role_matrix_governance_dashboard.py`'s own reason: a role check that
passes against a mocked session proves the decorator was called, not that the
endpoint serves data to that role.

**Every cell is asserted explicitly, admin included.** Research.md R-205's
non-hierarchical-roles point: a naive "admin can do everything" implementation
could pass every other cell while admin's own silently regressed, so admin is
never inferred from viewer working.

**There is no refusal cell to assert, and that is stated rather than assumed.**
Spec 005's P1 surface is read-only -- `GET /spend`, `GET /spend/summary` and
`GET /findings/{findingId}/notifications` are the whole of it. Every write in
this spec is performed by a worker Lambda under its own IAM role, not by a
signed-in principal through the API, so there is no endpoint here that any
role should be refused. The spend *dashboard* and the notification trail are
governance data, which specs 003 and 004 already established is visible to
every role. When P2 adds a write surface (budget editing, Phase 7), that
surface brings its own refusal cells with it.
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
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import findings as findings_router
from app.api.routers import spend as spend_router
from app.models.core import CloudAccount, Notification, Resource, Rule, SpendRecord
from app.models.core import Finding as FindingRow
from app.models.core import Sda as SdaRow
from app.models.enums import (
    AccountStatus,
    ConnectionMode,
    FindingKind,
    FindingSeverity,
    FindingStatus,
    NotificationCadencePoint,
    NotificationOutcome,
)

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]
EVERY_ROLE = [ADMIN, OPERATOR, VIEWER]

SPEND_DAY = date(2026, 9, 1)
RANGE = {"from": "2026-09-01", "to": "2026-09-02"}


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
def seed(clean_database: Engine, real_tenant_id: uuid.UUID) -> dict[str, str]:
    """One spend row and one finding carrying one notification attempt --
    enough that an empty response would fail these tests rather than pass them
    by accident."""
    session: Session = sessionmaker(bind=clean_database)()
    account = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    sda = SdaRow(
        tenant_id=real_tenant_id,
        name="platform",
        owner_email="p@example.com",
        tag_values={"project_id": "proj-a"},
    )
    session.add_all([account, sda])
    session.flush()

    session.add(
        SpendRecord(
            tenant_id=real_tenant_id,
            cloud_account_id=account.id,
            sda_id=sda.id,
            service="AmazonEC2",
            spend_date=SPEND_DAY,
            amount_usd=Decimal("10.00"),
            is_gap=False,
        )
    )

    rule = session.query(Rule).filter_by(tenant_id=real_tenant_id, key="owner", version=1).one()
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
    finding = FindingRow(
        tenant_id=real_tenant_id,
        resource_id=resource.id,
        rule_id=rule.id,
        rule_version=1,
        kind=FindingKind.TAG_VIOLATION,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
    )
    session.add(finding)
    session.flush()
    session.add(
        Notification(
            tenant_id=real_tenant_id,
            finding_id=finding.id,
            cadence_point=NotificationCadencePoint.DAY_0,
            outcome=NotificationOutcome.SENT,
            recipient_email="owner@example.com",
        )
    )
    session.commit()
    ids = {"finding_id": str(finding.id), "sda_id": str(sda.id)}
    session.close()
    return ids


@pytest.fixture
def api(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(spend_router.router)
    app.include_router(findings_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager, real_tenant_id


def test_every_role_can_read_spend(api: Any, seed: dict[str, str]) -> None:
    client, stager, tenant_id = api
    for groups in EVERY_ROLE:
        _stage(stager, tenant_id, groups)
        response = client.get("/spend", params=RANGE)
        assert response.status_code == 200, (groups, response.text)
        assert len(response.json()["spend"]) == 1, groups


def test_every_role_can_read_the_spend_summary(api: Any, seed: dict[str, str]) -> None:
    client, stager, tenant_id = api
    for groups in EVERY_ROLE:
        _stage(stager, tenant_id, groups)
        response = client.get("/spend/summary", params=RANGE)
        assert response.status_code == 200, (groups, response.text)
        assert response.json()["totalUsd"] == "10.0000", groups


def test_every_role_can_read_a_findings_notification_trail(api: Any, seed: dict[str, str]) -> None:
    client, stager, tenant_id = api
    for groups in EVERY_ROLE:
        _stage(stager, tenant_id, groups)
        response = client.get(f"/findings/{seed['finding_id']}/notifications")
        assert response.status_code == 200, (groups, response.text)
        assert len(response.json()["notifications"]) == 1, groups


def test_an_unauthenticated_caller_reads_nothing(api: Any, seed: dict[str, str]) -> None:
    """The one refusal this surface does have. Staged as no claims at all --
    the state an unauthenticated request actually arrives in."""
    client, stager, _ = api
    stager.claims = None
    assert client.get("/spend", params=RANGE).status_code == 401
    assert client.get("/spend/summary", params=RANGE).status_code == 401
    assert client.get(f"/findings/{seed['finding_id']}/notifications").status_code == 401


def test_a_caller_with_no_recognised_group_reads_nothing(api: Any, seed: dict[str, str]) -> None:
    """Authenticated but ungrouped. FR-032a's cardinality rule means an empty
    group claim is not "viewer by default" -- it is no role at all."""
    client, stager, tenant_id = api
    _stage(stager, tenant_id, [])
    assert client.get("/spend", params=RANGE).status_code == 403
    assert client.get(f"/findings/{seed['finding_id']}/notifications").status_code == 403
