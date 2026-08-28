"""Compliance scoring: the formula in isolation, then against a hand-counted
account and a hand-counted SDA, proving the DB-backed count matches a manual
tally exactly (S20, FR-018, FR-019a, SC-003).

Moved from tests/unit/ to tests/integration/ -- same precedent as T004/T008/T013:
"matches a manual tally" (SC-003) can only be proven against real `Resource`/
`Finding` rows, not by asserting the pure formula runs.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.governance.scoring import account_compliance_score, compute_score, sda_compliance_score
from app.models.core import CloudAccount, Finding, Resource
from app.models.core import Rule as RuleRow
from app.models.core import Sda as SdaRow
from app.models.enums import AccountStatus, ConnectionMode, FindingSeverity, FindingStatus

pytestmark = pytest.mark.integration


class TestComputeScore:
    def test_zero_total_is_well_defined_not_an_error(self) -> None:
        """FR-019a: a scope with no top-level resources is fully compliant by
        definition, not a division error."""
        assert compute_score(0, 0) == 1.0

    def test_matches_a_hand_count(self) -> None:
        assert compute_score(3, 4) == 0.75

    def test_all_compliant_is_one(self) -> None:
        assert compute_score(5, 5) == 1.0


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
    tid = uuid.UUID(str(db.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))
    db.execute(update(RuleRow).values(enabled=False))
    db.flush()
    return tid


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


def _resource(
    db: Session,
    tenant_id: uuid.UUID,
    account: CloudAccount,
    arn: str,
    sda_id: uuid.UUID | None = None,
) -> Resource:
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn=arn,
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
        sda_id=sda_id,
    )
    db.add(resource)
    db.flush()
    return resource


def _open_finding(db: Session, tenant_id: uuid.UUID, resource: Resource) -> Finding:
    rule = RuleRow(
        tenant_id=tenant_id, key=f"k-{uuid.uuid4().hex[:8]}", version=1, definition={}, enabled=True
    )
    db.add(rule)
    db.flush()
    finding = Finding(
        tenant_id=tenant_id,
        resource_id=resource.id,
        rule_id=rule.id,
        rule_version=1,
        severity=FindingSeverity.MEDIUM,
        status=FindingStatus.OPEN,
    )
    db.add(finding)
    db.flush()
    return finding


def test_account_score_matches_a_hand_count(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Hand count: 4 top-level resources, 1 with an open finding -> 3/4 = 0.75."""
    session = _RawSession(db, tenant_id)
    compliant_a = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-1"
    )
    compliant_b = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-2"
    )
    compliant_c = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-3"
    )
    non_compliant = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-4"
    )
    _open_finding(db, tenant_id, non_compliant)
    del compliant_a, compliant_b, compliant_c

    compliant_count, total_count, score = account_compliance_score(session, account.id)  # type: ignore[arg-type]

    assert (compliant_count, total_count) == (3, 4)
    assert score == 0.75


def test_a_resolved_finding_does_not_count_against_the_score(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """SC-003: only OPEN findings make a resource non-compliant."""
    session = _RawSession(db, tenant_id)
    resource = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-5")
    finding = _open_finding(db, tenant_id, resource)
    finding.status = FindingStatus.RESOLVED
    finding.resolved_at = datetime.now(UTC)
    db.flush()

    compliant_count, total_count, score = account_compliance_score(session, account.id)  # type: ignore[arg-type]

    assert (compliant_count, total_count) == (1, 1)
    assert score == 1.0


def test_a_child_resource_is_excluded_from_both_counts(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """The score follows T016's canonical top-level-only definition -- a child
    resource is never counted, compliant or not."""
    session = _RawSession(db, tenant_id)
    parent = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-6")
    child = _resource(db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:volume/vol-1")
    child.parent_resource_id = parent.id
    _open_finding(db, tenant_id, child)
    db.flush()

    compliant_count, total_count, score = account_compliance_score(session, account.id)  # type: ignore[arg-type]

    assert (compliant_count, total_count) == (1, 1)
    assert score == 1.0


def test_account_score_is_well_defined_at_zero_resources(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    session = _RawSession(db, tenant_id)
    compliant_count, total_count, score = account_compliance_score(session, account.id)  # type: ignore[arg-type]
    assert (compliant_count, total_count, score) == (0, 0, 1.0)


def test_sda_score_reflects_only_that_sdas_resources(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """Acceptance Scenario US4.2: a specific SDA's score reflects only that
    SDA's resources, not the whole account's."""
    session = _RawSession(db, tenant_id)
    sda_a = SdaRow(
        tenant_id=tenant_id, name="Team A", owner_email="a@example.com", tag_values={"team": "a"}
    )
    sda_b = SdaRow(
        tenant_id=tenant_id, name="Team B", owner_email="b@example.com", tag_values={"team": "b"}
    )
    db.add(sda_a)
    db.add(sda_b)
    db.flush()

    a_compliant = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-7", sda_id=sda_a.id
    )
    a_non_compliant = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-8", sda_id=sda_a.id
    )
    _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-9", sda_id=sda_b.id
    )
    _open_finding(db, tenant_id, a_non_compliant)
    del a_compliant

    compliant_count, total_count, score = sda_compliance_score(session, sda_a.id)  # type: ignore[arg-type]

    assert (compliant_count, total_count) == (1, 2)
    assert score == 0.5


def test_sda_score_is_well_defined_for_a_freshly_registered_sda(
    db: Session, tenant_id: uuid.UUID
) -> None:
    """Acceptance Scenario US4.3: a freshly registered SDA with no matched
    resources yet gets a well-defined score, not a divide-by-zero failure."""
    session = _RawSession(db, tenant_id)
    sda = SdaRow(
        tenant_id=tenant_id, name="Team C", owner_email="c@example.com", tag_values={"team": "c"}
    )
    db.add(sda)
    db.flush()

    compliant_count, total_count, score = sda_compliance_score(session, sda.id)  # type: ignore[arg-type]

    assert (compliant_count, total_count, score) == (0, 0, 1.0)
