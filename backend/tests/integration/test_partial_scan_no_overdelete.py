"""SC-006: a partial scan never over-deletes (FR-031, FR-032).

Forces one region's unit of work to "fail" and confirms only that region's
resources are spared from the deleted-marker sweep -- the other, succeeded region's
absent resource is still correctly marked deleted.
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

from app.models.core import CloudAccount, Resource, Scan
from app.models.enums import AccountStatus, ConnectionMode, ScanStatus, ScanTrigger
from app.scan.orchestrator import finalize_scan, persist_unit_result
from connectors.base import NormalizedResource

pytestmark = pytest.mark.integration


def _resource(arn: str, region: str) -> NormalizedResource:
    return NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id=arn,
        service="ec2",
        resource_type="AWS::EC2::Instance",
        region=region,
        name=None,
        tags={},
        state="running",
        created_at=None,
    )


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    def scoped(self, statement: Any, model: Any) -> Any:
        return statement.where(model.tenant_id == self._tenant_id)

    def add(self, instance: Any) -> None:
        instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()


@pytest.fixture
def db(clean_database: Engine, alembic_config: Any) -> Iterator[tuple[_RawSession, uuid.UUID]]:
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    tenant_id = uuid.UUID(str(session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))
    try:
        yield _RawSession(session, tenant_id), tenant_id
    finally:
        # See test_scan_diffing.py's identical fixture for why this close() is not
        # optional -- an unclosed connection hangs the next test's DROP SCHEMA.
        session.close()


@pytest.fixture
def account(db: tuple[_RawSession, uuid.UUID]) -> CloudAccount:
    session, _ = db
    account = CloudAccount(
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1", "eu-west-1"],
        status=AccountStatus.VERIFIED,
    )
    session.add(account)
    session.flush()
    return account


def test_only_the_failed_regions_resources_are_spared(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    session, _ = db
    healthy_region_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-us"
    failed_region_arn = "arn:aws:ec2:eu-west-1:123456789012:instance/i-eu"

    # Both resources existed before this scan started.
    persist_unit_result(
        session,
        cloud_account_id=account.id,
        resources=[
            _resource(healthy_region_arn, "us-east-1"),
            _resource(failed_region_arn, "eu-west-1"),
        ],
    )
    session.raw.execute(text("UPDATE resource SET last_seen_at = last_seen_at - interval '1 hour'"))
    session.flush()

    scan = Scan(
        cloud_account_id=account.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(scan)
    session.flush()

    # us-east-1's unit succeeds and no longer finds its resource (genuinely
    # deleted). eu-west-1's unit fails outright -- its resource is never
    # re-discovered, but that must NOT be read as "deleted."
    persist_unit_result(session, cloud_account_id=account.id, resources=[])

    final_status = finalize_scan(
        session,
        scan,
        [
            {"status": "succeeded", "region": "us-east-1"},
            {"status": "failed", "region": "eu-west-1"},
        ],
    )

    assert final_status is ScanStatus.PARTIAL
    healthy_row = session.raw.execute(
        select(Resource).where(Resource.arn == healthy_region_arn)
    ).scalar_one()
    failed_region_row = session.raw.execute(
        select(Resource).where(Resource.arn == failed_region_arn)
    ).scalar_one()

    # SC-006's own assertion: the succeeded region's absent resource IS deleted...
    assert healthy_row.deleted_at is not None
    # ...but the failed region's resource is completely untouched.
    assert failed_region_row.deleted_at is None


def test_partial_status_requires_both_a_success_and_a_failure(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    """R-204: partial is its own outcome, not derived loosely."""
    session, _ = db
    scan = Scan(
        cloud_account_id=account.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(scan)
    session.flush()

    all_succeeded = finalize_scan(session, scan, [{"status": "succeeded", "region": "us-east-1"}])
    assert all_succeeded is ScanStatus.SUCCEEDED

    scan2 = Scan(
        cloud_account_id=account.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(scan2)
    session.flush()
    all_failed = finalize_scan(session, scan2, [{"status": "failed", "region": "us-east-1"}])
    assert all_failed is ScanStatus.FAILED
