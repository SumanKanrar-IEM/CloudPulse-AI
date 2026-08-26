"""`GET/POST/PATCH/DELETE /sdas` and `GET /sdas/unmatched-resources`
(FR-007-FR-010b, FR-029, FR-030).

Moved from tests/unit/ to tests/integration/ per the same precedent
test_rules_api.py already established (T004): a 200-path role-gating assertion
needs real rows to serialize, and this file's positive cases all need a genuinely
migrated database anyway, so there is no lighter-weight split worth keeping
separate.
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
from app.api.routers import sdas as sdas_router

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
def sdas_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(sdas_router.router)
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


@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 200), (OPERATOR, 200), (VIEWER, 200)],
    ids=["admin", "operator", "viewer"],
)
def test_view_sdas(
    sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID], groups: list[str], expected_status: int
) -> None:
    """FR-030."""
    client, stager, tenant_id = sdas_app
    _stage(stager, tenant_id, groups)
    assert client.get("/sdas").status_code == expected_status


@pytest.mark.parametrize(
    ("groups", "expected_status"),
    [(ADMIN, 201), (OPERATOR, 403), (VIEWER, 403)],
    ids=["admin", "operator", "viewer"],
)
def test_register_sda(
    sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID], groups: list[str], expected_status: int
) -> None:
    """FR-029: only admin can register."""
    client, stager, tenant_id = sdas_app
    _stage(stager, tenant_id, groups)
    response = client.post(
        "/sdas",
        json={"name": "platform", "ownerEmail": "a@example.com", "tagValues": {"team": "platform"}},
    )
    assert response.status_code == expected_status, response.text


def test_register_sda_rejects_unrecognized_fields(
    sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    client, stager, tenant_id = sdas_app
    _stage(stager, tenant_id, ADMIN)
    response = client.post(
        "/sdas",
        json={
            "name": "platform",
            "ownerEmail": "a@example.com",
            "tagValues": {"team": "platform"},
            "notARealField": "x",
        },
    )
    assert response.status_code == 422, response.text


class TestOverlapDetection:
    """research.md R-305: identical mappings and the subset case are both
    refused, not just literal duplicates (FR-010a)."""

    def test_identical_mapping_is_refused(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        first = client.post(
            "/sdas",
            json={
                "name": "platform-a",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/sdas",
            json={
                "name": "platform-b",
                "ownerEmail": "b@example.com",
                "tagValues": {"team": "platform"},
            },
        )
        assert second.status_code == 409, second.text

    def test_subset_mapping_is_refused(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        """`{team: platform}` vs. `{team: platform, env: prod}` -- not literal
        duplicates, but a resource satisfying the more specific one also
        satisfies the broader one."""
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        broad = client.post(
            "/sdas",
            json={
                "name": "platform",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        )
        assert broad.status_code == 201, broad.text
        specific = client.post(
            "/sdas",
            json={
                "name": "platform-prod",
                "ownerEmail": "b@example.com",
                "tagValues": {"team": "platform", "env": "prod"},
            },
        )
        assert specific.status_code == 409, specific.text

    def test_disjoint_valued_mapping_is_allowed(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        """A genuinely different value for a shared key is not ambiguous -- a
        resource's `team` tag cannot equal both `platform` and `data`."""
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        first = client.post(
            "/sdas",
            json={
                "name": "platform",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/sdas",
            json={"name": "data", "ownerEmail": "b@example.com", "tagValues": {"team": "data"}},
        )
        assert second.status_code == 201, second.text

    def test_edit_that_would_overlap_another_sda_is_refused(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        client.post(
            "/sdas",
            json={
                "name": "platform",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        )
        second = client.post(
            "/sdas",
            json={"name": "data", "ownerEmail": "b@example.com", "tagValues": {"team": "data"}},
        ).json()
        response = client.patch(f"/sdas/{second['id']}", json={"tagValues": {"team": "platform"}})
        assert response.status_code == 409, response.text

    def test_edit_that_does_not_change_the_mapping_is_not_refused_against_itself(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        """An SDA's own existing mapping must not be compared against itself."""
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        created = client.post(
            "/sdas",
            json={
                "name": "platform",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        ).json()
        response = client.patch(f"/sdas/{created['id']}", json={"team": "core-platform"})
        assert response.status_code == 200, response.text


class TestRemoval:
    """FR-010b: removal is never refused for having attached resources, and
    reverts them immediately."""

    def test_remove_sda_with_no_resources_succeeds(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        created = client.post(
            "/sdas",
            json={
                "name": "platform",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        ).json()
        response = client.delete(f"/sdas/{created['id']}")
        assert response.status_code == 204, response.text
        assert client.get("/sdas").json()["sdas"] == []

    @pytest.mark.parametrize(
        ("groups", "expected_status"),
        [(ADMIN, 204), (OPERATOR, 403), (VIEWER, 403)],
        ids=["admin", "operator", "viewer"],
    )
    def test_remove_sda_role_gating(
        self,
        sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID],
        groups: list[str],
        expected_status: int,
    ) -> None:
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        created = client.post(
            "/sdas",
            json={
                "name": "platform",
                "ownerEmail": "a@example.com",
                "tagValues": {"team": "platform"},
            },
        ).json()
        _stage(stager, tenant_id, groups)
        response = client.delete(f"/sdas/{created['id']}")
        assert response.status_code == expected_status, response.text

    def test_remove_unknown_sda_404s(
        self, sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID]
    ) -> None:
        client, stager, tenant_id = sdas_app
        _stage(stager, tenant_id, ADMIN)
        response = client.delete(f"/sdas/{uuid.uuid4()}")
        assert response.status_code == 404, response.text


def test_unmatched_resources_endpoint_is_readable_by_every_role(
    sdas_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-009/FR-012, FR-030."""
    client, stager, tenant_id = sdas_app
    for groups in (ADMIN, OPERATOR, VIEWER):
        _stage(stager, tenant_id, groups)
        assert client.get("/sdas/unmatched-resources").status_code == 200
