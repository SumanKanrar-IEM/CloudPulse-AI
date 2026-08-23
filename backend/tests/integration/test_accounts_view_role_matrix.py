"""The accounts admin surface's role matrix and status transitions (FR-010a, FR-011a,
FR-009a, FR-009b, FR-009c, SC-008).

Runs against a real PostgreSQL container: status transitions and the
still-a-duplicate-when-disabled check are real row mutations and a real query, not
something a mocked session should stand in for.
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


def _register_local(client: TestClient, stager: _ClaimStager, tenant_id: uuid.UUID) -> str:
    _stage(stager, tenant_id, ["cloudpulse-admins"])
    response = client.post(
        "/accounts", json={"connectionMode": "local", "scanRegions": ["us-east-1"]}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@mock_aws
@pytest.mark.parametrize(
    "groups", [["cloudpulse-admins"], ["cloudpulse-operators"], ["cloudpulse-viewers"]]
)
def test_all_three_roles_can_view(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID], groups: list[str]
) -> None:
    """FR-010a: viewing is not restricted like the state-changing actions are."""
    client, stager, tenant_id = accounts_app
    account_id = _register_local(client, stager, tenant_id)

    _stage(stager, tenant_id, groups)
    response = client.get("/accounts")
    assert response.status_code == 200
    assert any(a["id"] == account_id for a in response.json()["accounts"])


@mock_aws
def test_deactivate_then_reactivate_round_trip(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-009a/FR-009c/SC-008: verified -> disabled -> verified, no re-registration."""
    client, stager, tenant_id = accounts_app
    account_id = _register_local(client, stager, tenant_id)

    _stage(stager, tenant_id, ["cloudpulse-admins"])
    deactivated = client.post(f"/accounts/{account_id}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "disabled"

    reactivated = client.post(f"/accounts/{account_id}/reactivate")
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "verified"


@mock_aws
def test_reactivating_an_already_active_account_is_refused(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    client, stager, tenant_id = accounts_app
    account_id = _register_local(client, stager, tenant_id)

    _stage(stager, tenant_id, ["cloudpulse-admins"])
    response = client.post(f"/accounts/{account_id}/reactivate")
    assert response.status_code == 409


@mock_aws
def test_duplicate_registration_still_refused_while_deactivated(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-009c's own text: a duplicate registration attempt against a *deactivated*
    account must still be refused as a duplicate, identifying the existing record --
    the fix is reactivation, not a second registration."""
    client, stager, tenant_id = accounts_app
    account_id = _register_local(client, stager, tenant_id)

    _stage(stager, tenant_id, ["cloudpulse-admins"])
    assert client.post(f"/accounts/{account_id}/deactivate").status_code == 200

    duplicate = client.post(
        "/accounts", json={"connectionMode": "local", "scanRegions": ["us-west-2"]}
    )
    assert duplicate.status_code == 409
    assert "already registered" in duplicate.json()["error"]["message"]


@mock_aws
def test_region_edit_takes_effect_immediately_in_the_record(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-008: no re-registration needed for a region-list change."""
    client, stager, tenant_id = accounts_app
    account_id = _register_local(client, stager, tenant_id)

    _stage(stager, tenant_id, ["cloudpulse-admins"])
    response = client.patch(
        f"/accounts/{account_id}", json={"scanRegions": ["eu-west-1", "ap-southeast-1"]}
    )
    assert response.status_code == 200
    assert response.json()["scanRegions"] == ["eu-west-1", "ap-southeast-1"]
