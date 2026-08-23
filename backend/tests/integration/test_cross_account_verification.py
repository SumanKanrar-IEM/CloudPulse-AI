"""Cross-account registration end to end (FR-003, FR-007, FR-009, SC-004).

Runs against a real PostgreSQL container -- registration writes `cloud_account` and
`audit_event` rows and the duplicate check (FR-009) is a real query, not something a
mocked session should stand in for. AWS calls (STS AssumeRole, Resource Groups
Tagging API, Secrets Manager) are moto-mocked (FR-010): no real credentials, no real
account touched.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import boto3
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

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


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
    # Point tenant_session at the Testcontainers engine directly, bypassing
    # Settings/Secrets Manager entirely -- see module docstring.
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(accounts_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager, real_tenant_id


def _as_admin(stager: _ClaimStager, tenant_id: uuid.UUID) -> None:
    stager.claims = {
        "sub": "admin-subject",
        "email": "admin@example.com",
        "cognito:groups": ["cloudpulse-admins"],
        "custom:tenant_id": str(tenant_id),
    }


def _create_moto_scanner_role(external_id: str) -> str:
    """A real IAM role in the moto backend, trust policy embedding the ExternalId
    (FR-003) -- mirrors what an admin deploys via cross_account_template.yaml."""
    iam = boto3.client("iam", region_name="us-east-1")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::000000000000:root"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
            }
        ],
    }
    response = iam.create_role(
        RoleName="cloudpulse-scanner", AssumeRolePolicyDocument=json.dumps(trust_policy)
    )
    return str(response["Role"]["Arn"])


@mock_aws
def test_cross_account_registration_succeeds_and_is_verified_before_acceptance(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """SC-001/SC-004: verified before acceptance, using the platform-generated
    ExternalId round-tripped from POST /accounts/external-id."""
    client, stager, tenant_id = accounts_app
    _as_admin(stager, tenant_id)

    external_id_resp = client.post("/accounts/external-id")
    assert external_id_resp.status_code == 200
    external_id = external_id_resp.json()["externalId"]

    role_arn = _create_moto_scanner_role(external_id)

    response = client.post(
        "/accounts",
        json={
            "connectionMode": "assume_role",
            "awsAccountId": "222222222222",
            "roleArn": role_arn,
            "externalId": external_id,
            "scanRegions": ["us-east-1"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "verified"
    assert body["connectionMode"] == "assume_role"


@mock_aws
def test_duplicate_registration_is_refused_regardless_of_mode(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-009: the same underlying AWS account cannot be registered twice."""
    client, stager, tenant_id = accounts_app
    _as_admin(stager, tenant_id)

    external_id = client.post("/accounts/external-id").json()["externalId"]
    role_arn = _create_moto_scanner_role(external_id)

    first = client.post(
        "/accounts",
        json={
            "connectionMode": "assume_role",
            "awsAccountId": "333333333333",
            "roleArn": role_arn,
            "externalId": external_id,
            "scanRegions": ["us-east-1"],
        },
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/accounts",
        json={
            "connectionMode": "assume_role",
            "awsAccountId": "333333333333",
            "roleArn": role_arn,
            "externalId": external_id,
            "scanRegions": ["us-west-2"],
        },
    )
    assert second.status_code == 409
    assert "already registered" in second.json()["error"]["message"]


@mock_aws
def test_duplicate_detection_crosses_connection_modes(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    """FR-009 (Edge Cases): registering local, then the same underlying account
    cross-account (or vice versa), must still be refused as a duplicate."""
    client, stager, tenant_id = accounts_app
    _as_admin(stager, tenant_id)

    local = client.post("/accounts", json={"connectionMode": "local", "scanRegions": ["us-east-1"]})
    assert local.status_code == 201, local.text
    same_account_id = local.json()["awsAccountId"]

    external_id = client.post("/accounts/external-id").json()["externalId"]
    # moto's default caller identity account is 123456789012 -- the same id
    # get_local_account_id() resolved above, so this role ARN targets the same account.
    role_arn = _create_moto_scanner_role(external_id)

    duplicate = client.post(
        "/accounts",
        json={
            "connectionMode": "assume_role",
            "awsAccountId": same_account_id,
            "roleArn": role_arn,
            "externalId": external_id,
            "scanRegions": ["us-east-1"],
        },
    )
    assert duplicate.status_code == 409


@mock_aws
def test_registration_writes_an_audit_event_on_success_and_on_duplicate_refusal(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID], clean_database: Engine
) -> None:
    """FR-040: every registration attempt, accepted or refused, is audited.

    Uses the duplicate-registration refusal path (a real DB check) rather than an
    AWS-rejected role, since moto's STS mock does not enforce trust-policy/ExternalId
    validity -- it returns usable credentials for a role that was never deployed
    (confirmed empirically; matches the moto-fidelity caveat research.md R-209 flags
    for other AWS APIs). The verification-failure audit path is proven separately in
    ``test_verification_failure_is_audited`` below, by mocking `verify_registration`
    directly rather than depending on moto's STS fidelity.
    """
    client, stager, tenant_id = accounts_app
    _as_admin(stager, tenant_id)

    external_id = client.post("/accounts/external-id").json()["externalId"]
    role_arn = _create_moto_scanner_role(external_id)

    body = {
        "connectionMode": "assume_role",
        "awsAccountId": "444444444444",
        "roleArn": role_arn,
        "externalId": external_id,
        "scanRegions": ["us-east-1"],
    }
    assert client.post("/accounts", json=body).status_code == 201
    assert client.post("/accounts", json=body).status_code == 409  # duplicate -- refused

    with clean_database.connect() as conn:
        actions = [
            row[0]
            for row in conn.execute(
                text("SELECT action FROM audit_event WHERE target_type = 'cloud_account'")
            )
        ]
    assert "account.register.succeeded" in actions
    assert "account.register.refused" in actions


@mock_aws
def test_verification_failure_is_audited(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    clean_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-040, distinct from the duplicate path: a verification failure is audited too."""
    from app.scan.verification import VerificationError

    client, stager, tenant_id = accounts_app
    _as_admin(stager, tenant_id)

    def _always_fails(*_args: object, **_kwargs: object) -> None:
        raise VerificationError("no_usable_access", "AccessDenied")

    monkeypatch.setattr("app.api.routers.accounts.verify_registration", _always_fails)

    response = client.post(
        "/accounts",
        json={
            "connectionMode": "assume_role",
            "awsAccountId": "666666666666",
            "roleArn": "arn:aws:iam::666666666666:role/cloudpulse-scanner",
            "externalId": "some-value",
            "scanRegions": ["us-east-1"],
        },
    )
    assert response.status_code == 422

    with clean_database.connect() as conn:
        actions = [
            row[0]
            for row in conn.execute(
                text("SELECT action FROM audit_event WHERE target_type = 'cloud_account'")
            )
        ]
    assert "account.register.refused" in actions
