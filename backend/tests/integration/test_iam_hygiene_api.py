"""IAM hygiene flags against a real database (T043; S56, FR-019, FR-020).

The clear/re-flag cycle is the reason this needs a real engine: it rests on the
partial unique index `WHERE cleared_at IS NULL`, which allows exactly one
active flag per principal while keeping every earlier cleared row as history. A
stub session cannot demonstrate that, and getting it wrong would either raise
on the second flag or silently revive a stale one.
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
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import iam_hygiene as iam_hygiene_router
from app.governance.iam_hygiene import UNUSED_AFTER, Candidate, reconcile_flags
from app.models.core import CloudAccount
from app.models.core import IamHygieneFlag as FlagRow
from app.models.enums import AccountStatus, ConnectionMode

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 1, tzinfo=UTC)
LONG_AGO = NOW - UNUSED_AFTER - timedelta(days=1)
RECENTLY = NOW - timedelta(days=2)
ROLE_ARN = "arn:aws:iam::123456789012:role/abandoned"

ADMIN = ["cloudpulse-admins"]
OPERATOR = ["cloudpulse-operators"]
VIEWER = ["cloudpulse-viewers"]


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    @property
    def tenant_id(self) -> uuid.UUID:
        return self._tenant_id

    def scoped(self, statement: Any, model: Any) -> Any:
        return statement.where(model.tenant_id == self._tenant_id)

    def add(self, instance: Any) -> None:
        instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()


class _ClaimStager:
    def __init__(self, app: Any, tenant_id: uuid.UUID) -> None:
        self.app = app
        self.claims: dict[str, Any] = {
            "sub": "s",
            "email": "e@example.com",
            "cognito:groups": VIEWER,
            "custom:tenant_id": str(tenant_id),
        }

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


@pytest.fixture
def db(clean_database: Engine, alembic_config: Any) -> Iterator[Session]:
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant_id(db: Session) -> uuid.UUID:
    return uuid.UUID(str(db.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def session(db: Session, tenant_id: uuid.UUID) -> _RawSession:
    return _RawSession(db, tenant_id)


@pytest.fixture
def account(db: Session, tenant_id: uuid.UUID) -> CloudAccount:
    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add(account)
    db.flush()
    return account


@pytest.fixture
def api(
    clean_database: Engine, db: Session, tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(iam_hygiene_router.router)
    stager = _ClaimStager(app, tenant_id)
    return TestClient(stager, raise_server_exceptions=False), stager


def _unused(identifier: str = ROLE_ARN) -> Candidate:
    return Candidate(
        principal_type="role",
        identifier=identifier,
        name="abandoned",
        created_at=LONG_AGO,
        last_used_at=LONG_AGO,
    )


def _active(identifier: str = ROLE_ARN) -> Candidate:
    return Candidate(
        principal_type="role",
        identifier=identifier,
        name="abandoned",
        created_at=LONG_AGO,
        last_used_at=RECENTLY,
    )


def _flags(db: Session, tenant_id: uuid.UUID) -> list[FlagRow]:
    return list(
        db.execute(
            select(FlagRow).where(FlagRow.tenant_id == tenant_id).order_by(FlagRow.flagged_at)
        )
        .scalars()
        .all()
    )


def test_an_unused_principal_is_flagged_with_its_evidence(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, api: Any
) -> None:
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.commit()

    client, _ = api
    body = client.get("/iam-hygiene").json()

    assert len(body["flags"]) == 1
    flag = body["flags"][0]
    assert flag["principalIdentifier"] == ROLE_ARN
    assert flag["principalType"] == "role"
    assert flag["evidence"]["daysSinceLastUse"] == (NOW - LONG_AGO).days
    assert flag["clearedAt"] is None


def test_an_active_principal_is_never_flagged(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-020, end to end."""
    flagged, cleared = reconcile_flags(session, account.id, [_active()], now=NOW)
    assert (flagged, cleared) == (0, 0)
    assert _flags(db, tenant_id) == []


def test_a_second_run_does_not_duplicate_or_restamp_an_existing_flag(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """`flagged_at` answers "how long has this been flagged", so re-stamping it
    weekly would destroy the only fact the flag carries about its own age."""
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.flush()
    first_flagged_at = _flags(db, tenant_id)[0].flagged_at

    later = NOW + timedelta(days=7)
    flagged, _ = reconcile_flags(session, account.id, [_unused()], now=later)
    db.flush()

    rows = _flags(db, tenant_id)
    assert flagged == 0
    assert len(rows) == 1
    assert rows[0].flagged_at == first_flagged_at


def test_a_principal_that_becomes_active_again_is_cleared(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.flush()

    later = NOW + timedelta(days=7)
    _, cleared = reconcile_flags(
        session,
        account.id,
        [Candidate("role", ROLE_ARN, "abandoned", LONG_AGO, later - timedelta(days=1))],
        now=later,
    )
    db.flush()

    rows = _flags(db, tenant_id)
    assert cleared == 1
    assert len(rows) == 1
    assert rows[0].cleared_at is not None


def test_a_principal_that_goes_unused_again_gets_a_fresh_flag(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """A new row, never a revived one -- the partial unique index allows exactly
    one active flag per principal while keeping the cleared row as history."""
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.flush()
    active_at = NOW + timedelta(days=7)
    reconcile_flags(
        session,
        account.id,
        [Candidate("role", ROLE_ARN, "abandoned", LONG_AGO, active_at - timedelta(days=1))],
        now=active_at,
    )
    db.flush()

    much_later = active_at + UNUSED_AFTER + timedelta(days=1)
    flagged, _ = reconcile_flags(
        session,
        account.id,
        [Candidate("role", ROLE_ARN, "abandoned", LONG_AGO, active_at - timedelta(days=1))],
        now=much_later,
    )
    db.flush()

    rows = _flags(db, tenant_id)
    assert flagged == 1
    assert len(rows) == 2
    assert rows[0].cleared_at is not None
    assert rows[1].cleared_at is None
    assert rows[1].flagged_at == much_later


def test_a_principal_that_no_longer_exists_is_cleared(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """A standing "this is unused, delete it" recommendation pointing at
    something already gone is worse than no recommendation."""
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.flush()

    _, cleared = reconcile_flags(session, account.id, [], now=NOW + timedelta(days=7))
    db.flush()

    assert cleared == 1
    assert _flags(db, tenant_id)[0].cleared_at is not None


def test_cleared_flags_are_hidden_by_default_and_available_on_request(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, api: Any
) -> None:
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.flush()
    reconcile_flags(session, account.id, [], now=NOW + timedelta(days=7))
    db.commit()

    client, _ = api
    assert client.get("/iam-hygiene").json()["flags"] == []
    assert len(client.get("/iam-hygiene", params={"includeCleared": "true"}).json()["flags"]) == 1


def test_every_role_can_read_the_flags(
    db: Session, session: _RawSession, tenant_id: uuid.UUID, account: CloudAccount, api: Any
) -> None:
    reconcile_flags(session, account.id, [_unused()], now=NOW)
    db.commit()

    client, stager = api
    for groups in (ADMIN, OPERATOR, VIEWER):
        stager.claims["cognito:groups"] = groups
        assert client.get("/iam-hygiene").status_code == 200, groups
