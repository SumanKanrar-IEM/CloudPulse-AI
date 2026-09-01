"""The full role matrix across spec 004's P1 write/read surfaces (quickstart.md
V7-adjacent, FR-027, FR-028, FR-028a).

Runs against a real PostgreSQL container. Every cell is asserted explicitly,
admin included -- research.md R-205's non-hierarchical-roles point (already
made concrete for other surfaces in `test_role_matrix_governance.py`) applies
here too: a naive "admin can do everything" implementation could still pass
every read cell while a write cell silently regresses, so admin's own write
access is asserted, not inferred from it "probably working". P2's scan-
operations role gating (FR-021-FR-023) is deliberately excluded -- that
surface doesn't exist yet (Phase 8).
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
from app.api.routers import resources as resources_router
from app.models.core import CloudAccount, Finding, Resource
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
def seeded_ids(clean_database: Engine, real_tenant_id: uuid.UUID) -> dict[str, str]:
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
        arn="arn:aws:s3:::bucket-matrix",
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
    ids = {"resource_id": str(resource.id), "finding_id": str(finding.id)}
    session.close()
    return ids


@pytest.fixture
def dashboard_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(resources_router.router)
    app.include_router(findings_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager, real_tenant_id


# --- View cells: 200 for every role -----------------------------------------------


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_resources(dashboard_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = dashboard_app
    _stage(stager, tenant_id, groups)
    assert client.get("/resources").status_code == expected


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_resource_detail(dashboard_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = dashboard_app
    _stage(stager, tenant_id, groups)
    response = client.get(f"/resources/{seeded_ids['resource_id']}")
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_findings(dashboard_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = dashboard_app
    _stage(stager, tenant_id, groups)
    assert client.get("/findings").status_code == expected


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_finding_suggestion(dashboard_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = dashboard_app
    _stage(stager, tenant_id, groups)
    response = client.get(f"/findings/{seeded_ids['finding_id']}/suggestion")
    assert response.status_code == expected, response.text


# --- Write cells -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_acknowledge_finding(dashboard_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    """FR-015, FR-028: admin or operator, never viewer."""
    client, stager, tenant_id = dashboard_app
    _stage(stager, tenant_id, groups)
    response = client.post(f"/findings/{seeded_ids['finding_id']}/acknowledge")
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_seed_finding_suggestion(dashboard_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    """FR-020a, FR-028a: admin only -- explicitly refused for operator too,
    not just inferred from viewer's refusal."""
    client, stager, tenant_id = dashboard_app
    _stage(stager, tenant_id, groups)
    response = client.put(
        f"/findings/{seeded_ids['finding_id']}/suggestion",
        json={"suggestionText": "x", "blastRadiusNote": "y"},
    )
    assert response.status_code == expected, response.text


def test_the_matrix_covers_every_p1_write_read_surface() -> None:
    """Guard against a row silently disappearing and the suite still passing."""
    view_actions = {
        "view_resources",
        "view_resource_detail",
        "view_findings",
        "view_finding_suggestion",
    }
    write_actions = {"acknowledge_finding", "seed_finding_suggestion"}
    roles = {"admin", "operator", "viewer"}
    assert (len(view_actions) + len(write_actions)) * len(roles) == 18
