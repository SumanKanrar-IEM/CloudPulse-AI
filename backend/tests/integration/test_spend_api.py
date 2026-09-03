"""`GET /spend` and `GET /spend/summary` (T005, T010; S39, S42, FR-003).

Deferred from T005 into this same PR as T010's router, per this project's own
precedent (test_sdas_api.py's docstring) of a route and its integration test
landing together when they're this tightly coupled.
"""

from __future__ import annotations

import uuid
from datetime import date
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
from app.api.routers import spend as spend_router
from app.models.core import CloudAccount, SpendRecord
from app.models.core import Sda as SdaRow
from app.models.enums import AccountStatus, ConnectionMode

pytestmark = pytest.mark.integration

VIEWER = ["cloudpulse-viewers"]

DAY_1 = date(2026, 9, 1)
DAY_2 = date(2026, 9, 2)


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
def spend_app(
    clean_database: Engine, alembic_config: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow]:
    command.upgrade(alembic_config, "head")
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)

    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    tenant_id = uuid.UUID(str(session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))

    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
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
    session.add(account)
    session.add(sda)
    session.flush()

    session.add(
        SpendRecord(
            tenant_id=tenant_id,
            cloud_account_id=account.id,
            sda_id=sda.id,
            service="AmazonEC2",
            spend_date=DAY_1,
            amount_usd=Decimal("10.00"),
            is_gap=False,
        )
    )
    session.add(
        SpendRecord(
            tenant_id=tenant_id,
            cloud_account_id=account.id,
            sda_id=None,
            service="AmazonS3",
            spend_date=DAY_1,
            amount_usd=Decimal("5.00"),
            is_gap=False,
        )
    )
    session.add(
        SpendRecord(
            tenant_id=tenant_id,
            cloud_account_id=account.id,
            sda_id=None,
            service=None,
            spend_date=DAY_2,
            amount_usd=None,
            is_gap=True,
        )
    )
    session.commit()

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(spend_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": VIEWER,
        "custom:tenant_id": str(tenant_id),
    }
    return client, stager, tenant_id, account, sda


def test_list_spend_returns_rows_in_range(
    spend_app: tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow],
) -> None:
    client, *_ = spend_app
    response = client.get("/spend", params={"from": "2026-09-01", "to": "2026-09-02"})
    assert response.status_code == 200, response.text
    assert len(response.json()["spend"]) == 3


def test_list_spend_filters_by_sda_id(
    spend_app: tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow],
) -> None:
    client, _, _, _, sda = spend_app
    response = client.get(
        "/spend", params={"from": "2026-09-01", "to": "2026-09-02", "sdaId": str(sda.id)}
    )
    rows = response.json()["spend"]
    assert len(rows) == 1
    assert rows[0]["sdaId"] == str(sda.id)


def test_list_spend_filters_to_the_no_sda_bucket(
    spend_app: tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow],
) -> None:
    """`sdaId=none` -- distinct from omitting the parameter (FR-001)."""
    client, *_ = spend_app
    response = client.get(
        "/spend", params={"from": "2026-09-01", "to": "2026-09-01", "sdaId": "none"}
    )
    rows = response.json()["spend"]
    assert len(rows) == 1
    assert rows[0]["sdaId"] is None
    assert rows[0]["service"] == "AmazonS3"


def test_summary_totals_and_by_project_breakdown(
    spend_app: tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow],
) -> None:
    client, _, _, _, sda = spend_app
    response = client.get("/spend/summary", params={"from": "2026-09-01", "to": "2026-09-02"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totalUsd"] == "15.0000"
    by_project = {row["sdaId"]: row["totalUsd"] for row in body["byProject"]}
    assert by_project[str(sda.id)] == "10.0000"
    assert by_project[None] == "5.0000"


def test_summary_trend_renders_a_gap_day_as_null_not_a_missing_point(
    spend_app: tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow],
) -> None:
    """FR-002a: a partial sum presented as complete would be worse than an
    honest null."""
    client, *_ = spend_app
    response = client.get("/spend/summary", params={"from": "2026-09-01", "to": "2026-09-02"})
    trend = {point["date"]: point["totalUsd"] for point in response.json()["trend"]}
    assert trend == {"2026-09-01": "15.0000", "2026-09-02": None}


def test_spend_endpoints_are_readable_by_every_role(
    spend_app: tuple[TestClient, _ClaimStager, uuid.UUID, CloudAccount, SdaRow],
) -> None:
    """FR-003's own visibility Assumption: any role may read."""
    client, stager, tenant_id, *_ = spend_app
    for groups in (["cloudpulse-admins"], ["cloudpulse-operators"], VIEWER):
        stager.claims = {
            "sub": "s",
            "email": "e@example.com",
            "cognito:groups": groups,
            "custom:tenant_id": str(tenant_id),
        }
        assert (
            client.get("/spend", params={"from": "2026-09-01", "to": "2026-09-02"}).status_code
            == 200
        )
        assert (
            client.get(
                "/spend/summary", params={"from": "2026-09-01", "to": "2026-09-02"}
            ).status_code
            == 200
        )
