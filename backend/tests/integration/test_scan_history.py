"""`GET /accounts/{id}/scans` retrieves scan history (FR-033, T058).

Runs against a real PostgreSQL container, not tests/unit -- like T039/T052 before
it, retrieving trigger/timing/counts/outcome accurately depends on real row
persistence and ordering, not something a mocked session should stand in for
(tasks.md documents this same class of deviation for test_scan_diffing.py and
test_role_matrix_accounts.py). Scan rows are inserted directly via the ORM rather
than through `start_scan`/`finalize_scan`, since this endpoint's own job is only to
read back whatever `trigger`/`status`/`started_at`/`finished_at`/`resource_count`
already exist -- it has no opinion on how they got there.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import accounts as accounts_router
from app.models.core import CloudAccount, Scan
from app.models.enums import AccountStatus, ConnectionMode, ScanStatus, ScanTrigger

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
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:  # type: ignore[no-untyped-def]
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


@pytest.fixture
def account_with_scans(
    clean_database: Engine, real_tenant_id: uuid.UUID
) -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """One account, two scans with distinct trigger/status/timing/counts -- an older
    succeeded manual scan and a newer partial scheduled one."""
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    try:
        account = CloudAccount(
            tenant_id=real_tenant_id,
            aws_account_id="123456789012",
            alias="test",
            connection_mode=ConnectionMode.LOCAL,
            scan_regions=["us-east-1"],
            status=AccountStatus.VERIFIED,
        )
        session.add(account)
        session.flush()

        now = datetime(2026, 8, 24, tzinfo=UTC)
        older = Scan(
            tenant_id=real_tenant_id,
            cloud_account_id=account.id,
            trigger=ScanTrigger.MANUAL,
            status=ScanStatus.SUCCEEDED,
            resource_count=42,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2) + timedelta(minutes=3),
        )
        newer = Scan(
            tenant_id=real_tenant_id,
            cloud_account_id=account.id,
            trigger=ScanTrigger.SCHEDULED,
            status=ScanStatus.PARTIAL,
            resource_count=17,
            started_at=now,
            finished_at=None,
        )
        session.add_all([older, newer])
        session.flush()
        session.commit()
        yield account.id, older.id, newer.id
    finally:
        session.close()


def test_scan_history_returns_trigger_timing_counts_outcome(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    account_with_scans: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    client, stager, tenant_id = accounts_app
    account_id, older_id, newer_id = account_with_scans
    _stage(stager, tenant_id, VIEWER)

    response = client.get(f"/accounts/{account_id}/scans")
    assert response.status_code == 200, response.text
    scans = response.json()["scans"]
    assert len(scans) == 2

    # Most recent first.
    assert scans[0]["id"] == str(newer_id)
    assert scans[0]["trigger"] == "scheduled"
    assert scans[0]["status"] == "partial"
    assert scans[0]["resourceCount"] == 17
    assert scans[0]["finishedAt"] is None

    assert scans[1]["id"] == str(older_id)
    assert scans[1]["trigger"] == "manual"
    assert scans[1]["status"] == "succeeded"
    assert scans[1]["resourceCount"] == 42
    assert scans[1]["startedAt"]
    assert scans[1]["finishedAt"]


@pytest.mark.parametrize(
    "groups",
    [ADMIN, OPERATOR, VIEWER],
    ids=["admin", "operator", "viewer"],
)
def test_scan_history_readable_by_every_role(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    account_with_scans: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    groups: list[str],
) -> None:
    """FR-033/FR-010a: scan history is as open to view as the accounts list itself."""
    client, stager, tenant_id = accounts_app
    account_id, _older_id, _newer_id = account_with_scans
    _stage(stager, tenant_id, groups)
    assert client.get(f"/accounts/{account_id}/scans").status_code == 200


def test_scan_history_404s_for_an_unknown_account(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
) -> None:
    client, stager, tenant_id = accounts_app
    _stage(stager, tenant_id, VIEWER)
    response = client.get(f"/accounts/{uuid.uuid4()}/scans")
    assert response.status_code == 404


def test_scan_history_is_an_empty_list_not_an_error_for_an_account_with_no_scans(
    accounts_app: tuple[TestClient, _ClaimStager, uuid.UUID],
    clean_database: Engine,
    real_tenant_id: uuid.UUID,
) -> None:
    client, stager, tenant_id = accounts_app
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    try:
        account = CloudAccount(
            tenant_id=real_tenant_id,
            aws_account_id="999999999999",
            alias="never-scanned",
            connection_mode=ConnectionMode.LOCAL,
            scan_regions=["us-east-1"],
            status=AccountStatus.VERIFIED,
        )
        session.add(account)
        session.flush()
        session.commit()
        account_id = account.id
    finally:
        session.close()

    _stage(stager, tenant_id, VIEWER)
    response = client.get(f"/accounts/{account_id}/scans")
    assert response.status_code == 200
    assert response.json()["scans"] == []
