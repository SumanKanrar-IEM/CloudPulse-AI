"""`GET /rightsizing` through the store (spec 006, T049/T050; FR-023, FR-002).

Three instances of the same class, differing only in their CPU history:
`idle` (low and flat) is recommended down; `busy` (high) and `spiky` (low
mean, high peak) are absent. Absent, not flagged -- the endpoint returns
recommendations, and the ones it must not make do not appear as anything.

The unavailable-row exclusion is exercised here too: `idle` carries a stretch
of unavailable days that, averaged as zero, would only make it look idler.
That direction of error is the flattering one, which is why it is the one to
guard against.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
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
from app.api.routers import rightsizing as rightsizing_router
from app.models.core import CloudAccount, Resource, ResourceMetric
from app.models.enums import AccountStatus, ConnectionMode, ResourceMetricKind

pytestmark = pytest.mark.integration

START = date(2026, 2, 1)


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
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def seed(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDPULSE_RIGHTSIZING_MIN_PERIODS", "14")
    monkeypatch.setenv("CLOUDPULSE_RIGHTSIZING_LOW_CPU_PERCENT", "20")
    session = sessionmaker(bind=clean_database)()
    account = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="a",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    session.add(account)
    session.flush()

    def instance(name: str) -> Resource:
        return Resource(
            tenant_id=real_tenant_id,
            cloud_account_id=account.id,
            arn=f"arn:aws:ec2:us-east-1:123456789012:instance/i-{name}",
            resource_type="AWS::EC2::Instance",
            service="ec2",
            region="us-east-1",
            tags={},
            detail={"instance_type": "m5.xlarge"},
        )

    idle, busy, spiky = instance("idle"), instance("busy"), instance("spiky")
    session.add_all([idle, busy, spiky])
    session.flush()

    def cpu(resource: Resource, day_index: int, value: str | None) -> ResourceMetric:
        return ResourceMetric(
            tenant_id=real_tenant_id,
            resource_id=resource.id,
            metric=ResourceMetricKind.CPU,
            period_start=datetime.combine(START + timedelta(days=day_index), datetime.min.time()),
            value=None if value is None else Decimal(value),
            is_unavailable=value is None,
        )

    # idle: 20 days at 6-9%, plus five unavailable days that must not count.
    session.add_all(cpu(idle, i, str(6 + i % 4)) for i in range(20))
    session.add_all(cpu(idle, 20 + i, None) for i in range(5))
    # busy: 20 days at 60%.
    session.add_all(cpu(busy, i, "60") for i in range(20))
    # spiky: 19 days at 5%, one day at 85%. Mean ~9%, peak 85%.
    session.add_all(cpu(spiky, i, "5") for i in range(19))
    session.add(cpu(spiky, 19, "85"))
    session.commit()
    session.close()


@pytest.fixture
def api(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(rightsizing_router.router)
    stager = _ClaimStager(app)
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": ["cloudpulse-viewers"],
        "custom:tenant_id": str(real_tenant_id),
    }
    return TestClient(stager, raise_server_exceptions=False)


def test_only_the_idle_instance_is_recommended_and_it_carries_its_evidence(
    api: TestClient, seed: None
) -> None:
    body = api.get("/rightsizing").json()

    assert [r["arn"].rsplit("-", 1)[-1] for r in body["recommendations"]] == ["idle"]
    rec = body["recommendations"][0]
    assert (rec["currentClass"], rec["recommendedClass"]) == ("m5.xlarge", "m5.large")
    assert rec["estimatedMonthlySavingUsd"] == "70.08"
    # Twenty measured periods, not twenty-five: the unavailable days were
    # excluded rather than averaged in as zero.
    assert rec["evidence"]["periods"] == 20
    assert rec["evidence"]["period_last"] == "2026-02-20"
    assert Decimal(rec["evidence"]["mean_percent"]) < Decimal("10")
    assert rec["evidence"]["low_threshold_percent"] == "20"


def test_the_response_has_no_apply_control(api: TestClient, seed: None) -> None:
    """FR-002, acceptance scenario 3. Asserted on the contract rather than the
    UI: no field in a recommendation is an action, and no route exists that
    could be one."""
    body = api.get("/rightsizing").json()
    rec = body["recommendations"][0]

    for key in rec:
        assert not any(word in key.lower() for word in ("apply", "execute", "action", "url"))
    assert [r.path for r in api.app.app.routes if "rightsizing" in r.path] == ["/rightsizing"]  # type: ignore[attr-defined]
