"""A failed account and its reason, end to end against real Postgres (US1 scenario 6,
US2 scenario 3, FR-012, T062).

The scan worker's `_handle_scan_unit` is invoked in-process (R-210's Lambda-level
fallback, as `test_governance_worker_wiring.py` does), with AssumeRole refused at
its boundary -- moto's STS never refuses (T013's note). The account row, the check
constraint, and `GET /accounts` are all real.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

import app.core.db as db_module
import handlers.scan_worker_handler as scan_worker
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import accounts as accounts_router
from connectors.aws import RoleAssumptionError

pytestmark = pytest.mark.integration

ROLE_ARN = "arn:aws:iam::222222222222:role/cloudpulse-scanner"


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
def tenant_id(
    clean_database: Engine,
    alembic_config: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


def _insert_account(engine: Engine, tenant_id: uuid.UUID, aws_account_id: str) -> uuid.UUID:
    account_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cloud_account (id, tenant_id, aws_account_id, alias, "
                "connection_mode, role_arn, scan_regions, status) VALUES (:id, :t, :a, :a, "
                "'assume_role', :r, ARRAY['us-east-1'], 'verified')"
            ),
            {"id": account_id, "t": tenant_id, "a": aws_account_id, "r": ROLE_ARN},
        )
    return account_id


def _scan_unit(tenant_id: uuid.UUID, account_id: uuid.UUID) -> dict[str, Any]:
    return scan_worker.handler(
        {
            "scan_id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "cloud_account_id": str(account_id),
            "region": "us-east-1",
        }
    )


def _row(engine: Engine, account_id: uuid.UUID) -> tuple[str, str | None]:
    with engine.connect() as conn:
        status, reason = conn.execute(
            text("SELECT status, failure_reason FROM cloud_account WHERE id = :id"),
            {"id": account_id},
        ).one()
    return str(status), reason


def _refuse_assume_role() -> Any:
    sts = MagicMock()
    sts.assume_role.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not authorized"}}, "AssumeRole"
    )
    return patch("boto3.client", return_value=sts)


def _client(tenant_id: uuid.UUID, group: str) -> TestClient:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(accounts_router.router)
    stager = _ClaimStager(app)
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": [group],
        "custom:tenant_id": str(tenant_id),
    }
    return TestClient(stager, raise_server_exceptions=False)


def test_a_role_gone_bad_marks_the_account_failed_and_get_accounts_serves_the_reason(
    clean_database: Engine, tenant_id: uuid.UUID
) -> None:
    broken = _insert_account(clean_database, tenant_id, "222222222222")
    healthy = _insert_account(clean_database, tenant_id, "333333333333")

    with _refuse_assume_role(), pytest.raises(RoleAssumptionError):
        _scan_unit(tenant_id, broken)

    # Committed despite the raise -- the unit still fails for the scan's accounting.
    status, reason = _row(clean_database, broken)
    assert status == "failed"
    assert reason is not None and ROLE_ARN in reason and "AccessDenied" in reason

    response = _client(tenant_id, "cloudpulse-viewers").get("/accounts")
    assert response.status_code == 200, response.text
    accounts = {a["id"]: a for a in response.json()["accounts"]}
    assert accounts[str(broken)]["status"] == "failed"
    assert accounts[str(broken)]["failureReason"] == reason
    assert accounts[str(healthy)]["failureReason"] is None


def test_a_later_successful_scan_restores_the_account_and_clears_the_reason(
    clean_database: Engine, tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = _insert_account(clean_database, tenant_id, "222222222222")
    with _refuse_assume_role(), pytest.raises(RoleAssumptionError):
        _scan_unit(tenant_id, account_id)
    assert _row(clean_database, account_id)[0] == "failed"

    # The admin re-deployed the template: the role assumes again.
    monkeypatch.setattr(scan_worker.discovery, "discover_account_region", lambda **_: [])
    monkeypatch.setattr(scan_worker, "_write_raw_snapshot", lambda *_: "unused")
    assert _scan_unit(tenant_id, account_id)["status"] == "succeeded"

    assert _row(clean_database, account_id) == ("verified", None)


def test_deactivating_a_failed_account_clears_its_reason(
    clean_database: Engine, tenant_id: uuid.UUID
) -> None:
    account_id = _insert_account(clean_database, tenant_id, "222222222222")
    with _refuse_assume_role(), pytest.raises(RoleAssumptionError):
        _scan_unit(tenant_id, account_id)

    response = _client(tenant_id, "cloudpulse-admins").post(f"/accounts/{account_id}/deactivate")
    assert response.status_code == 200, response.text
    assert response.json()["failureReason"] is None
    assert _row(clean_database, account_id) == ("disabled", None)


@pytest.mark.parametrize(
    ("status", "reason"), [("failed", None), ("verified", "a reason on a healthy account")]
)
def test_the_reason_is_present_exactly_when_the_account_failed(
    clean_database: Engine, tenant_id: uuid.UUID, status: str, reason: str | None
) -> None:
    account_id = _insert_account(clean_database, tenant_id, "222222222222")
    with pytest.raises(IntegrityError, match="ck_cloud_account_failure_reason_shape"):
        with clean_database.begin() as conn:
            conn.execute(
                text("UPDATE cloud_account SET status = :s, failure_reason = :r WHERE id = :id"),
                {"s": status, "r": reason, "id": account_id},
            )
