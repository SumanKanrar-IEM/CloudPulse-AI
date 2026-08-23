"""Role-gating for deactivate/reactivate/region-edit (FR-009a, FR-009c, FR-011a).

Stays a unit test the same way test_account_registration.py does: `require_admin`
raises 403 as a FastAPI dependency, before the handler body ever opens a DB session,
so no real database is needed to prove non-admin roles are refused. The actual status
transitions (`verified` <-> `disabled`), and duplicate-registration still applying to
a deactivated account, need a real database and are in
tests/integration/test_accounts_view_role_matrix.py (T020) instead.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers.accounts import router

SOME_ACCOUNT_ID = str(uuid.uuid4())


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
def accounts_app() -> tuple[TestClient, _ClaimStager]:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager


def _stage(stager: _ClaimStager, groups: list[str]) -> None:
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": groups,
        "custom:tenant_id": "11111111-1111-1111-1111-111111111111",
    }


@pytest.mark.parametrize("groups", [["cloudpulse-operators"], ["cloudpulse-viewers"]])
def test_deactivate_refused_for_non_admin(
    accounts_app: tuple[TestClient, _ClaimStager], groups: list[str]
) -> None:
    """FR-009a/FR-011a: deactivation is admin-only."""
    client, stager = accounts_app
    _stage(stager, groups)
    response = client.post(f"/accounts/{SOME_ACCOUNT_ID}/deactivate")
    assert response.status_code == 403


@pytest.mark.parametrize("groups", [["cloudpulse-operators"], ["cloudpulse-viewers"]])
def test_reactivate_refused_for_non_admin(
    accounts_app: tuple[TestClient, _ClaimStager], groups: list[str]
) -> None:
    """FR-009c/FR-011a: reactivation is admin-only."""
    client, stager = accounts_app
    _stage(stager, groups)
    response = client.post(f"/accounts/{SOME_ACCOUNT_ID}/reactivate")
    assert response.status_code == 403


@pytest.mark.parametrize("groups", [["cloudpulse-operators"], ["cloudpulse-viewers"]])
def test_region_edit_refused_for_non_admin(
    accounts_app: tuple[TestClient, _ClaimStager], groups: list[str]
) -> None:
    """FR-008/FR-011a: editing the region list is admin-only."""
    client, stager = accounts_app
    _stage(stager, groups)
    response = client.patch(f"/accounts/{SOME_ACCOUNT_ID}", json={"scanRegions": ["us-east-1"]})
    assert response.status_code == 403
