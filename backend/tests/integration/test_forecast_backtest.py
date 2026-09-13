"""Backtesting through the store and the endpoint (T045; spec 006, FR-021a,
FR-022, SC-006, S51).

Three projects, seeded so each exercises one branch of `GET /forecasts`:

* **steady** -- 30 days of spend on a clean upward line, and CPU history.
  Forecasts, backtests, and the backtest error is exactly zero because the
  held-out week lies on the same line.
* **thin** -- 10 days of spend. Below the 14-period minimum, so
  `insufficientHistory: true` with a null projection and the counts.
* **gappy** -- 20 rows across 20 days, but six of them are gap days. Fourteen
  real periods: exactly the minimum, so it forecasts -- and the gap days must
  not have counted, or "thin" would forecast too.

SC-006's reproducibility is asserted the only way it can be: two requests,
byte-identical projections and errors. `generatedAt` is the one field allowed
to differ.
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
from app.api.routers import forecasts as forecasts_router
from app.models.core import CloudAccount, Resource, ResourceMetric, Sda, SpendRecord
from app.models.enums import AccountStatus, ConnectionMode, ResourceMetricKind

pytestmark = pytest.mark.integration

VIEWER = ["cloudpulse-viewers"]
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
    monkeypatch.setenv("CLOUDPULSE_FORECAST_MIN_PERIODS", "14")
    session = sessionmaker(bind=clean_database)()
    account = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="a",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    sdas = {
        name: Sda(
            tenant_id=real_tenant_id, name=name, owner_email=f"{name}@example.com", tag_values={}
        )
        for name in ("gappy", "steady", "thin")
    }
    session.add(account)
    session.add_all(sdas.values())
    session.flush()

    def spend(sda: Sda, day: date, amount: str | None) -> SpendRecord:
        return SpendRecord(
            tenant_id=real_tenant_id,
            cloud_account_id=account.id,
            sda_id=sda.id,
            service="AmazonEC2",
            spend_date=day,
            amount_usd=None if amount is None else Decimal(amount),
            is_gap=amount is None,
        )

    # steady: 10 + 0.5x for 30 days.
    session.add_all(
        spend(sdas["steady"], START + timedelta(days=i), str(Decimal("10") + Decimal("0.5") * i))
        for i in range(30)
    )
    # thin: 10 days, flat.
    session.add_all(spend(sdas["thin"], START + timedelta(days=i), "10") for i in range(10))
    # gappy: 20 days, of which every third is a gap -> 14 real periods.
    session.add_all(
        spend(sdas["gappy"], START + timedelta(days=i), None if i % 3 == 2 else "10")
        for i in range(20)
    )

    # steady also has CPU history on one instance: 20 + 1x for 30 days.
    instance = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        sda_id=sdas["steady"].id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-steady",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
        detail={},
    )
    session.add(instance)
    session.flush()
    session.add_all(
        ResourceMetric(
            tenant_id=real_tenant_id,
            resource_id=instance.id,
            metric=ResourceMetricKind.CPU,
            period_start=datetime.combine(START + timedelta(days=i), datetime.min.time()),
            value=Decimal("20") + i,
            is_unavailable=False,
        )
        for i in range(30)
    )
    # And one unavailable memory row, which must not leak into the CPU mean.
    session.add(
        ResourceMetric(
            tenant_id=real_tenant_id,
            resource_id=instance.id,
            metric=ResourceMetricKind.MEMORY,
            period_start=datetime.combine(START, datetime.min.time()),
            value=None,
            is_unavailable=True,
        )
    )
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
    app.include_router(forecasts_router.router)
    stager = _ClaimStager(app)
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": VIEWER,
        "custom:tenant_id": str(real_tenant_id),
    }
    return TestClient(stager, raise_server_exceptions=False)


def _by_name(body: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {p["sdaName"]: {f["kind"]: f for f in p["forecasts"]} for p in body["projects"]}


def test_a_project_with_history_forecasts_and_backtests_with_zero_error_on_a_line(
    api: TestClient, seed: None
) -> None:
    body = api.get("/forecasts").json()
    steady = _by_name(body)["steady"]

    spend = steady["spend"]
    assert spend["insufficientHistory"] is False
    assert spend["historyDays"] == 30
    assert spend["projectedValue"] is not None
    assert spend["backtest"]["heldOutDays"] == 7
    assert spend["backtest"]["trainingDays"] == 23
    # The held-out week sits on the same line the training week fit, so the
    # forecast made exactly the right call. Anything else here means the fit
    # or the split is wrong, not the data.
    assert spend["backtest"]["absolutePercentageError"] == "0.000"

    capacity = steady["capacity"]
    assert capacity["insufficientHistory"] is False
    assert capacity["historyDays"] == 30
    assert capacity["backtest"]["absolutePercentageError"] == "0.000"


def test_a_thin_project_gets_the_explicit_state_with_its_counts(
    api: TestClient, seed: None
) -> None:
    thin = _by_name(api.get("/forecasts").json())["thin"]

    assert thin["spend"] == {
        "kind": "spend",
        "insufficientHistory": True,
        "historyDays": 10,
        "requiredDays": 14,
        "periodStart": None,
        "periodEnd": None,
        "projectedValue": None,
        "backtest": None,
    }
    # No metrics at all: still listed, still the explicit state (FR-021a).
    assert thin["capacity"]["insufficientHistory"] is True
    assert thin["capacity"]["historyDays"] == 0


def test_gap_days_do_not_count_as_history(api: TestClient, seed: None) -> None:
    """Twenty rows, fourteen real. Exactly the minimum -- so it forecasts, and
    `historyDays` says fourteen, not twenty."""
    gappy = _by_name(api.get("/forecasts").json())["gappy"]

    assert gappy["spend"]["insufficientHistory"] is False
    assert gappy["spend"]["historyDays"] == 14


def test_the_same_history_yields_byte_identical_forecasts_on_every_request(
    api: TestClient, seed: None
) -> None:
    """SC-006. `generatedAt` is the only thing that may differ."""
    first = api.get("/forecasts").json()
    second = api.get("/forecasts").json()

    first.pop("generatedAt")
    second.pop("generatedAt")
    assert first == second
