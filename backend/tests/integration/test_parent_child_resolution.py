"""Parent/child resource resolution (FR-013, FR-013a) -- the first use of
spec 1's `resource.parent_resource_id` column, reserved but left unpopulated by
spec 002.

Moved from tests/unit/ to tests/integration/, same precedent as the rest of
Phase 5: proving `parent_resource_id` gets set correctly needs real persisted
rows, not a mock.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.governance.validation import resolve_parent_child_relationships, validate_account
from app.models.core import CloudAccount, Resource
from app.models.core import Rule as RuleRow
from app.models.enums import AccountStatus, ConnectionMode

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
def db(
    clean_database: Engine, alembic_config: Any
) -> Iterator[tuple[_RawSession, Session, uuid.UUID]]:
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    tenant_id = uuid.UUID(str(session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))
    try:
        yield _RawSession(session, tenant_id), session, tenant_id
    finally:
        session.close()


@pytest.fixture
def account(db: tuple[_RawSession, Session, uuid.UUID]) -> CloudAccount:
    _, raw, tenant_id = db
    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    raw.add(account)
    raw.flush()
    return account


def test_an_ebs_volume_gets_its_attached_instance_as_parent(
    db: tuple[_RawSession, Session, uuid.UUID], account: CloudAccount
) -> None:
    """FR-013a: `attached_instance_id`, the field spec 002's EBS enrichment
    already captures."""
    session, raw, tenant_id = db
    instance = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    raw.add(instance)
    raw.flush()
    volume = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:volume/vol-xyz789",
        resource_type="AWS::EC2::Volume",
        service="ec2",
        region="us-east-1",
        tags={},
        detail={"attached_instance_id": "i-abc123"},
    )
    raw.add(volume)
    raw.flush()

    changed = resolve_parent_child_relationships(session, account.id)  # type: ignore[arg-type]
    raw.refresh(volume)

    assert changed == 1
    assert volume.parent_resource_id == instance.id


def test_an_eip_gets_its_associated_instance_as_parent(
    db: tuple[_RawSession, Session, uuid.UUID], account: CloudAccount
) -> None:
    session, raw, tenant_id = db
    instance = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    raw.add(instance)
    raw.flush()
    eip = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:elastic-ip/eipalloc-1",
        resource_type="AWS::EC2::EIP",
        service="ec2",
        region="us-east-1",
        tags={},
        detail={"associated_instance_id": "i-abc123"},
    )
    raw.add(eip)
    raw.flush()

    resolve_parent_child_relationships(session, account.id)  # type: ignore[arg-type]
    raw.refresh(eip)

    assert eip.parent_resource_id == instance.id


def test_a_resource_with_no_attachment_detail_stays_top_level(
    db: tuple[_RawSession, Session, uuid.UUID], account: CloudAccount
) -> None:
    session, raw, tenant_id = db
    standalone = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:s3:::my-bucket",
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-east-1",
        tags={},
    )
    raw.add(standalone)
    raw.flush()

    resolve_parent_child_relationships(session, account.id)  # type: ignore[arg-type]
    raw.refresh(standalone)

    assert standalone.parent_resource_id is None


def test_validation_only_evaluates_top_level_resources(
    db: tuple[_RawSession, Session, uuid.UUID], account: CloudAccount
) -> None:
    """FR-013: `validate_account` never independently evaluates an attached
    resource, even one that would otherwise violate a rule."""
    session, raw, tenant_id = db
    raw.execute(update(RuleRow).values(enabled=False))
    raw.flush()
    session.add(
        RuleRow(
            tenant_id=tenant_id, key="team", version=1, definition={"required": True}, enabled=True
        )
    )
    raw.flush()
    instance = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={"team": "platform"},
    )
    raw.add(instance)
    raw.flush()
    volume = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:volume/vol-xyz789",
        resource_type="AWS::EC2::Volume",
        service="ec2",
        region="us-east-1",
        tags={},  # would violate the owner rule if evaluated independently
        detail={"attached_instance_id": "i-abc123"},
    )
    raw.add(volume)
    raw.flush()

    evaluated_count = validate_account(session, account.id)  # type: ignore[arg-type]

    assert evaluated_count == 1  # only the instance, not the volume
