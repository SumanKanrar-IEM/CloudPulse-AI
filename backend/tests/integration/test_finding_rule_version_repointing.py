"""research.md R-301: a finding follows a rule's stable key across edits,
rather than being permanently pinned to the version that first opened it
(Clarifications session 2026-08-25, FR-006, FR-015, FR-016, SC-002).

The decisive test: open a finding under rule version 1, edit the rule to
version 2, re-evaluate, confirm the *same finding row* now points at version 2
and can auto-close under version 2's criteria -- the specific correctness risk
the Clarifications session exists to prevent (a naive `rule_id`-only lookup
would orphan the finding the moment the rule is edited, since `Rule` gives
every edit a new row).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.governance.validation import validate_account
from app.models.core import CloudAccount, Finding, Resource
from app.models.core import Rule as RuleRow
from app.models.enums import AccountStatus, ConnectionMode, FindingStatus

pytestmark = pytest.mark.integration

# migration 0010 seeds five rules against the single seeded tenant -- disabled in
# every test here (and given fresh, non-seeded keys for anything created) so this
# file's own rule set is the only one `validate_account` evaluates against, and
# to avoid the uq_rule_tenant_key_version collision an insert at version=1 under
# a seeded key would hit.


def _disable_seeded_rules(db: Session) -> None:
    db.execute(update(RuleRow).values(enabled=False))
    db.flush()


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


def test_a_finding_follows_its_rule_across_an_edit(
    db: tuple[_RawSession, Session, uuid.UUID],
) -> None:
    tenant_session, raw, tenant_id = db
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
    _disable_seeded_rules(raw)

    rule_v1 = RuleRow(
        tenant_id=tenant_id,
        key="custom_id",
        version=1,
        definition={"required": True, "allowed_values": ["PROJ-0001"]},
        enabled=True,
    )
    raw.add(rule_v1)
    raw.flush()

    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={"custom_id": "PROJ-9999"},  # violates v1's allowed_values
    )
    raw.add(resource)
    raw.flush()

    # --- Round 1: violates version 1, a finding opens pinned to it ---
    validate_account(tenant_session, account.id)  # type: ignore[arg-type]
    findings = (
        raw.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    )
    assert len(findings) == 1
    original_finding_id = findings[0].id
    assert findings[0].rule_id == rule_v1.id
    assert findings[0].rule_version == 1
    assert findings[0].status == FindingStatus.OPEN

    # --- Edit the rule: version 2, now allowing PROJ-9999 ---
    rule_v2 = RuleRow(
        tenant_id=tenant_id,
        key="custom_id",  # same key -- research.md R-301's stable identity
        version=2,
        definition={"required": True, "allowed_values": ["PROJ-9999"]},
        enabled=True,
    )
    raw.add(rule_v2)
    raw.flush()

    # --- Round 2: re-evaluate under version 2 ---
    validate_account(tenant_session, account.id)  # type: ignore[arg-type]
    raw.expire_all()

    findings_after = (
        raw.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    )
    # The decisive assertion: still exactly one finding row, the SAME one,
    # now closed under version 2's criteria -- not a new row, and not stuck
    # open forever against a superseded version 1 no future scan re-checks.
    assert len(findings_after) == 1
    assert findings_after[0].id == original_finding_id
    assert findings_after[0].rule_id == rule_v2.id
    assert findings_after[0].rule_version == 2
    assert findings_after[0].status == FindingStatus.RESOLVED


def test_a_still_violating_finding_re_points_without_duplicating(
    db: tuple[_RawSession, Session, uuid.UUID],
) -> None:
    """The edit doesn't fix the violation this time -- the same row still gets
    re-pointed to the new version, not left stale and not duplicated."""
    tenant_session, raw, tenant_id = db
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
    _disable_seeded_rules(raw)
    rule_v1 = RuleRow(
        tenant_id=tenant_id,
        key="team",
        version=1,
        definition={"required": True, "severity": "low"},
        enabled=True,
    )
    raw.add(rule_v1)
    raw.flush()
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-2",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
    )
    raw.add(resource)
    raw.flush()

    validate_account(tenant_session, account.id)  # type: ignore[arg-type]
    original_id = (
        raw.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().one().id
    )

    rule_v2 = RuleRow(
        tenant_id=tenant_id,
        key="team",
        version=2,
        definition={"required": True, "severity": "critical"},  # still required
        enabled=True,
    )
    raw.add(rule_v2)
    raw.flush()

    validate_account(tenant_session, account.id)  # type: ignore[arg-type]
    raw.expire_all()

    findings = (
        raw.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    )
    assert len(findings) == 1
    assert findings[0].id == original_id
    assert findings[0].rule_version == 2
    assert findings[0].severity.value == "critical"
    assert findings[0].status == FindingStatus.OPEN
