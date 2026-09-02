"""research.md R-508: `finding.kind` discriminates a tag-violation finding
(spec 003's original shape) from a budget-overrun one (spec 005's addition),
enforced by `ck_finding_kind_shape` -- not just application-layer discipline.

Also confirms the pre-existing `uq_finding_open_per_resource_rule` partial
index still refuses a duplicate open tag-violation finding, and that a
budget-overrun row's NULL `resource_id`/`rule_id` never collides with it
(data-model.md's own note: Postgres never treats two NULLs as matching in a
unique index).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.core import CloudAccount, Finding, Resource, Sda
from app.models.core import Rule as RuleRow
from app.models.enums import AccountStatus, ConnectionMode, FindingKind, FindingSeverity

pytestmark = pytest.mark.integration


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    def add(self, instance: Any) -> None:
        instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()


@pytest.fixture
def db(
    clean_database: Engine, alembic_config: Any
) -> Iterator[tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]]:
    """Upgraded schema plus one account/resource/rule/sda, ready for a Finding."""
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

    resource = Resource(
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    db.add(resource)
    db.flush()

    rule = RuleRow(key="owner", version=99, definition={"required": True}, enabled=False)
    db.add(rule)
    db.flush()

    sda = Sda(name="platform-team", owner_email="owner@example.com")
    db.add(sda)
    db.flush()

    try:
        yield db, tenant_id, account.id, resource.id, sda.id
    finally:
        session.close()


def _tag_violation(resource_id: uuid.UUID, rule_id: uuid.UUID) -> Finding:
    return Finding(
        kind=FindingKind.TAG_VIOLATION,
        resource_id=resource_id,
        rule_id=rule_id,
        rule_version=99,
        severity=FindingSeverity.MEDIUM,
    )


def _budget_overrun(sda_id: uuid.UUID) -> Finding:
    return Finding(
        kind=FindingKind.BUDGET_OVERRUN,
        sda_id=sda_id,
        severity=FindingSeverity.HIGH,
    )


def test_a_tag_violation_finding_with_sda_id_set_is_rejected(
    db: tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    session, _tenant_id, _account_id, resource_id, sda_id = db
    finding = _tag_violation(resource_id, uuid.uuid4())
    finding.sda_id = sda_id  # violates ck_finding_kind_shape
    session.add(finding)
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_budget_overrun_finding_with_resource_id_set_is_rejected(
    db: tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    session, _tenant_id, _account_id, resource_id, sda_id = db
    finding = _budget_overrun(sda_id)
    finding.resource_id = resource_id  # violates ck_finding_kind_shape
    session.add(finding)
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_valid_tag_violation_finding_is_accepted(
    db: tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    session, _tenant_id, _account_id, resource_id, _sda_id = db
    rule_id = uuid.uuid4()
    session.raw.execute(
        text(
            "INSERT INTO rule (id, tenant_id, key, version, definition, enabled) "
            "VALUES (:id, :tenant_id, 'inline', 1, '{}', true)"
        ),
        {"id": rule_id, "tenant_id": _tenant_id},
    )
    session.flush()
    session.add(_tag_violation(resource_id, rule_id))
    session.flush()  # must not raise


def test_a_valid_budget_overrun_finding_is_accepted(
    db: tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    session, _tenant_id, _account_id, _resource_id, sda_id = db
    session.add(_budget_overrun(sda_id))
    session.flush()  # must not raise


def test_a_second_open_tag_violation_on_the_same_resource_and_rule_is_refused(
    db: tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    session, tenant_id, _account_id, resource_id, _sda_id = db
    rule_id = uuid.uuid4()
    session.raw.execute(
        text(
            "INSERT INTO rule (id, tenant_id, key, version, definition, enabled) "
            "VALUES (:id, :tenant_id, 'inline', 1, '{}', true)"
        ),
        {"id": rule_id, "tenant_id": tenant_id},
    )
    session.flush()
    session.add(_tag_violation(resource_id, rule_id))
    session.flush()

    # spec 003's own pre-existing invariant, unchanged by this migration.
    session.add(_tag_violation(resource_id, rule_id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_two_open_budget_overrun_findings_never_collide_on_null_resource_and_rule(
    db: tuple[_RawSession, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """data-model.md's own note: a Postgres unique index never treats two NULLs
    as matching, so `uq_finding_open_per_resource_rule` (keyed on resource_id/
    rule_id) cannot see two budget_overrun rows as duplicates of each other --
    only `uq_finding_open_overrun_per_sda` (keyed on sda_id) can, and does."""
    session, tenant_id, _account_id, _resource_id, sda_id = db
    session.add(_budget_overrun(sda_id))
    session.flush()

    other_sda = Sda(name="other-team", owner_email="other@example.com")
    session.add(other_sda)
    session.flush()

    # A second, different SDA's overrun finding: must succeed -- proves the
    # resource/rule-keyed index alone never blocked a second budget_overrun row.
    session.add(_budget_overrun(other_sda.id))
    session.flush()

    # The SAME sda a second time: must be refused by uq_finding_open_overrun_per_sda.
    session.add(_budget_overrun(sda_id))
    with pytest.raises(IntegrityError):
        session.flush()
