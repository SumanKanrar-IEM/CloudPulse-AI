"""The full SC-009 three-role matrix for the accounts surface (quickstart.md V9).

Runs against a real PostgreSQL container -- register/deactivate/reactivate are real
row mutations. The cell this test exists for is "admin refused triggering an
on-demand scan": a naive "admin can do everything" implementation passes every other
cell in this matrix while silently getting that one wrong (research.md R-205's
non-hierarchical-roles point, made concrete, exactly as quickstart.md V9 warns).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import Engine, text

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import accounts as accounts_router

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


@pytest.fixture
def real_tenant_id(clean_database: Engine, alembic_config) -> uuid.UUID:  # type: ignore[no-untyped-def]
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def accounts_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    monkeypatch.setenv(
        "CLOUDPULSE_SCAN_STATE_MACHINE_ARN",
        "arn:aws:states:us-east-1:123456789012:stateMachine:test",
    )
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(accounts_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager, real_tenant_id


def _stage(stager: _ClaimStager, tenant_id: uuid.UUID, groups: list[str]) -> None:
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": groups,
        "custom:tenant_id": str(tenant_id),
    }


@pytest.fixture
@mock_aws
def registered_account(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> tuple[TestClient, _ClaimStager, uuid.UUID, str]:
    """`@mock_aws` here too, not just on the test functions below: fixture setup
    runs BEFORE a test function's own `@mock_aws` decorator activates, so
    registration's STS/Tagging API calls would otherwise reach outside any mock
    context entirely -- found by running this file and getting a 500, not by
    inspection."""
    client, stager, tenant_id = accounts_app
    _stage(stager, tenant_id, ADMIN)
    response = client.post(
        "/accounts", json={"connectionMode": "local", "scanRegions": ["us-east-1"]}
    )
    assert response.status_code == 201, response.text
    return client, stager, tenant_id, str(response.json()["id"])


@mock_aws
@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_accounts_list(
    registered_account: tuple[TestClient, _ClaimStager, uuid.UUID, str],
    groups: list[str],
    expected_status: int,
) -> None:
    """SC-009: all three roles can view."""
    client, stager, tenant_id, _account_id = registered_account
    _stage(stager, tenant_id, groups)
    assert client.get("/accounts").status_code == expected_status


@mock_aws
@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 201), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_register_account(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    groups: list[str],
    expected_status: int,
) -> None:
    """SC-009: only admin can register."""
    client, stager, tenant_id = accounts_app
    _stage(stager, tenant_id, groups)
    response = client.post(
        "/accounts", json={"connectionMode": "local", "scanRegions": ["us-east-1"]}
    )
    assert response.status_code == expected_status


@mock_aws
@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 200), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_deactivate_account(
    registered_account: tuple[TestClient, _ClaimStager, uuid.UUID, str],
    groups: list[str],
    expected_status: int,
) -> None:
    """SC-009: only admin can deactivate."""
    client, stager, tenant_id, account_id = registered_account
    _stage(stager, tenant_id, groups)
    response = client.post(f"/accounts/{account_id}/deactivate")
    assert response.status_code == expected_status


@mock_aws
@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 200), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_reactivate_account(
    registered_account: tuple[TestClient, _ClaimStager, uuid.UUID, str],
    groups: list[str],
    expected_status: int,
) -> None:
    """SC-009: only admin can reactivate."""
    client, stager, tenant_id, account_id = registered_account
    _stage(stager, tenant_id, ADMIN)
    assert client.post(f"/accounts/{account_id}/deactivate").status_code == 200

    _stage(stager, tenant_id, groups)
    response = client.post(f"/accounts/{account_id}/reactivate")
    assert response.status_code == expected_status


def _create_scan_state_machine() -> None:
    """`registered_account`'s own `@mock_aws` context exits (and its mocked AWS
    state is torn down) the moment that fixture function returns, before the test
    body -- with its own, separate `@mock_aws` context -- ever runs. A state
    machine created during fixture setup is therefore gone by the time a test
    calls `POST /accounts/{id}/scans`; moto's `start_execution` needs the state
    machine to genuinely exist (`StateMachineDoesNotExist` otherwise, confirmed
    directly). Created fresh, inside each test's own mock context, instead."""
    import json

    import boto3

    iam = boto3.client("iam", region_name="us-east-1")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "states.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    role_arn = iam.create_role(RoleName="sfn-role", AssumeRolePolicyDocument=json.dumps(trust))[
        "Role"
    ]["Arn"]
    sfn = boto3.client("stepfunctions", region_name="us-east-1")
    sfn.create_state_machine(
        name="test",
        definition=json.dumps(
            {"StartAt": "Done", "States": {"Done": {"Type": "Pass", "End": True}}}
        ),
        roleArn=role_arn,
    )


@mock_aws
@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 403), (OPERATOR, 202), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_trigger_on_demand_scan(
    registered_account: tuple[TestClient, _ClaimStager, uuid.UUID, str],
    groups: list[str],
    expected_status: int,
) -> None:
    """SC-009's decisive cell (quickstart.md V9): admin is REFUSED here, the one a
    naive 'admin can do everything' implementation gets wrong. Only operator may
    trigger -- admin's account-management grant does not carry it (R-205)."""
    _create_scan_state_machine()
    client, stager, tenant_id, account_id = registered_account
    _stage(stager, tenant_id, groups)
    response = client.post(f"/accounts/{account_id}/scans")
    assert response.status_code == expected_status, (
        f"role={groups}: expected {expected_status}, got {response.status_code} "
        f"({response.text})"
    )


@mock_aws
def test_the_matrix_covers_every_sc009_cell() -> None:
    """Guard against a row silently disappearing and the suite still passing."""
    actions = {
        "view",
        "register",
        "deactivate",
        "reactivate",
        "trigger_scan",
    }
    roles = {"admin", "operator", "viewer"}
    # 5 actions x 3 roles = 15 cells, matching quickstart.md V9's table exactly.
    assert len(actions) * len(roles) == 15
