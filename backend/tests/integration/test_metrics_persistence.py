"""FR-019's no-duplicate rule, against the constraint that enforces it (spec
006, T039; S50).

User Story 4's independent test: a second run for a period already collected
neither duplicates nor overwrites it. The one deliberate exception -- a row
recorded as unavailable is upgraded when a later run has a value -- is asserted
too, in both directions, because the conditional `WHERE` on the upsert is the
part a refactor would most plausibly drop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import sessionmaker

import app.core.db as db_module
from app.core.db import tenant_session
from app.governance.metrics import (
    Measurement,
    MeteredResource,
    metered_resources,
    period_start_for,
    persist_measurements,
)
from app.models.core import CloudAccount, Resource, ResourceMetric
from app.models.enums import AccountStatus, ConnectionMode, ResourceMetricKind

pytestmark = pytest.mark.integration

PERIOD = period_start_for(datetime(2026, 3, 1, tzinfo=UTC).date())


@pytest.fixture
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def seed(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> dict[str, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    session = sessionmaker(bind=clean_database)()
    account = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="a",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    session.add(account)
    session.flush()
    instance = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
        detail={},
    )
    bucket = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:s3:::not-metered",
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-east-1",
        tags={},
        detail={},
    )
    session.add_all([instance, bucket])
    session.commit()
    ids = {"account": account.id, "instance": instance.id}
    session.close()
    return ids


def _rows(tenant_id: uuid.UUID) -> list[tuple[ResourceMetricKind, Decimal | None, bool]]:
    with tenant_session(tenant_id) as session:
        return [
            (r.metric, r.value, r.is_unavailable)
            for r in session.raw.execute(
                session.scoped(select(ResourceMetric), ResourceMetric).order_by(
                    ResourceMetric.metric
                )
            ).scalars()
        ]


def _measure(
    resource_id: uuid.UUID, kind: ResourceMetricKind, value: Decimal | None
) -> Measurement:
    return Measurement(resource_id=resource_id, metric=kind, period_start=PERIOD, value=value)


def test_only_metered_types_are_selected(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    with tenant_session(real_tenant_id) as session:
        selected = metered_resources(session, cloud_account_id=seed["account"])

    assert selected == [
        MeteredResource(
            resource_id=seed["instance"],
            resource_type="AWS::EC2::Instance",
            arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
            region="us-east-1",
        )
    ]


def test_a_second_run_for_the_same_period_neither_duplicates_nor_overwrites(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """Acceptance scenario 2, and the "nor overwrites" half of the independent
    test: a different value on the second run does not replace the first."""
    with tenant_session(real_tenant_id) as session:
        first = persist_measurements(
            session, [_measure(seed["instance"], ResourceMetricKind.CPU, Decimal("10"))]
        )
        session.commit()
    with tenant_session(real_tenant_id) as session:
        second = persist_measurements(
            session, [_measure(seed["instance"], ResourceMetricKind.CPU, Decimal("99"))]
        )
        session.commit()

    assert (first, second) == (1, 0)
    assert _rows(real_tenant_id) == [(ResourceMetricKind.CPU, Decimal("10.0000"), False)]


def test_an_unavailable_row_is_upgraded_when_a_later_run_has_a_value(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """The one permitted overwrite. CloudWatch publishes with a lag; the first
    run after midnight can honestly find nothing."""
    with tenant_session(real_tenant_id) as session:
        persist_measurements(session, [_measure(seed["instance"], ResourceMetricKind.CPU, None)])
        session.commit()
    assert _rows(real_tenant_id) == [(ResourceMetricKind.CPU, None, True)]

    with tenant_session(real_tenant_id) as session:
        upgraded = persist_measurements(
            session, [_measure(seed["instance"], ResourceMetricKind.CPU, Decimal("42"))]
        )
        session.commit()

    assert upgraded == 1
    assert _rows(real_tenant_id) == [(ResourceMetricKind.CPU, Decimal("42.0000"), False)]


def test_a_measured_row_is_never_downgraded_to_unavailable(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """The other direction of the same WHERE clause. A later run that hears
    nothing must not erase a number an earlier run heard."""
    with tenant_session(real_tenant_id) as session:
        persist_measurements(
            session, [_measure(seed["instance"], ResourceMetricKind.CPU, Decimal("42"))]
        )
        session.commit()
    with tenant_session(real_tenant_id) as session:
        touched = persist_measurements(
            session, [_measure(seed["instance"], ResourceMetricKind.CPU, None)]
        )
        session.commit()

    assert touched == 0
    assert _rows(real_tenant_id) == [(ResourceMetricKind.CPU, Decimal("42.0000"), False)]


def test_unknown_is_stored_as_null_and_flagged_never_as_zero(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID]
) -> None:
    """Acceptance scenario 3, at the row. The check constraint makes the
    inverse shape -- a flag with a value, or a value with no flag -- a database
    error, so this is asserting the shape the constraint permits."""
    with tenant_session(real_tenant_id) as session:
        persist_measurements(session, [_measure(seed["instance"], ResourceMetricKind.MEMORY, None)])
        session.commit()

    assert _rows(real_tenant_id) == [(ResourceMetricKind.MEMORY, None, True)]
