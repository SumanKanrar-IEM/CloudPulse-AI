"""SDA matching and reclassification -- the registry's primary behavior, not just
its edge cases (FR-008, FR-009, FR-010, SC-006, SC-007).

Added by `/speckit-analyze` finding E1 (2026-08-25): T009/T010 only ever covered
the overlap-refusal and removal edge cases, never the happy path itself. Calls
`app.governance.sda_matching.reclassify_account_resources` directly -- the same
function Phase 7's compliance-validation worker calls once per finalized scan
(research.md R-303) -- rather than through a real scan, the same "prove the logic
directly, wire it to a real trigger later" split Phase 5's validation tests use.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.governance.sda_matching import reclassify_account_resources
from app.models.core import CloudAccount, Resource, Sda
from app.models.enums import AccountStatus, ConnectionMode

pytestmark = pytest.mark.integration


class _RawSession:
    """Minimal TenantSession-compatible wrapper, matching
    test_scan_diffing.py's own established pattern for calling governance/scan
    functions directly against a real session."""

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
        session.close()


@pytest.fixture
def account(db: tuple[_RawSession, uuid.UUID]) -> CloudAccount:
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


def _resource(
    session: _RawSession, account: CloudAccount, arn: str, tags: dict[str, str]
) -> Resource:
    resource = Resource(
        cloud_account_id=account.id,
        arn=arn,
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags=tags,
    )
    session.add(resource)
    session.flush()
    return resource


def test_a_resource_matching_an_sda_attaches_to_it(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    """FR-008, Acceptance Scenario US2.1."""
    session, _ = db
    sda = Sda(name="platform", owner_email="a@example.com", tag_values={"team": "platform"})
    session.add(sda)
    session.flush()
    resource = _resource(
        session, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-1", {"team": "platform"}
    )

    changed = reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(resource)

    assert changed == 1
    assert resource.sda_id == sda.id


def test_a_resource_matching_no_sda_stays_in_no_sda_bucket(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    """FR-009, SC-006."""
    session, _ = db
    session.add(Sda(name="platform", owner_email="a@example.com", tag_values={"team": "platform"}))
    session.flush()
    resource = _resource(
        session, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-2", {"team": "data"}
    )

    reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(resource)

    assert resource.sda_id is None


def test_registering_an_sda_reclassifies_previously_unmatched_resources(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    """FR-010, Acceptance Scenario US2.3, SC-007: registering a new SDA
    reclassifies matching resources by the next scan -- no separate trigger."""
    session, _ = db
    resource = _resource(
        session, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-3", {"team": "data"}
    )
    reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(resource)
    assert resource.sda_id is None  # no SDA registered yet

    sda = Sda(name="data", owner_email="b@example.com", tag_values={"team": "data"})
    session.add(sda)
    session.flush()
    changed = reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(resource)

    assert changed == 1
    assert resource.sda_id == sda.id


def test_editing_an_sdas_mapping_reclassifies_resources(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    """FR-010: an edited mapping reclassifies resources too, not just a new
    registration."""
    session, _ = db
    sda = Sda(name="platform", owner_email="a@example.com", tag_values={"team": "platform"})
    session.add(sda)
    session.flush()
    resource = _resource(
        session, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-4", {"team": "data"}
    )
    reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(resource)
    assert resource.sda_id is None

    sda.tag_values = {"team": "data"}
    session.flush()
    reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(resource)

    assert resource.sda_id == sda.id


def test_reclassification_only_touches_top_level_resources(
    db: tuple[_RawSession, uuid.UUID], account: CloudAccount
) -> None:
    """FR-013's "top-level resource" definition applies here too: an attached
    (non-top-level) resource is never independently classified."""
    session, _ = db
    session.add(Sda(name="platform", owner_email="a@example.com", tag_values={"team": "platform"}))
    session.flush()
    parent = _resource(
        session, account, "arn:aws:ec2:us-east-1:123456789012:instance/i-5", {"team": "platform"}
    )
    child = Resource(
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:volume/vol-5",
        resource_type="AWS::EC2::Volume",
        service="ec2",
        region="us-east-1",
        tags={"team": "platform"},
        parent_resource_id=parent.id,
    )
    session.add(child)
    session.flush()

    reclassify_account_resources(session, account.id)  # type: ignore[arg-type]
    session.raw.refresh(parent)
    session.raw.refresh(child)

    assert parent.sda_id is not None
    assert child.sda_id is None  # never evaluated -- not top-level
