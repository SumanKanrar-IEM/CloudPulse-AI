"""Direct-creator ownership attribution against a real database (FR-020-FR-023,
research.md R-302).

Moved from tests/unit/ to tests/integration/ -- same precedent as T013/T018:
FR-023's guarded upsert is a real Postgres `ON CONFLICT ... WHERE` behavior,
not something a mock can prove.
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

from app.governance.ownership import _write_attribution, attribute_ownership
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


def test_a_human_creator_is_attributed_with_evidence(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-021: a human-principal creation event becomes a high-confidence,
    direct attribution with evidence citing the event."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-1")
    events = {
        "i-1": {
            "principal": "arn:aws:iam::123456789012:user/alice",
            "is_human": True,
            "event_name": "RunInstances",
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
            "event_id": "evt-alice",
            "is_write": True,
        }
    }

    attributed = attribute_ownership(session, account.id, events)  # type: ignore[arg-type]

    assert attributed == 1
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()
    assert owner.owner_email == "arn:aws:iam::123456789012:user/alice"
    assert owner.confidence == OwnerConfidence.HIGH
    assert owner.evidence["kind"] == "direct"
    assert owner.evidence["cloudtrail_event_id"] == "evt-alice"
    assert owner.evidence["principal"] == "arn:aws:iam::123456789012:user/alice"


def test_a_resource_with_no_matching_event_stays_unattributed(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-022: no event in the map at all (outside the 90-day window, or no
    creator determinable) -- stays queued unattributed, not guessed."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-2")

    attributed = attribute_ownership(session, account.id, {})  # type: ignore[arg-type]

    assert attributed == 0
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one_or_none()
    assert owner is None


def test_a_non_human_creator_stays_unattributed(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-021's P1 scope: an automation/pipeline creator is not directly
    attributed -- P2's fallback chain (out of scope here) is what handles it."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-3")
    events = {
        "i-3": {
            "principal": "arn:aws:sts::123456789012:assumed-role/ci-deploy/session",
            "is_human": False,
            "event_name": "RunInstances",
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
            "event_id": "evt-ci",
            "is_write": True,
        }
    }

    attributed = attribute_ownership(session, account.id, events)  # type: ignore[arg-type]

    assert attributed == 0
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one_or_none()
    assert owner is None


def test_an_existing_high_confidence_attribution_is_not_overwritten_by_a_lower_one(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-023, the decisive guard: `_write_attribution` with a MEDIUM result
    must leave an existing HIGH row untouched -- the guarded
    `ON CONFLICT ... WHERE` pattern data-model.md's `resource_owner` section
    requires, exercised directly since P1's `attribute_ownership` only ever
    produces HIGH results itself (P2's fallback chain is what would produce a
    genuinely lower one in practice)."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-4")
    original_time = datetime(2026, 3, 1, tzinfo=UTC)
    wrote_first = _write_attribution(
        session,  # type: ignore[arg-type]
        resource_id=resource.id,
        owner_email="arn:aws:iam::123456789012:user/alice",
        confidence=OwnerConfidence.HIGH,
        evidence={"kind": "direct", "cloudtrail_event_id": "evt-1", "principal": "alice"},
        attributed_at=original_time,
    )
    assert wrote_first is True

    later_time = datetime(2026, 3, 5, tzinfo=UTC)
    wrote_second = _write_attribution(
        session,  # type: ignore[arg-type]
        resource_id=resource.id,
        owner_email="bob@example.com",
        confidence=OwnerConfidence.MEDIUM,
        evidence={"kind": "fallback", "cloudtrail_event_id": "evt-2", "principal": "bob"},
        attributed_at=later_time,
    )
    assert wrote_second is False

    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()
    assert owner.owner_email == "arn:aws:iam::123456789012:user/alice"
    assert owner.confidence == OwnerConfidence.HIGH
    assert owner.evidence["kind"] == "direct"
    assert owner.attributed_at == original_time


def test_a_same_confidence_result_updates_in_place(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """A second scan's HIGH-confidence re-attribution updates the same row,
    rather than being blocked -- the guard is `<=`, not `<`."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-5")
    _write_attribution(
        session,  # type: ignore[arg-type]
        resource_id=resource.id,
        owner_email="arn:aws:iam::123456789012:user/alice",
        confidence=OwnerConfidence.HIGH,
        evidence={"kind": "direct", "cloudtrail_event_id": "evt-1", "principal": "alice"},
        attributed_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    later_time = datetime(2026, 3, 5, tzinfo=UTC)
    wrote_again = _write_attribution(
        session,  # type: ignore[arg-type]
        resource_id=resource.id,
        owner_email="arn:aws:iam::123456789012:user/alice",
        confidence=OwnerConfidence.HIGH,
        evidence={"kind": "direct", "cloudtrail_event_id": "evt-2", "principal": "alice"},
        attributed_at=later_time,
    )

    assert wrote_again is True
    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()
    assert owner.evidence["cloudtrail_event_id"] == "evt-2"
    assert owner.attributed_at == later_time


def test_a_child_resource_is_still_attributed(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-020 carries no top-level-only qualifier, unlike FR-013/FR-018."""
    session = _RawSession(db, tenant_id)
    parent = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-parent"
    )
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:volume/vol-1")
    resource.parent_resource_id = parent.id
    db.flush()
    events = {
        "vol-1": {
            "principal": "arn:aws:iam::123456789012:user/alice",
            "is_human": True,
            "event_name": "CreateVolume",
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
            "event_id": "evt-vol",
            "is_write": True,
        }
    }

    attributed = attribute_ownership(session, account.id, events)  # type: ignore[arg-type]

    assert attributed == 1
