"""The full role matrix (SC-008, FR-033a, FR-034).

SC-008 requires **six** caller kinds against admin, operator and read-only actions, with
100% of cells producing the expected allow or refuse.

The last two rows — no mapped group, and multiple mapped groups — are the ones that
matter. The first four would pass with a naive implementation that picks the first group
it recognises; only these two catch it. That is why FR-032a spells out the refusal
instead of leaving it to judgement.

Runs against a real PostgreSQL container because `/me` performs a just-in-time
`app_user` insert, and a mocked session would not exercise the tenant stamping.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.core.config import Role
from app.core.security import (
    GROUPS_CLAIM, Principal, get_principal,
    require_admin, require_operator, require_viewer,
)

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]
NO_MAPPED_GROUP = ["some-unrelated-group"]
MULTIPLE_GROUPS = ["cloudpulse-admins", "cloudpulse-viewers"]


class _ClaimStager:
    """Stage JWT claims the way the API Gateway authorizer would."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.claims: dict[str, Any] | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


@pytest.fixture
def tenant_id(clean_database: Engine, alembic_config) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def matrix_app(tenant_id: uuid.UUID) -> tuple[TestClient, _ClaimStager]:
    """One route per privilege level, wired through the real dependencies."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    @app.get("/admin-action")
    async def _admin(p: Principal = Depends(require_admin)) -> dict[str, str]:
        return {"role": p.role.value}

    @app.get("/operator-action")
    async def _operator(p: Principal = Depends(require_operator)) -> dict[str, str]:
        return {"role": p.role.value}

    @app.get("/read-only-action")
    async def _viewer(p: Principal = Depends(require_viewer)) -> dict[str, str]:
        return {"role": p.role.value}

    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    client.base_url = client.base_url  # noqa: PLW0127 - keep httpx happy
    return client, stager


def _call(
    matrix_app: tuple[TestClient, _ClaimStager],
    path: str,
    groups: list[str] | None,
    *,
    authenticated: bool = True,
    tenant_id: uuid.UUID | None = None,
) -> int:
    client, stager = matrix_app
    if not authenticated:
        stager.claims = None
    else:
        claims: dict[str, Any] = {"sub": "test-subject", "email": "t@example.com"}
        if groups is not None:
            claims[GROUPS_CLAIM] = groups
        if tenant_id:
            claims["custom:tenant_id"] = str(tenant_id)
        stager.claims = claims
    return client.get(path).status_code


# --- SC-008: six caller kinds x three action kinds = 18 cells ---------------

MATRIX: list[tuple[str, list[str] | None, bool, dict[str, int]]] = [
    # (label, groups, authenticated, {path: expected status})
    ("unauthenticated", None, False, {"admin": 401, "operator": 401, "read": 401}),
    ("viewer",          VIEWER,          True,  {"admin": 403, "operator": 403, "read": 200}),
    ("operator",        OPERATOR,        True,  {"admin": 403, "operator": 200, "read": 200}),
    ("admin",           ADMIN,           True,  {"admin": 200, "operator": 200, "read": 200}),
    # The two that catch a naive implementation:
    ("no mapped group", NO_MAPPED_GROUP, True,  {"admin": 403, "operator": 403, "read": 403}),
    ("multiple groups", MULTIPLE_GROUPS, True,  {"admin": 403, "operator": 403, "read": 403}),
]

PATHS = {"admin": "/admin-action", "operator": "/operator-action", "read": "/read-only-action"}


@pytest.mark.parametrize(
    ("label", "groups", "authenticated", "expected"),
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_role_matrix(
    matrix_app: tuple[TestClient, _ClaimStager],
    tenant_id: uuid.UUID,
    label: str,
    groups: list[str] | None,
    authenticated: bool,
    expected: dict[str, int],
) -> None:
    """SC-008: 100% of cells produce the expected allow or refuse."""
    for action, want in expected.items():
        got = _call(
            matrix_app, PATHS[action], groups,
            authenticated=authenticated, tenant_id=tenant_id,
        )
        assert got == want, f"{label} -> {action}: expected {want}, got {got}"


def test_no_governance_data_reaches_a_caller_without_a_resolved_role(
    matrix_app: tuple[TestClient, _ClaimStager], tenant_id: uuid.UUID
) -> None:
    """SC-008: 'zero governance data returned to any caller lacking a resolved role'."""
    client, stager = matrix_app
    for groups in (NO_MAPPED_GROUP, MULTIPLE_GROUPS, []):
        stager.claims = {
            "sub": "s", "email": "e@x.y", GROUPS_CLAIM: groups,
            "custom:tenant_id": str(tenant_id),
        }
        response = client.get(PATHS["read"])
        assert response.status_code == 403
        assert "role" not in response.text
        assert str(tenant_id) not in response.text


def test_refusals_are_indistinguishable_between_no_group_and_many(
    matrix_app: tuple[TestClient, _ClaimStager], tenant_id: uuid.UUID
) -> None:
    """A caller should not learn its own group cardinality from the error body."""
    client, stager = matrix_app
    bodies = []
    for groups in (NO_MAPPED_GROUP, MULTIPLE_GROUPS):
        stager.claims = {
            "sub": "s", "email": "e@x.y", GROUPS_CLAIM: groups,
            "custom:tenant_id": str(tenant_id),
        }
        body = client.get(PATHS["read"]).json()["error"]
        body.pop("correlationId")
        bodies.append(body)
    assert bodies[0] == bodies[1]


def test_the_matrix_covers_every_caller_kind_sc008_names() -> None:
    """Guard against a row being deleted and the suite still passing."""
    labels = {row[0] for row in MATRIX}
    assert labels == {
        "unauthenticated", "viewer", "operator", "admin",
        "no mapped group", "multiple groups",
    }
    assert len(MATRIX) * len(PATHS) == 18
