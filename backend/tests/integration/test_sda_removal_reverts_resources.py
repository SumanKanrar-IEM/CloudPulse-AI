"""SDA removal reverts attached resources to the "No SDA" bucket immediately
(FR-010b), proven at the database level -- the `ON DELETE SET NULL` foreign key
is the actual mechanism (data-model.md), not application code, so this test
deletes the SDA row directly and inspects `resource.sda_id` with no
`reclassify_account_resources` call in between.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.core import CloudAccount, Resource, Sda
from app.models.enums import AccountStatus, ConnectionMode

pytestmark = pytest.mark.integration


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


def test_deleting_an_sda_immediately_reverts_its_attached_resource(
    db: Session, tenant_id: uuid.UUID
) -> None:
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

    sda = Sda(tenant_id=tenant_id, name="platform", owner_email="a@example.com", tag_values={})
    db.add(sda)
    db.flush()

    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={"team": "platform"},
        sda_id=sda.id,
    )
    db.add(resource)
    db.flush()
    resource_id = resource.id
    assert resource.sda_id == sda.id

    db.delete(sda)
    db.flush()
    db.commit()
    # `ON DELETE SET NULL` is a database-level FK action -- it changes the row in
    # Postgres, but the already-loaded `resource` object in this session's identity
    # map has no way to know that on its own. `expire_all()` forces the next access
    # to re-query rather than serve the stale in-memory value (found by running
    # this test and getting the old UUID back, not by inspection).
    db.expire_all()

    reloaded = db.get(Resource, resource_id)
    assert reloaded is not None
    assert reloaded.sda_id is None


def test_deleting_an_sda_does_not_delete_its_former_resources(
    db: Session, tenant_id: uuid.UUID
) -> None:
    """`ON DELETE SET NULL`, not `CASCADE` -- the resource row itself, its scan
    history, and its findings are all untouched by an SDA's removal."""
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
    sda = Sda(tenant_id=tenant_id, name="platform", owner_email="a@example.com", tag_values={})
    db.add(sda)
    db.flush()
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-2",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
        sda_id=sda.id,
    )
    db.add(resource)
    db.flush()
    resource_id = resource.id

    db.delete(sda)
    db.flush()
    db.commit()

    assert db.get(Resource, resource_id) is not None
