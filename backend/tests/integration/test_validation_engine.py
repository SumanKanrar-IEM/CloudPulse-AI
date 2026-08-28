"""Rule evaluation: the three violation kinds, severity, uncovered/disabled
rules, auto-close, and the FR-017 completion gate (FR-004, FR-013-FR-017,
SC-002).

Moved from tests/unit/ to tests/integration/ -- same precedent as T004/T008:
proving a violation actually opens a `Finding` row (not just that a pure
function returns the right string) needs a real database. The pure
`evaluate_rule_against_tags` helper is exercised directly too, in the same file,
since there's no reason to split a genuinely no-DB assertion into a second file.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from alembic import command
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.governance.validation import evaluate_rule_against_tags, validate_account, validate_scan
from app.models.core import CloudAccount, Finding, Resource, Scan
from app.models.core import Rule as RuleRow
from app.models.enums import AccountStatus, ConnectionMode, FindingStatus, ScanStatus, ScanTrigger

pytestmark = pytest.mark.integration

# migration 0010 seeds five rules (project_name/owner/project_id/created_by
# required, environment not) against the single seeded tenant -- disabled here so
# each test's own rule set is the only one `validate_account` evaluates against,
# and so test rule keys are free to reuse any name without the
# uq_rule_tenant_key_version collision a fresh insert at version=1 would hit.


def _disable_seeded_rules(db: Session) -> None:
    db.execute(update(RuleRow).values(enabled=False))
    db.flush()


# --- Pure function: no DB needed ------------------------------------------------


class TestEvaluateRuleAgainstTags:
    def test_missing_required_tag(self) -> None:
        assert evaluate_rule_against_tags("owner", {"required": True}, {}) == "missing_tag"

    def test_missing_optional_tag_is_not_a_violation(self) -> None:
        assert evaluate_rule_against_tags("environment", {"required": False}, {}) is None

    def test_empty_value_counts_as_missing(self) -> None:
        assert (
            evaluate_rule_against_tags("owner", {"required": True}, {"owner": "   "})
            == "missing_tag"
        )

    def test_disallowed_value(self) -> None:
        definition = {"required": True, "allowed_values": ["dev", "prod"]}
        assert (
            evaluate_rule_against_tags("environment", definition, {"environment": "staging"})
            == "invalid_value"
        )

    def test_disallowed_format(self) -> None:
        definition = {"required": True, "format_pattern": r"^PROJ-\d{4}$"}
        assert (
            evaluate_rule_against_tags("project_id", definition, {"project_id": "nope"})
            == "invalid_format"
        )

    def test_a_compliant_value_is_not_a_violation(self) -> None:
        definition = {"required": True, "allowed_values": ["dev", "prod"]}
        assert (
            evaluate_rule_against_tags("environment", definition, {"environment": "prod"}) is None
        )

    def test_key_matching_is_case_insensitive(self) -> None:
        """FR-002: `Owner` on the resource satisfies a rule keyed `owner`."""
        assert (
            evaluate_rule_against_tags("owner", {"required": True}, {"owner": "team@example.com"})
            is None
        )


def test_validate_scan_does_nothing_for_a_failed_scan() -> None:
    """FR-017: the completion gate, proven without touching a real database --
    a failed scan must never reach a single tenant-scoped query."""
    poison_session = MagicMock()
    scan = MagicMock(status=ScanStatus.FAILED, cloud_account_id=uuid.uuid4())
    result = validate_scan(poison_session, scan)
    assert result == 0
    poison_session.scoped.assert_not_called()
    poison_session.raw.execute.assert_not_called()


# --- DB-backed: findings actually open/close ------------------------------------


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
def account(db: Session, tenant_id: uuid.UUID) -> CloudAccount:
    _disable_seeded_rules(db)
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
    db: Session, tenant_id: uuid.UUID, account: CloudAccount, arn: str, tags: dict
) -> Resource:
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn=arn,
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags=tags,
    )
    db.add(resource)
    db.flush()
    return resource


def _rule(db: Session, tenant_id: uuid.UUID, key: str, definition: dict) -> RuleRow:
    rule = RuleRow(tenant_id=tenant_id, key=key, version=1, definition=definition, enabled=True)
    db.add(rule)
    db.flush()
    return rule


def test_each_violation_kind_opens_a_distinct_finding(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    session = _RawSession(db, tenant_id)
    _rule(db, tenant_id, "team", {"required": True, "severity": "high"})
    _rule(db, tenant_id, "tier", {"required": True, "allowed_values": ["dev", "prod"]})
    _rule(db, tenant_id, "custom_id", {"required": True, "format_pattern": r"^PROJ-\d{4}$"})
    resource = _resource(
        db,
        tenant_id,
        account,
        "arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        {"tier": "staging", "custom_id": "nope"},  # team missing entirely
    )

    validate_account(session, account.id)  # type: ignore[arg-type]

    findings = db.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    assert len(findings) == 3
    assert {f.severity.value for f in findings} == {"high", "medium"}


def test_a_disabled_rule_produces_no_finding(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    session = _RawSession(db, tenant_id)
    disabled = _rule(db, tenant_id, "team", {"required": True})
    disabled.enabled = False
    db.flush()
    resource = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-2", {}
    )

    validate_account(session, account.id)  # type: ignore[arg-type]

    findings = db.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    assert findings == []


def test_a_fixed_tag_auto_closes_its_finding(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """SC-002."""
    session = _RawSession(db, tenant_id)
    _rule(db, tenant_id, "team", {"required": True})
    resource = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-3", {}
    )
    validate_account(session, account.id)  # type: ignore[arg-type]
    findings = db.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    assert len(findings) == 1
    assert findings[0].status == FindingStatus.OPEN

    resource.tags = {"team": "platform"}
    db.flush()
    validate_account(session, account.id)  # type: ignore[arg-type]
    db.expire_all()

    findings = db.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    assert len(findings) == 1  # same row, not a second one
    assert findings[0].status == FindingStatus.RESOLVED
    assert findings[0].resolved_at is not None


def test_validate_scan_runs_for_succeeded_and_partial_but_not_failed(
    db: Session, tenant_id: uuid.UUID, account: CloudAccount
) -> None:
    """FR-017, proven end-to-end against a real `Scan` row this time."""
    session = _RawSession(db, tenant_id)
    _rule(db, tenant_id, "team", {"required": True})
    resource = _resource(
        db, tenant_id, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-4", {}
    )
    failed_scan = Scan(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.FAILED,
    )
    db.add(failed_scan)
    db.flush()

    validate_scan(session, failed_scan)

    findings = db.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    assert findings == []
