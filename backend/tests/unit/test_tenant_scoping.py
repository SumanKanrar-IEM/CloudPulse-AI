"""Tenant isolation is structural, not conventional (FR-030).

These tests run against the SQLAlchemy metadata rather than a live database, so they
catch a missing ``tenant_id`` at the moment a model is added rather than the first time
someone queries it in production.

The interesting assertions are the negative ones: that a tenant-scoped query without a
filter *raises*, and that ``app_user`` has no ``role`` column. Both guard against
mistakes that look completely normal in review.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.db import TenantScopeError, TenantSession
from app.models import Base
from app.models.base import TenantScoped
from app.models.core import (
    AppUser,
    AuditEvent,
    CloudAccount,
    Deployment,
    Finding,
    Resource,
    ResourceOwner,
    Rule,
    Scan,
    Sda,
    Tenant,
)

# `tenant` defines the boundary; `deployment` records an act on the platform itself,
# not on a tenant's data. Every other table must be scoped.
DELIBERATELY_UNSCOPED = {"tenant", "deployment"}

ALL_MODELS = [
    AppUser,
    AuditEvent,
    CloudAccount,
    Deployment,
    Finding,
    Resource,
    ResourceOwner,
    Rule,
    Scan,
    Sda,
    Tenant,
]


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__tablename__)
def test_every_table_is_tenant_scoped_or_deliberately_not(model: type) -> None:
    """FR-030, with an explicit allowlist.

    A new table that forgets ``tenant_id`` fails here. Adding it to
    DELIBERATELY_UNSCOPED is a visible, reviewable act rather than an omission.
    """
    table = model.__table__
    if table.name in DELIBERATELY_UNSCOPED:
        assert (
            "tenant_id" not in table.c
        ), f"{table.name} is listed as deliberately unscoped but has a tenant_id"
        return

    assert "tenant_id" in table.c, f"{table.name} is missing tenant_id (FR-030)"
    assert not table.c.tenant_id.nullable, f"{table.name}.tenant_id must be NOT NULL"
    assert issubclass(model, TenantScoped), f"{model.__name__} must inherit TenantScoped"


@pytest.mark.parametrize(
    "model",
    [m for m in ALL_MODELS if m.__tablename__ not in DELIBERATELY_UNSCOPED],
    ids=lambda m: m.__tablename__,
)
def test_tenant_id_is_indexed(model: type) -> None:
    """An unindexed tenant filter turns every query into a full scan."""
    table = model.__table__
    indexed = any("tenant_id" in [c.name for c in idx.columns] for idx in table.indexes)
    assert indexed or table.c.tenant_id.index, f"{table.name}.tenant_id is not indexed"


def test_app_user_has_no_role_column() -> None:
    """FR-031a: the directory is the SOLE authority for a person's role.

    A role column here would be a second, drifting source of truth and a
    privilege-escalation surface. This test exists so that adding one fails loudly
    rather than looking like a reasonable feature in review.
    """
    columns = set(AppUser.__table__.c.keys())
    for forbidden in ("role", "roles", "permissions", "is_admin", "group"):
        assert forbidden not in columns, (
            f"app_user.{forbidden} would make the platform a second source of truth "
            f"for authorisation, violating FR-031a"
        )


def test_cloud_account_holds_no_credential_columns() -> None:
    """FR-007 / Principle III: references only, never values."""
    columns = set(CloudAccount.__table__.c.keys())
    for forbidden in ("access_key", "secret_key", "secret_access_key", "password", "external_id"):
        assert forbidden not in columns, (
            f"cloud_account.{forbidden} would store a credential. Use a Secrets "
            f"Manager reference (external_id_ref) instead."
        )
    assert "external_id_ref" in columns


def test_scoped_query_applies_the_tenant_filter() -> None:
    """Assert on the clause, not the rendered string.

    SQLAlchemy compiles a UUID without hyphens, so matching ``str(tenant_id)`` against
    the SQL text gives a false negative. Inspecting the WHERE clause tests the
    behaviour rather than a rendering detail.
    """
    tenant_id = uuid.uuid4()
    session = TenantSession(session=None, tenant_id=tenant_id)  # type: ignore[arg-type]
    stmt = session.scoped(select(Resource), Resource)

    where = stmt.whereclause
    assert where is not None, "scoped() produced no WHERE clause (FR-030)"

    params = (
        [p.value for p in where.right.__dict__.get("_bindparams", {}).values()]
        if hasattr(where.right, "_bindparams")
        else [getattr(where.right, "value", None)]
    )
    assert tenant_id in params, f"tenant filter does not bind the tenant id: {params}"
    assert "tenant_id" in str(where)


def test_scoping_an_unscoped_model_raises() -> None:
    """Fail closed. Silently returning every row would look like success."""
    session = TenantSession(session=None, tenant_id=uuid.uuid4())  # type: ignore[arg-type]
    with pytest.raises(TenantScopeError, match="not tenant-scoped"):
        session.scoped(select(Deployment), Deployment)


def test_add_stamps_the_tenant() -> None:
    """A caller cannot forget to set tenant_id -- the session sets it."""
    tenant_id = uuid.uuid4()
    recorded: list[object] = []

    class _FakeSession:
        def add(self, obj: object) -> None:
            recorded.append(obj)

    session = TenantSession(session=_FakeSession(), tenant_id=tenant_id)  # type: ignore[arg-type]
    resource = Resource(
        arn="arn:aws:s3:::x", resource_type="AWS::S3::Bucket", service="s3", region="us-east-1"
    )
    session.add(resource)
    assert resource.tenant_id == tenant_id
    assert recorded == [resource]


def test_add_refuses_a_row_belonging_to_another_tenant() -> None:
    """Cross-tenant writes fail loudly rather than being silently re-stamped."""
    session = TenantSession(session=object(), tenant_id=uuid.uuid4())  # type: ignore[arg-type]
    foreign = Resource(
        tenant_id=uuid.uuid4(),
        arn="arn:aws:s3:::y",
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-east-1",
    )
    with pytest.raises(TenantScopeError, match="refusing to write"):
        session.add(foreign)


def test_audit_event_has_no_updated_at() -> None:
    """A row that can never change has no meaningful update time (FR-029)."""
    assert "updated_at" not in AuditEvent.__table__.c.keys()


def test_deployment_requires_an_approver_for_prod() -> None:
    """FR-017/FR-018 enforced in the database, not in application code."""
    checks = [c.name for c in Deployment.__table__.constraints if hasattr(c, "sqltext")]
    assert any(
        "approver" in (name or "") for name in checks
    ), f"deployment is missing the prod-approval CHECK constraint; found {checks}"


def test_finding_pins_the_rule_version() -> None:
    """A finding must trace to the rule version that produced it, not the current one."""
    assert "rule_version" in Finding.__table__.c.keys()
    assert not Finding.__table__.c.rule_version.nullable


def test_all_ten_governance_entities_exist() -> None:
    """FR-024: the full shape, so specs 002-006 build against a settled schema."""
    expected = {
        "tenant",
        "app_user",
        "audit_event",
        "deployment",
        "cloud_account",
        "resource",
        "rule",
        "finding",
        "sda",
        "resource_owner",
        "scan",
    }
    assert expected <= set(Base.metadata.tables), f"missing: {expected - set(Base.metadata.tables)}"
