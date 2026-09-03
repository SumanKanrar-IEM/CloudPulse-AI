"""`app.governance.spend.ingest_spend_rows` against a real PostgreSQL --
correction-in-place, the explicit gap fallback, and migration 0013's
NULL-safe uniqueness fix (spec 005, FR-001, FR-002a). Not unit-testable:
`ON CONFLICT` has no meaning without a real unique index to conflict
against, and this is exactly the class of "only a real engine proves it"
correctness `test_migrations.py`'s own docstring already establishes for
this project (native partial unique indexes).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.governance.spend import ingest_spend_rows
from app.models.core import CloudAccount, SpendRecord
from app.models.core import Sda as SdaRow
from app.models.enums import AccountStatus, ConnectionMode

pytestmark = pytest.mark.integration

DAY = date(2026, 9, 1)


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self.raw = session
        self.tenant_id = tenant_id

    def scoped(self, statement: Any, model: Any) -> Any:
        return statement.where(model.tenant_id == self.tenant_id)

    def add(self, instance: Any) -> None:
        instance.tenant_id = self.tenant_id
        self.raw.add(instance)

    def flush(self) -> None:
        self.raw.flush()


@pytest.fixture
def db(
    clean_database: Engine, alembic_config: Any, settings_env: None
) -> Iterator[tuple[_RawSession, CloudAccount]]:
    from app.core.config import get_settings

    get_settings.cache_clear()  # settings_env's values, not a stale prior test's
    command.upgrade(alembic_config, "head")
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    tenant_id = uuid.UUID(str(session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))
    db = _RawSession(session, tenant_id)

    account = CloudAccount(
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add(account)
    db.flush()

    try:
        yield db, account
    finally:
        session.close()


def _rows(
    *, service: str = "AmazonEC2", tag_value: str | None, amount: str
) -> list[dict[str, Any]]:
    return [{"service": service, "tag_value": tag_value, "amount_usd": Decimal(amount)}]


def _all_spend_records(session: _RawSession) -> list[SpendRecord]:
    return list(
        session.raw.execute(session.scoped(select(SpendRecord), SpendRecord)).scalars().all()
    )


def test_a_gap_is_recorded_when_rows_is_none(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    session, account = db
    ingest_spend_rows(session, account, DAY, None)
    records = _all_spend_records(session)
    assert len(records) == 1
    assert records[0].is_gap is True
    assert records[0].amount_usd is None
    assert records[0].service is None


def test_a_second_gap_for_the_same_day_does_not_duplicate(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    session, account = db
    ingest_spend_rows(session, account, DAY, None)
    ingest_spend_rows(session, account, DAY, None)
    assert len(_all_spend_records(session)) == 1


def test_a_successful_ingestion_with_zero_rows_is_not_a_gap(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    """`rows=[]` (a real call that found no cost) is a fact, not a failure."""
    session, account = db
    ingest_spend_rows(session, account, DAY, [])
    assert _all_spend_records(session) == []


def test_an_untagged_row_lands_in_the_no_sda_bucket(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    session, account = db
    ingest_spend_rows(session, account, DAY, _rows(tag_value=None, amount="5.00"))
    records = _all_spend_records(session)
    assert len(records) == 1
    assert records[0].sda_id is None
    assert records[0].amount_usd == Decimal("5.00")


def test_a_tagged_row_attributes_to_the_matching_sda(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    session, account = db
    sda = SdaRow(name="platform", owner_email="p@example.com", tag_values={"project_id": "proj-a"})
    session.add(sda)
    session.flush()

    ingest_spend_rows(session, account, DAY, _rows(tag_value="proj-a", amount="10.00"))
    records = _all_spend_records(session)
    assert len(records) == 1
    assert records[0].sda_id == sda.id


def test_a_repeat_ingestion_for_the_no_sda_bucket_corrects_in_place(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    """The decisive test migration 0013 exists for: a plain UniqueConstraint
    including a nullable sda_id would have let this insert a *second* row
    instead of correcting the first, since Postgres never treats two NULLs
    as equal."""
    session, account = db
    ingest_spend_rows(session, account, DAY, _rows(tag_value=None, amount="5.00"))
    ingest_spend_rows(session, account, DAY, _rows(tag_value=None, amount="7.50"))

    records = _all_spend_records(session)
    assert len(records) == 1
    assert records[0].amount_usd == Decimal("7.50")


def test_a_repeat_ingestion_for_a_real_sda_corrects_in_place(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    session, account = db
    sda = SdaRow(name="platform", owner_email="p@example.com", tag_values={"project_id": "proj-a"})
    session.add(sda)
    session.flush()

    ingest_spend_rows(session, account, DAY, _rows(tag_value="proj-a", amount="10.00"))
    ingest_spend_rows(session, account, DAY, _rows(tag_value="proj-a", amount="12.00"))

    records = _all_spend_records(session)
    assert len(records) == 1
    assert records[0].amount_usd == Decimal("12.00")


def test_the_no_sda_bucket_and_a_real_sda_never_collide_for_the_same_service_and_day(
    db: tuple[_RawSession, CloudAccount],
) -> None:
    """Two distinct rows for the same (account, service, day) -- one
    attributed, one not -- must coexist, not be treated as duplicates of
    each other."""
    session, account = db
    sda = SdaRow(name="platform", owner_email="p@example.com", tag_values={"project_id": "proj-a"})
    session.add(sda)
    session.flush()

    ingest_spend_rows(session, account, DAY, _rows(tag_value="proj-a", amount="10.00"))
    ingest_spend_rows(session, account, DAY, _rows(tag_value=None, amount="3.00"))

    records = _all_spend_records(session)
    assert len(records) == 2
    assert {r.sda_id for r in records} == {sda.id, None}
