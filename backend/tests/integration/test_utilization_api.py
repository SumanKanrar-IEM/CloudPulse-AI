"""`GET /utilization` against a real database (T040; S54, S55, FR-018).

The classification itself is unit-tested (T038). What needs a real engine is
the grouping: that per-account and per-project figures partition the same
resources the overall figure counts, and that the "No SDA" bucket appears as a
project row rather than vanishing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import utilization as utilization_router
from app.models.core import CloudAccount, Resource
from app.models.core import Sda as SdaRow
from app.models.enums import AccountStatus, ConnectionMode

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


def _stage(stager: _ClaimStager, tenant_id: uuid.UUID, groups: list[str]) -> None:
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": groups,
        "custom:tenant_id": str(tenant_id),
    }


@pytest.fixture
def seeded(
    clean_database: Engine, alembic_config: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    command.upgrade(alembic_config, "head")
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    session: Session = sessionmaker(bind=clean_database)()
    tenant_id = uuid.UUID(str(session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))

    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="sandbox",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    sda = SdaRow(
        tenant_id=tenant_id,
        name="platform",
        owner_email="p@example.com",
        tag_values={"project_id": "proj-a"},
    )
    session.add_all([account, sda])
    session.flush()

    def _resource(arn: str, state: str | None, sda_id: uuid.UUID | None) -> Resource:
        return Resource(
            tenant_id=tenant_id,
            cloud_account_id=account.id,
            arn=arn,
            resource_type="AWS::EC2::Instance",
            service="ec2",
            region="us-east-1",
            tags={},
            state=state,
            sda_id=sda_id,
        )

    session.add_all(
        [
            _resource("arn:aws:ec2:::i-1", "running", sda.id),
            _resource("arn:aws:ec2:::i-2", "stopped", sda.id),
            _resource("arn:aws:ec2:::i-3", "running", None),  # the "No SDA" bucket
            _resource("arn:aws:ec2:::i-4", None, sda.id),  # never enriched: excluded
        ]
    )
    session.commit()
    session.close()

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(utilization_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    _stage(stager, tenant_id, VIEWER)
    return client, stager, tenant_id


def test_overall_counts_only_resources_with_a_known_state(seeded: Any) -> None:
    """Three enriched resources, two of them running -- the fourth has no state
    and is in neither half (R-509)."""
    client, *_ = seeded
    body = client.get("/utilization").json()
    assert body["overall"] == {"used": 2, "provisioned": 3, "percent": 66.7}


def test_the_per_account_figure_partitions_the_same_resources(seeded: Any) -> None:
    client, *_ = seeded
    body = client.get("/utilization").json()
    assert len(body["byAccount"]) == 1
    assert body["byAccount"][0]["alias"] == "sandbox"
    assert body["byAccount"][0]["utilization"] == body["overall"]


def test_the_no_sda_bucket_appears_as_its_own_project_row(seeded: Any) -> None:
    """Unattributed resources are a bucket, not an omission -- the same
    treatment spend and inventory already give them."""
    client, *_ = seeded
    by_project = {
        row["sdaName"]: row["utilization"] for row in client.get("/utilization").json()["byProject"]
    }
    assert by_project["platform"] == {"used": 1, "provisioned": 2, "percent": 50.0}
    assert by_project[None] == {"used": 1, "provisioned": 1, "percent": 100.0}


def test_an_empty_tenant_reports_not_enough_data_rather_than_zero(
    clean_database: Engine, alembic_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config, "head")
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    with clean_database.connect() as conn:
        tenant_id = uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(utilization_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    _stage(stager, tenant_id, VIEWER)

    body = client.get("/utilization").json()
    assert body["overall"] == {"used": 0, "provisioned": 0, "percent": None}


def test_every_role_can_read_utilization(seeded: Any) -> None:
    client, stager, tenant_id = seeded
    for groups in (ADMIN, OPERATOR, VIEWER):
        _stage(stager, tenant_id, groups)
        assert client.get("/utilization").status_code == 200, groups
