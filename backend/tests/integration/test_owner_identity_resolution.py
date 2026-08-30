"""Owner-identity resolution precedence chain (P2, FR-027, FR-028, S23a).

Integration, not unit, despite the task list's original naming -- same
precedent as every other governance test this spec moved: the chain reads
`Tenant.owner_identity_pattern` and the `owner_identity_override` table, both
real Postgres state.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.governance.identity_resolution import resolve_owner_email
from app.models.core import OwnerIdentityOverride, Tenant
from app.models.core import Rule as RuleRow

pytestmark = pytest.mark.integration


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


def test_a_valid_owner_tag_wins_outright(db: Session, tenant_id: uuid.UUID) -> None:
    session = _RawSession(db, tenant_id)
    email = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {"owner": "alice@example.com"},
        "arn:aws:iam::123456789012:user/bob",
    )
    assert email == "alice@example.com"


def test_an_invalid_owner_tag_falls_through_to_the_pattern(
    db: Session, tenant_id: uuid.UUID
) -> None:
    session = _RawSession(db, tenant_id)
    db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(owner_identity_pattern="{principal_local_part}@example.com")
    )
    db.flush()

    email = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {"owner": "not-an-email"},
        "arn:aws:iam::123456789012:user/alice",
    )
    assert email == "alice@example.com"


def test_no_pattern_falls_through_to_the_override_table(db: Session, tenant_id: uuid.UUID) -> None:
    session = _RawSession(db, tenant_id)
    override = OwnerIdentityOverride(
        tenant_id=tenant_id,
        principal_id="arn:aws:iam::123456789012:user/alice",
        owner_email="override@example.com",
    )
    db.add(override)
    db.flush()

    email = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {},
        "arn:aws:iam::123456789012:user/alice",
    )
    assert email == "override@example.com"


def test_nothing_resolves_returns_none(db: Session, tenant_id: uuid.UUID) -> None:
    session = _RawSession(db, tenant_id)
    email = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {},
        "arn:aws:iam::123456789012:user/nobody",
    )
    assert email is None


def test_a_changed_pattern_takes_effect_immediately(db: Session, tenant_id: uuid.UUID) -> None:
    """FR-028: admin-editable configuration, no redeploy needed."""
    session = _RawSession(db, tenant_id)
    db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(owner_identity_pattern="{principal_local_part}@old.example.com")
    )
    db.flush()
    first = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {},
        "arn:aws:iam::123456789012:user/alice",
    )
    assert first == "alice@old.example.com"

    db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(owner_identity_pattern="{principal_local_part}@new.example.com")
    )
    db.flush()
    second = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {},
        "arn:aws:iam::123456789012:user/alice",
    )
    assert second == "alice@new.example.com"


def test_owner_tag_lookup_is_case_insensitive(db: Session, tenant_id: uuid.UUID) -> None:
    """Matches FR-002's established case-insensitive tag-key convention."""
    session = _RawSession(db, tenant_id)
    email = resolve_owner_email(
        session,  # type: ignore[arg-type]
        {"Owner": "alice@example.com"},
        "arn:aws:iam::123456789012:user/bob",
    )
    assert email == "alice@example.com"
