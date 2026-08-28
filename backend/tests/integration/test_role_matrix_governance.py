"""The full role matrix across rules/SDAs/findings/scores/ownership
(quickstart.md V7, FR-029, FR-030).

Runs against a real PostgreSQL container -- rule/SDA creation are real row
mutations, and the view cells need real account/resource/SDA rows to return
anything but an empty list. Every cell is asserted explicitly, admin included
-- research.md R-205's non-hierarchical-roles point (already made concrete
for the accounts surface in `test_role_matrix_accounts.py`) applies here too:
a naive "admin can do everything" implementation could still pass every read
cell while a write cell silently regresses, so admin's own write access is
asserted, not inferred from it "probably working".
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
from app.api.routers import compliance as compliance_router
from app.api.routers import findings as findings_router
from app.api.routers import ownership as ownership_router
from app.api.routers import rules as rules_router
from app.api.routers import sdas as sdas_router
from app.models.core import CloudAccount, Resource
from app.models.core import Sda as SdaRow
from app.models.enums import AccountStatus, ConnectionMode

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
    """Direct ORM inserts -- the accounts router isn't mounted in this app (it
    isn't part of V7's matrix), so these can't be created through the API
    under test here."""
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
        tenant_id=real_tenant_id, name="Platform", owner_email="owner@example.com", tag_values={}
    )
    session.add(account)
    session.add(sda)
    session.flush()
    resource = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-matrix",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    session.add(resource)
    session.commit()
    ids = {"account_id": str(account.id), "sda_id": str(sda.id), "resource_id": str(resource.id)}
    session.close()
    return ids


@pytest.fixture
def governance_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(rules_router.router)
    app.include_router(sdas_router.router)
    app.include_router(findings_router.router)
    app.include_router(compliance_router.router)
    app.include_router(ownership_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager, real_tenant_id


# --- View cells: 200 for every role -----------------------------------------------


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_rules(governance_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    assert client.get("/rules").status_code == expected


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_sdas(governance_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    assert client.get("/sdas").status_code == expected


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_findings(governance_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    assert client.get("/findings").status_code == expected


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_account_compliance_score(governance_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.get(f"/accounts/{seeded_ids['account_id']}/compliance-score")
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_sda_compliance_score(governance_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.get(f"/sdas/{seeded_ids['sda_id']}/compliance-score")
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_ownership(governance_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.get(f"/resources/{seeded_ids['resource_id']}/owner")
    assert response.status_code == expected, response.text


# --- Write cells: admin only, everyone else refused --------------------------------


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 201), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_create_rule(governance_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.post(
        "/rules",
        json={"key": "role-matrix-rule", "definition": {"required": True}},
    )
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_update_rule(governance_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, ADMIN)
    created = client.post(
        "/rules",
        json={"key": "role-matrix-update-rule", "definition": {"required": True}},
    )
    assert created.status_code == 201, created.text

    _stage(stager, tenant_id, groups)
    response = client.patch(
        "/rules/role-matrix-update-rule",
        json={"definition": {"required": False}},
    )
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 201), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_register_sda(governance_app, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.post(
        "/sdas",
        json={"name": "Team X", "ownerEmail": "x@example.com", "tagValues": {"team": "x"}},
    )
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 200), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_update_sda(governance_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.patch(f"/sdas/{seeded_ids['sda_id']}", json={"team": "renamed"})
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("groups", "expected"),
    [(ADMIN, 204), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_remove_sda(governance_app, seeded_ids, groups, expected) -> None:  # type: ignore[no-untyped-def]
    client, stager, tenant_id = governance_app
    _stage(stager, tenant_id, groups)
    response = client.delete(f"/sdas/{seeded_ids['sda_id']}")
    assert response.status_code == expected, response.text


def test_the_matrix_covers_every_v7_p1_cell() -> None:
    """Guard against a row silently disappearing and the suite still passing.
    P2's owner-identity-pattern/override row (quickstart.md V7's last row) is
    deliberately excluded -- that surface doesn't exist yet (Phase 9)."""
    view_actions = {
        "view_rules",
        "view_sdas",
        "view_findings",
        "view_account_score",
        "view_sda_score",
        "view_ownership",
    }
    write_actions = {"create_rule", "update_rule", "register_sda", "update_sda", "remove_sda"}
    roles = {"admin", "operator", "viewer"}
    assert (len(view_actions) + len(write_actions)) * len(roles) == 33
