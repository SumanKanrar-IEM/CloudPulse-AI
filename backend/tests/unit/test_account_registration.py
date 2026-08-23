"""Registration input validation (FR-001, FR-002, FR-006).

Schema- and router-level checks that never reach the database, so this stays a unit
test: `extra="forbid"` rejecting an access-key field, connection-mode validation, and
the assume_role-mode required-field check `register_account` raises before opening any
DB session. The full round trip (duplicate detection, success, audit writes) is
`tests/integration/test_cross_account_verification.py` (T013) -- it needs a real
database.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers.accounts import AccountCreate, router


class _ClaimStager:
    """Stage JWT claims the way the API Gateway authorizer would (test_role_matrix.py)."""

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


def _as_admin(
    stager: _ClaimStager, tenant_id: str = "11111111-1111-1111-1111-111111111111"
) -> None:
    stager.claims = {
        "sub": "admin-subject",
        "email": "admin@example.com",
        "cognito:groups": ["cloudpulse-admins"],
        "custom:tenant_id": tenant_id,
    }


# --- FR-001: an access key is refused as input, not merely unverified --------------


def test_access_key_field_is_rejected_by_the_schema_not_silently_dropped() -> None:
    with pytest.raises(ValidationError, match="accessKeyId"):
        AccountCreate.model_validate(
            {
                "connectionMode": "assume_role",
                "scanRegions": ["us-east-1"],
                "accessKeyId": "not-a-real-access-key-id",
            }
        )


def test_access_key_via_http_is_a_422_not_a_201(
    accounts_app: tuple[TestClient, _ClaimStager],
) -> None:
    client, stager = accounts_app
    _as_admin(stager)
    response = client.post(
        "/accounts",
        json={
            "connectionMode": "local",
            "scanRegions": ["us-east-1"],
            "accessKeyId": "not-a-real-access-key-id",
        },
    )
    assert response.status_code == 422


# --- Connection-mode validation -----------------------------------------------------


def test_unknown_connection_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AccountCreate.model_validate({"connectionMode": "api_key", "scanRegions": ["us-east-1"]})


@pytest.mark.parametrize("mode", ["local", "assume_role"])
def test_the_two_accepted_connection_modes_validate(mode: str) -> None:
    account = AccountCreate.model_validate({"connectionMode": mode, "scanRegions": ["us-east-1"]})
    assert account.connection_mode.value == mode


# --- assume_role requires awsAccountId, roleArn, externalId (checked by the router) -


def test_assume_role_missing_role_arn_is_refused_before_any_db_access(
    accounts_app: tuple[TestClient, _ClaimStager],
) -> None:
    client, stager = accounts_app
    _as_admin(stager)
    response = client.post(
        "/accounts",
        json={
            "connectionMode": "assume_role",
            "awsAccountId": "123456789012",
            "scanRegions": ["us-east-1"],
            # roleArn and externalId both omitted
        },
    )
    assert response.status_code == 422
    assert "assume_role" in response.json()["error"]["message"]


def test_operator_cannot_register(accounts_app: tuple[TestClient, _ClaimStager]) -> None:
    """FR-011a: registration is admin-only."""
    client, stager = accounts_app
    stager.claims = {
        "sub": "op-subject",
        "email": "op@example.com",
        "cognito:groups": ["cloudpulse-operators"],
        "custom:tenant_id": "11111111-1111-1111-1111-111111111111",
    }
    response = client.post(
        "/accounts", json={"connectionMode": "local", "scanRegions": ["us-east-1"]}
    )
    assert response.status_code == 403


def test_viewer_cannot_register(accounts_app: tuple[TestClient, _ClaimStager]) -> None:
    client, stager = accounts_app
    stager.claims = {
        "sub": "v-subject",
        "email": "v@example.com",
        "cognito:groups": ["cloudpulse-viewers"],
        "custom:tenant_id": "11111111-1111-1111-1111-111111111111",
    }
    response = client.post(
        "/accounts", json={"connectionMode": "local", "scanRegions": ["us-east-1"]}
    )
    assert response.status_code == 403
