"""Attribution fallback (P2, FR-024-FR-026, research.md R-302).

Moved from tests/unit/ to tests/integration/ -- same precedent as T022:
FR-023's guarded upsert underlies every write here too, a real Postgres
behavior, not something a mock proves.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.governance.ownership import attribute_ownership
from app.models.core import CloudAccount, Resource, ResourceOwner
from app.models.enums import AccountStatus, ConnectionMode, OwnerConfidence

pytestmark = pytest.mark.integration


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    @property
    def tenant_id(self) -> uuid.UUID:  # type: ignore[override]
        return self._tenant_id

    def scoped(self, statement: Any, model: Any) -> Any:
        return statement.where(model.tenant_id == self._tenant_id)

    def add(self, instance: Any) -> None:
        instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()


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


def _resource(db: Session, tenant_id: uuid.UUID, account: CloudAccount, arn: str) -> Resource:
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn=arn,
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    db.add(resource)
    db.flush()
    return resource


def _write_event(principal: str, day: int, *, is_human: bool = True) -> dict[str, Any]:
    return {
        "principal": principal,
        "is_human": is_human,
        "event_time": datetime(2026, 3, day, tzinfo=UTC),
        "event_id": f"evt-{principal}-{day}",
    }


def test_an_automation_creator_falls_back_to_the_most_frequent_human_modifier(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-024/FR-025: 3+ write events from the same human is enough."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-1")
    events = {
        "i-1": {
            "principal": "arn:aws:sts::123456789012:assumed-role/ci-deploy/session",
            "is_human": False,
            "event_name": "RunInstances",
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
            "event_id": "evt-ci",
            "is_write": True,
        }
    }
    write_events = {
        "i-1": [
            _write_event("alice", 2),
            _write_event("alice", 3),
            _write_event("alice", 4),
        ]
    }

    attributed = attribute_ownership(session, account.id, events, write_events)  # type: ignore[arg-type]

    assert attributed == 1
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()
    assert owner.owner_email == "alice"
    assert owner.confidence == OwnerConfidence.MEDIUM
    assert owner.evidence["kind"] == "fallback"
    assert owner.evidence["write_event_count"] == 3


def test_fewer_than_three_write_events_stays_unattributed(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-026: below the threshold is queued unattributed, not a guess."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-2")
    write_events = {"i-2": [_write_event("bob", 2), _write_event("bob", 3)]}

    attributed = attribute_ownership(session, account.id, {}, write_events)  # type: ignore[arg-type]

    assert attributed == 0
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one_or_none()
    assert owner is None


def test_the_most_frequent_human_wins_over_a_less_frequent_one(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-3")
    write_events = {
        "i-3": [
            _write_event("alice", 1),
            _write_event("alice", 2),
            _write_event("alice", 3),
            _write_event("alice", 4),
            _write_event("bob", 5),
            _write_event("bob", 6),
            _write_event("bob", 7),
        ]
    }

    attribute_ownership(session, account.id, {}, write_events)  # type: ignore[arg-type]

    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()
    assert owner.owner_email == "alice"
    assert owner.evidence["write_event_count"] == 4


def test_non_human_write_events_never_count_toward_the_threshold(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-4")
    write_events = {
        "i-4": [
            _write_event("ci-role", 1, is_human=False),
            _write_event("ci-role", 2, is_human=False),
            _write_event("ci-role", 3, is_human=False),
        ]
    }

    attributed = attribute_ownership(session, account.id, {}, write_events)  # type: ignore[arg-type]

    assert attributed == 0
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one_or_none()
    assert owner is None


def test_direct_attribution_takes_priority_over_fallback(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """A human creator is attributed directly (HIGH) even when write-event
    data for a fallback candidate is also present -- direct attribution
    always wins when it applies."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-5")
    events = {
        "i-5": {
            "principal": "alice",
            "is_human": True,
            "event_name": "RunInstances",
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
            "event_id": "evt-alice",
            "is_write": True,
        }
    }
    write_events = {"i-5": [_write_event("bob", 2), _write_event("bob", 3), _write_event("bob", 4)]}

    attribute_ownership(session, account.id, events, write_events)  # type: ignore[arg-type]

    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()
    assert owner.owner_email == "alice"
    assert owner.confidence == OwnerConfidence.HIGH
    assert owner.evidence["kind"] == "direct"
