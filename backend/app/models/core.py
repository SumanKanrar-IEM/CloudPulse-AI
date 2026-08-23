"""The governance record (FR-024).

This spec owns the *shape* of these tables. The behaviour that fills them belongs to
specs 002-006, which extend them by additive migration. Most arrive empty and stay
empty until their owning spec lands.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import enums
from app.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


def _pg_enum(py_enum: type[StrEnum], name: str) -> Enum:
    """Native PostgreSQL enum, storing values rather than member names."""
    return Enum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


# ---------------------------------------------------------------------------
# 1. tenant -- owned by this spec
# ---------------------------------------------------------------------------
class Tenant(UUIDPrimaryKey, Timestamps, Base):
    """The organisational boundary that owns every other record.

    Exactly one row is seeded in the MVP. Every other table is tenant-scoped from day
    one (FR-030) so multi-tenancy never needs a schema rewrite.
    """

    __tablename__ = "tenant"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[enums.TenantStatus] = mapped_column(
        _pg_enum(enums.TenantStatus, "tenant_status"),
        nullable=False,
        server_default=enums.TenantStatus.ACTIVE.value,
    )

    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),)


# ---------------------------------------------------------------------------
# 2. app_user -- owned by this spec
# ---------------------------------------------------------------------------
class AppUser(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A projection of a Cognito identity.

    Exists only to attribute audit events and display a human-readable name.

    **There is deliberately no `role` column.** FR-031a makes the directory the sole
    authority for a person's role; it is derived from the group claim on every request
    (FR-038). A column here would be a second, drifting source of truth and a
    privilege-escalation surface. A pull request adding one is a constitution
    violation, not a feature -- see `test_tenant_scoping.py::test_app_user_has_no_role_column`.

    Named `app_user` because `user` is reserved in PostgreSQL.
    """

    __tablename__ = "app_user"

    cognito_sub: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# 3. audit_event -- owned by this spec, written by every spec
# ---------------------------------------------------------------------------
class AuditEvent(UUIDPrimaryKey, TenantScoped, Base):
    """Append-only record of every privileged or state-changing action (FR-040).

    Immutability is enforced in three layers, because any one of them is bypassable:

    1. the application role holds INSERT/SELECT and **not** UPDATE/DELETE (migration
       ``0003``);
    2. a ``BEFORE UPDATE OR DELETE`` trigger raises (migration ``0003``);
    3. this class exposes no update or delete path, and the repository layer offers
       only ``write_audit_event``.

    No ``updated_at``: a row that can never change has no meaningful update time.
    No expiry, no partition dropping, no purge job -- FR-029a makes the *absence* of a
    retention mechanism the correct implementation.
    """

    __tablename__ = "audit_event"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT")
    )
    # Kept alongside the FK so a system or pipeline actor -- which has no app_user row
    # -- is still attributable, and so the label survives even if the user row changes.
    actor_label: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(2048))
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_audit_event_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_audit_event_correlation", "correlation_id"),
    )


# ---------------------------------------------------------------------------
# 4. deployment -- owned by this spec. The ONE table that is not tenant-scoped.
# ---------------------------------------------------------------------------
class Deployment(UUIDPrimaryKey, Base):
    """A deployment of the platform itself (FR-023).

    Deliberately **not** tenant-scoped: it records an act on the platform, not on a
    tenant's data. Called out explicitly so it does not read as an FR-030 oversight.
    """

    __tablename__ = "deployment"

    environment: Mapped[enums.DeploymentEnvironment] = mapped_column(
        _pg_enum(enums.DeploymentEnvironment, "deployment_environment"), nullable=False
    )
    git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Spec Assumptions: with a single maintainer every prod approval is a
    # self-approval. Permitted, but recorded as such so the merge history stays honest
    # about what kind of gate it was.
    self_approved: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    migration_revision: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[enums.DeploymentStatus] = mapped_column(
        _pg_enum(enums.DeploymentStatus, "deployment_status"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # FR-017/FR-018: a prod deployment row cannot exist without a recorded
        # approver. Enforced in the database, not in application code, so a future
        # code path cannot route around it.
        CheckConstraint(
            "environment <> 'prod' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="prod_requires_approver",
        ),
        Index("ix_deployment_env_started", "environment", "started_at"),
    )


# ---------------------------------------------------------------------------
# 5-10. Downstream tables -- schema here, behaviour elsewhere
# ---------------------------------------------------------------------------
class CloudAccount(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A registered AWS account (spec 002).

    **No credential columns.** ``external_id_ref`` is a Secrets Manager reference, never
    a value; ``role_arn`` is an identifier. Principle III (FR-007).
    """

    __tablename__ = "cloud_account"

    aws_account_id: Mapped[str] = mapped_column(String(12), nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    connection_mode: Mapped[enums.ConnectionMode] = mapped_column(
        _pg_enum(enums.ConnectionMode, "connection_mode"), nullable=False
    )
    role_arn: Mapped[str | None] = mapped_column(String(2048))
    external_id_ref: Mapped[str | None] = mapped_column(String(2048))
    scan_regions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    status: Mapped[enums.AccountStatus] = mapped_column(
        _pg_enum(enums.AccountStatus, "account_status"),
        nullable=False,
        server_default=enums.AccountStatus.PENDING.value,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "aws_account_id", name="uq_cloud_account_tenant_account"),
        CheckConstraint("aws_account_id ~ '^[0-9]{12}$'", name="aws_account_id_is_12_digits"),
        # An assume_role connection is meaningless without a role to assume.
        CheckConstraint(
            "connection_mode <> 'assume_role' OR role_arn IS NOT NULL",
            name="assume_role_requires_arn",
        ),
    )


class Resource(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A normalised, provider-agnostic discovered resource (spec 002)."""

    __tablename__ = "resource"

    cloud_account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cloud_account.id", ondelete="CASCADE"), nullable=False
    )
    arn: Mapped[str] = mapped_column(String(2048), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(200), nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(50), nullable=False)
    tags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    parent_resource_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resource.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # migration 0009 (spec 002). Free-text, service-reported (e.g. `running`,
    # `available`) rather than a cross-service enum -- AWS resource states genuinely
    # don't share a common vocabulary (data-model.md).
    state: Mapped[str | None] = mapped_column(String(100))
    # migration 0009. NULL = currently present; non-null = the timestamp of the scan
    # that first failed to find it. A soft marker, never a row deletion (FR-030).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # migration 0009. Service-specific enrichment payload (FR-019), deliberately
    # schemaless at the SQL level -- coverage.py gives it structure at the app layer.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "arn", name="uq_resource_tenant_arn"),
        # GIN over tags: spec 003 filters on tag keys across the whole inventory.
        Index("ix_resource_tags", "tags", postgresql_using="gin"),
        Index("ix_resource_account_type", "cloud_account_id", "resource_type"),
    )


class Rule(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A governance rule expressed as data, not code (spec 003, Principle V).

    Versioned so a finding always traces to the rule version that produced it.
    """

    __tablename__ = "rule"

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", "version", name="uq_rule_tenant_key_version"),
    )


class Finding(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A resource failing a rule (spec 003).

    Lifecycle semantics are spec 003's to define (FR-055); this is the schema's
    accommodation of them.
    """

    __tablename__ = "finding"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resource.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rule.id", ondelete="RESTRICT"), nullable=False
    )
    # Pinned, not derived from rule_id: the rule may be superseded, and the finding
    # must still say which version produced it.
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[enums.FindingSeverity] = mapped_column(
        _pg_enum(enums.FindingSeverity, "finding_severity"), nullable=False
    )
    status: Mapped[enums.FindingStatus] = mapped_column(
        _pg_enum(enums.FindingStatus, "finding_status"),
        nullable=False,
        server_default=enums.FindingStatus.OPEN.value,
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # One OPEN finding per (resource, rule). Re-running a scan must not create a
        # duplicate; a resolved finding may coexist with a later re-opened one.
        Index(
            "uq_finding_open_per_resource_rule",
            "tenant_id",
            "resource_id",
            "rule_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_finding_tenant_status_severity", "tenant_id", "status", "severity"),
        CheckConstraint(
            "status <> 'resolved' OR resolved_at IS NOT NULL", name="resolved_requires_timestamp"
        ),
    )


class Sda(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Service Delivery Area -- a named delivery unit (spec 003).

    Grouping and roll-up semantics are spec 003's to define (FR-055).
    """

    __tablename__ = "sda"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(320), nullable=False)
    team: Mapped[str | None] = mapped_column(String(200))
    tag_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_sda_tenant_name"),)


class ResourceOwner(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """The human attributed as accountable for a resource (spec 003)."""

    __tablename__ = "resource_owner"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resource.id", ondelete="CASCADE"), nullable=False
    )
    owner_email: Mapped[str | None] = mapped_column(String(320))
    # Why we believe it: the audit events, tags or fallbacks the attribution rests on.
    # An attribution without evidence is a guess presented as a fact.
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    confidence: Mapped[enums.OwnerConfidence] = mapped_column(
        _pg_enum(enums.OwnerConfidence, "owner_confidence"), nullable=False
    )
    attributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "resource_id", name="uq_resource_owner_tenant_resource"),
    )


class Scan(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """One execution of discovery against an account (spec 002)."""

    __tablename__ = "scan"

    cloud_account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cloud_account.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[enums.ScanTrigger] = mapped_column(
        _pg_enum(enums.ScanTrigger, "scan_trigger"), nullable=False
    )
    status: Mapped[enums.ScanStatus] = mapped_column(
        _pg_enum(enums.ScanStatus, "scan_status"), nullable=False
    )
    resource_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    snapshot_s3_key: Mapped[str | None] = mapped_column(String(2048))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_scan_account_started", "cloud_account_id", "started_at"),)


__all__ = [
    "Tenant",
    "AppUser",
    "AuditEvent",
    "Deployment",
    "CloudAccount",
    "Resource",
    "Rule",
    "Finding",
    "Sda",
    "ResourceOwner",
    "Scan",
]
