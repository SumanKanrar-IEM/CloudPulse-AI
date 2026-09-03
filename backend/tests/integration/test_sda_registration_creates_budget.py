"""`POST /sdas` creates the budget in its own transaction (T028; S40, FR-015,
research.md R-502).

Needs a real database: "in the same transaction" is not a property a stub
session can demonstrate. The rollback case is the one that matters most --
it is what stops a project existing without the guardrail Phase 8's overrun
check depends on.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import sdas as sdas_router
from app.models.core import Budget
from app.models.core import Sda as SdaRow

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]


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
def sdas_app(
    clean_database: Engine, alembic_config: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    command.upgrade(alembic_config, "head")
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    with clean_database.connect() as conn:
        tenant_id = uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(sdas_router.router)
    stager = _ClaimStager(app)
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": ADMIN,
        "custom:tenant_id": str(tenant_id),
    }
    return TestClient(stager, raise_server_exceptions=False), stager, tenant_id


def _register(client: TestClient, name: str, tag_value: str) -> Any:
    return client.post(
        "/sdas",
        json={
            "name": name,
            "ownerEmail": f"{name}@example.com",
            "tagValues": {"project_id": tag_value},
        },
    )


def test_registering_a_project_creates_exactly_one_budget(
    sdas_app: Any, clean_database: Engine
) -> None:
    client, _, tenant_id = sdas_app

    response = _register(client, "platform", "proj-a")
    assert response.status_code == 201, response.text

    session = sessionmaker(bind=clean_database)()
    budgets = session.execute(select(Budget).where(Budget.tenant_id == tenant_id)).scalars().all()
    assert len(budgets) == 1
    assert str(budgets[0].sda_id) == response.json()["id"]
    assert budgets[0].amount_usd > 0
    session.close()


def test_the_new_budget_has_crossed_no_thresholds(sdas_app: Any, clean_database: Engine) -> None:
    client, _, tenant_id = sdas_app
    _register(client, "platform", "proj-a")

    session = sessionmaker(bind=clean_database)()
    budget = session.execute(select(Budget).where(Budget.tenant_id == tenant_id)).scalar_one()
    assert budget.actual_80_crossed_at is None
    assert budget.actual_100_crossed_at is None
    assert budget.forecast_80_crossed_at is None
    assert budget.forecast_100_crossed_at is None
    session.close()


def test_each_project_gets_its_own_budget(sdas_app: Any, clean_database: Engine) -> None:
    client, _, tenant_id = sdas_app
    _register(client, "platform", "proj-a")
    _register(client, "data", "proj-b")

    session = sessionmaker(bind=clean_database)()
    count = session.execute(
        select(func.count()).select_from(Budget).where(Budget.tenant_id == tenant_id)
    ).scalar_one()
    assert count == 2
    session.close()


def test_a_refused_registration_leaves_no_orphan_budget(
    sdas_app: Any, clean_database: Engine
) -> None:
    """The transactional half of R-502. An overlapping mapping is refused with
    409 (FR-010a); neither the SDA nor its budget may survive that."""
    client, _, tenant_id = sdas_app
    _register(client, "platform", "proj-a")

    refused = _register(client, "duplicate", "proj-a")
    assert refused.status_code == 409, refused.text

    session = sessionmaker(bind=clean_database)()
    assert (
        session.execute(
            select(func.count()).select_from(Budget).where(Budget.tenant_id == tenant_id)
        ).scalar_one()
        == 1
    )
    assert (
        session.execute(
            select(func.count()).select_from(SdaRow).where(SdaRow.tenant_id == tenant_id)
        ).scalar_one()
        == 1
    )
    session.close()
