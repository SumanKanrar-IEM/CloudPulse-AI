"""Scan lifecycle diffing: first-seen/last-seen, and the deleted marker set only for
a completed scan (FR-029, FR-030, SC-003).

Runs against a real PostgreSQL container -- first-seen/last-seen timestamp behavior
and the deleted-marker sweep are real row mutations across two simulated scans, not
something a mocked session should stand in for. Calls
`app/scan/orchestrator.py`'s functions directly (the business logic under test),
not through Step Functions or the Lambda handler -- that plumbing is
test_scan_orchestration.py's concern (T051).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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


def _resource(arn: str, region: str = "us-east-1") -> NormalizedResource:
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
    """A minimal TenantSession-compatible wrapper around a plain SQLAlchemy Session,
    for orchestrator functions that only need `.raw`/`.scoped`/`.add`/`.flush`."""

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
    # Migrate, THEN open a session against the now-migrated schema -- not the
    # conftest `db_session` fixture, which would open its session independently of
    # (and possibly before) this schema setup completes.
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    tenant_id = uuid.UUID(str(session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))
    try:
        yield _RawSession(session, tenant_id), tenant_id
    finally:
        # Without this, the connection stays open and idle-in-transaction, holding a
        # lock the NEXT test's `clean_database` (DROP SCHEMA ... CASCADE) then hangs
        # waiting on indefinitely -- found by running two tests in this file back to
        # back and watching the second one hang, not by inspection.
        session.close()


@pytest.fixture
def account(db: tuple[Any, uuid.UUID]) -> CloudAccount:  # type: ignore[no-untyped-def]
    session, _ = db
    account = CloudAccount(
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    session.add(account)
    session.flush()
    return account


def test_first_seen_preserved_last_seen_updated_across_two_scans(
    db: tuple[Any, uuid.UUID], account: CloudAccount
) -> None:
    session, _ = db
    arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-persistent"

    persist_unit_result(session, cloud_account_id=account.id, resources=[_resource(arn)])
    first_row = session.raw.execute(select(Resource).where(Resource.arn == arn)).scalar_one()
    first_seen = first_row.first_seen_at
    original_last_seen = first_row.last_seen_at

    # Force real timestamp separation rather than trusting wall-clock speed.
    session.raw.execute(
        text("UPDATE resource SET last_seen_at = :t WHERE arn = :arn"),
        {"t": original_last_seen - timedelta(hours=1), "arn": arn},
    )
    session.flush()

    persist_unit_result(session, cloud_account_id=account.id, resources=[_resource(arn)])
    second_row = session.raw.execute(select(Resource).where(Resource.arn == arn)).scalar_one()

    assert second_row.first_seen_at == first_seen  # FR-029: preserved
    assert second_row.last_seen_at > original_last_seen - timedelta(hours=1)  # refreshed


def test_deleted_marker_set_only_on_a_completed_scan(
    db: tuple[Any, uuid.UUID], account: CloudAccount
) -> None:
    """FR-030/SC-003: a resource absent from a new, successfully completed scan is
    marked deleted; one still present is not."""
    session, _ = db
    survives_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-survives"
    deleted_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-deleted"

    persist_unit_result(
        session,
        cloud_account_id=account.id,
        resources=[_resource(survives_arn), _resource(deleted_arn)],
    )
    # Both resources' last_seen_at predates the next scan's started_at.
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

    # This scan only re-discovers `survives_arn` -- `deleted_arn` was not found.
    persist_unit_result(session, cloud_account_id=account.id, resources=[_resource(survives_arn)])

    final_status = finalize_scan(session, scan, [{"status": "succeeded", "region": "us-east-1"}])

    assert final_status is ScanStatus.SUCCEEDED
    survives_row = session.raw.execute(
        select(Resource).where(Resource.arn == survives_arn)
    ).scalar_one()
    deleted_row = session.raw.execute(
        select(Resource).where(Resource.arn == deleted_arn)
    ).scalar_one()
    assert survives_row.deleted_at is None
    assert deleted_row.deleted_at is not None


def test_a_failed_scan_never_marks_anything_deleted(
    db: tuple[Any, uuid.UUID], account: CloudAccount
) -> None:
    """FR-031: a scan that fails before completing must not cause any deletion."""
    session, _ = db
    arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-untouched"
    persist_unit_result(session, cloud_account_id=account.id, resources=[_resource(arn)])
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

    final_status = finalize_scan(session, scan, [{"status": "failed", "region": "us-east-1"}])

    assert final_status is ScanStatus.FAILED
    row = session.raw.execute(select(Resource).where(Resource.arn == arn)).scalar_one()
    assert row.deleted_at is None
