"""`GET/POST/PATCH /rules` (FR-001-FR-006, FR-029, FR-030).

Moved from tests/unit/ to tests/integration/ per tasks.md T004's own note -- the same
class of deviation already documented for T039/T052/T057 in spec 002 and T057 in spec
003's own tasks.md history: confirming the five seeded rules exist with the exact
required/not-required split needs a genuinely migrated database (migration 0010's
seed data), not a mocked session. Role-gating negative cases (403) are proven here
too rather than split into a separate unit file, since every case in this file
already needs the real DB for the 200 cases anyway.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import rules as rules_router

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]

SEEDED_REQUIRED = {"project_name", "owner", "project_id", "created_by"}
SEEDED_NOT_REQUIRED = {"environment"}


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
def rules_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(rules_router.router)
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


def test_seeded_rules_match_fr003_exactly(
    rules_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    client, stager, tenant_id = rules_app
    _stage(stager, tenant_id, VIEWER)
    response = client.get("/rules")
    assert response.status_code == 200, response.text
    rules = {r["key"]: r for r in response.json()["rules"]}
    assert set(rules) == SEEDED_REQUIRED | SEEDED_NOT_REQUIRED
    for key in SEEDED_REQUIRED:
        assert rules[key]["definition"]["required"] is True
        assert rules[key]["version"] == 1
        assert rules[key]["enabled"] is True
    for key in SEEDED_NOT_REQUIRED:
        assert rules[key]["definition"]["required"] is False


@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_rules(
    rules_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    groups: list[str],
    expected_status: int,
) -> None:
    """FR-030: all three roles can view."""
    client, stager, tenant_id = rules_app
    _stage(stager, tenant_id, groups)
    assert client.get("/rules").status_code == expected_status


@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 201), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_create_rule(
    rules_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    groups: list[str],
    expected_status: int,
) -> None:
    """FR-029: only admin can create a rule."""
    client, stager, tenant_id = rules_app
    _stage(stager, tenant_id, groups)
    response = client.post(
        "/rules",
        json={
            "key": "cost_center",
            "definition": {
                "required": True,
                "allowedValues": None,
                "formatPattern": None,
                "severity": "medium",
            },
        },
    )
    assert response.status_code == expected_status, response.text


def test_create_rule_rejects_unrecognized_fields(
    rules_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """`extra='forbid'`-style structural rejection, matching AccountCreate's
    precedent for keeping the request shape honest."""
    client, stager, tenant_id = rules_app
    _stage(stager, tenant_id, ADMIN)
    response = client.post(
        "/rules",
        json={
            "key": "cost_center",
            "definition": {"required": True, "severity": "medium"},
            "notARealField": "x",
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 200), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_update_rule(
    rules_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    groups: list[str],
    expected_status: int,
) -> None:
    """FR-029: only admin can edit a rule."""
    client, stager, tenant_id = rules_app
    _stage(stager, tenant_id, groups)
    response = client.patch(
        "/rules/owner",
        json={
            "definition": {
                "required": True,
                "allowedValues": None,
                "formatPattern": "^[a-z]+@example\\.com$",
                "severity": "high",
            }
        },
    )
    assert response.status_code == expected_status, response.text


def test_update_rule_creates_new_version_under_same_key(
    rules_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-006, research.md R-301: an edit is a new version, not a mutation."""
    client, stager, tenant_id = rules_app
    _stage(stager, tenant_id, ADMIN)
    response = client.patch(
        "/rules/owner",
        json={
            "definition": {
                "required": True,
                "allowedValues": None,
                "formatPattern": None,
                "severity": "high",
            }
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["key"] == "owner"
    assert body["version"] == 2

    listing = client.get("/rules").json()["rules"]
    owner_rules = [r for r in listing if r["key"] == "owner"]
    assert len(owner_rules) == 1  # only the current version is listed
    assert owner_rules[0]["version"] == 2
