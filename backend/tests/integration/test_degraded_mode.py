"""The intelligence layer being unavailable changes nothing deterministic
(T011a; spec 006, FR-007, FR-007a, SC-009).

**Scope note.** T011a as written also asserts that `GET /insights/digest` serves
the last valid digest or the not-enough-data state. Those routes are T018's, in
Phase 3, so that half is asserted there as **T018a** — a Phase 2 test cannot
exercise a Phase 3 surface, and stubbing one to satisfy the ordering would prove
nothing. What is testable now is the half that matters more: that no
deterministic capability changes behaviour, which is SC-009's own comparison and
the reason P1 is shippable under R-605 at all.

The comparison is byte-identical output from the same fixture, run with and
without the agent tables populated. A prose claim of no regression is not
evidence; a diff of two runs is.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.governance.agent_runs import RunBudget, outcome_for
from app.governance.scoring import account_compliance_score
from app.models.core import CloudAccount, Resource
from app.models.core import Finding as FindingRow
from app.models.core import Rule as RuleRow
from app.models.enums import (
    AccountStatus,
    AgentRunStatus,
    ConnectionMode,
    FindingKind,
    FindingSeverity,
    FindingStatus,
)

pytestmark = pytest.mark.integration


class _RawSession:
    """The `TenantSession`-shaped shim this suite already uses."""

    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    @property
    def tenant_id(self) -> uuid.UUID:
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
def seeded(db: Session, tenant_id: uuid.UUID) -> CloudAccount:
    """A fixed governance fixture: two resources, one failing a rule."""
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

    rule = db.query(RuleRow).filter_by(tenant_id=tenant_id, key="owner", version=1).one()
    for index in (1, 2):
        resource = Resource(
            tenant_id=tenant_id,
            cloud_account_id=account.id,
            arn=f"arn:aws:s3:::bucket-{index}",
            resource_type="AWS::S3::Bucket",
            service="s3",
            region="us-east-1",
            tags={},
        )
        db.add(resource)
        db.flush()
        if index == 1:
            db.add(
                FindingRow(
                    tenant_id=tenant_id,
                    resource_id=resource.id,
                    rule_id=rule.id,
                    rule_version=1,
                    kind=FindingKind.TAG_VIOLATION,
                    severity=FindingSeverity.HIGH,
                    status=FindingStatus.OPEN,
                )
            )
    db.commit()
    return account


def _deterministic_snapshot(db: Session, tenant_id: uuid.UUID, account_id: uuid.UUID) -> str:
    """Everything FR-007 names as deterministic, rendered for exact comparison."""
    session = _RawSession(db, tenant_id)
    score = account_compliance_score(session, account_id)
    resources = db.execute(
        text("SELECT arn, resource_type, state FROM resource WHERE tenant_id = :t ORDER BY arn"),
        {"t": tenant_id},
    ).all()
    findings = db.execute(
        text(
            "SELECT resource_id, rule_version, severity, status FROM finding "
            "WHERE tenant_id = :t ORDER BY resource_id"
        ),
        {"t": tenant_id},
    ).all()
    return repr((score, resources, findings))


def test_the_deterministic_core_is_byte_identical_with_and_without_the_agent_layer(
    db: Session, tenant_id: uuid.UUID, seeded: CloudAccount
) -> None:
    """SC-009's own stated comparison. Populating every agent table must not move
    inventory, findings, or the compliance score by a single byte."""
    before = _deterministic_snapshot(db, tenant_id, seeded.id)

    run_id = db.execute(
        text(
            "INSERT INTO agent_run (tenant_id, capability, definition_hash, status, cost_units, "
            "cost_cap_units, failure_reason) VALUES (:t, 'digest', 'h', 'failed', 0, 100, "
            "'endpoint unreachable') RETURNING id"
        ),
        {"t": tenant_id},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO grounding_rejection (tenant_id, agent_run_id, rejected_reference, "
            "reference_kind) VALUES (:t, :r, 'arn:aws:ec2:::i-fake', 'arn')"
        ),
        {"t": tenant_id, "r": run_id},
    )
    db.commit()

    assert _deterministic_snapshot(db, tenant_id, seeded.id) == before


def test_an_unreachable_model_is_recorded_as_failed_with_a_reason(
    db: Session, tenant_id: uuid.UUID
) -> None:
    """FR-007a: the run is recorded, not silently absent. A missing row and a
    failed row look the same to a dashboard but very different to an admin
    asking why there is no digest today."""
    status, reason = outcome_for(
        RunBudget(cap_units=Decimal("100")),
        completed=False,
        error="bedrock agent invocation failed: EndpointConnectionError",
    )
    assert status is AgentRunStatus.FAILED
    assert reason is not None

    db.execute(
        text(
            "INSERT INTO agent_run (tenant_id, capability, definition_hash, status, cost_units, "
            "cost_cap_units, failure_reason) VALUES (:t, 'digest', 'h', :s, 0, 100, :reason)"
        ),
        {"t": tenant_id, "s": status.value, "reason": reason},
    )
    db.commit()

    stored = db.execute(
        text("SELECT status, failure_reason FROM agent_run WHERE tenant_id = :t"),
        {"t": tenant_id},
    ).one()
    assert stored.status == "failed"
    assert "EndpointConnectionError" in stored.failure_reason


def test_a_tenant_with_no_agent_run_still_serves_its_deterministic_data(
    db: Session, tenant_id: uuid.UUID, seeded: CloudAccount
) -> None:
    """The new-tenant and never-ran-successfully cases are the same state, and
    neither may degrade anything spec 001-005 built."""
    assert (
        db.execute(
            text("SELECT count(*) FROM agent_run WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalar_one()
        == 0
    )

    snapshot = _deterministic_snapshot(db, tenant_id, seeded.id)
    assert "bucket-1" in snapshot
    assert "bucket-2" in snapshot
