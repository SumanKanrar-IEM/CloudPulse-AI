"""The governance record (FR-024).

This spec owns the *shape* of these tables. The behaviour that fills them belongs to
specs 002-006, which extend them by additive migration. Most arrive empty and stay
empty until their owning spec lands.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
    # migration 0010 (spec 003). Admin-configurable template applied to an audit-trail
    # identity when an owner tag isn't a usable email and no override row exists for
    # it (FR-028). NULL = the pattern step is skipped in the resolution chain.
    owner_identity_pattern: Mapped[str | None] = mapped_column(String(500))

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
    # migration 0010 (spec 003). NULL = "No SDA" bucket (FR-009). Set at scan time by
    # SDA matching (FR-008); ON DELETE SET NULL is FR-010b's actual removal mechanism,
    # not an incidental default (data-model.md).
    sda_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sda.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "arn", name="uq_resource_tenant_arn"),
        # GIN over tags: spec 003 filters on tag keys across the whole inventory.
        Index("ix_resource_tags", "tags", postgresql_using="gin"),
        Index("ix_resource_account_type", "cloud_account_id", "resource_type"),
        Index("ix_resource_sda_id", "sda_id"),
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

    # migration 0012 (spec 005). Nullable as of this migration -- a `budget_overrun`
    # finding (kind, below) has neither a resource nor a rule; it attaches to an
    # `Sda` instead. `ck_finding_kind_shape` is what actually enforces which three
    # of these six columns are populated together, not the column definitions alone
    # (data-model.md, research.md R-508).
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resource.id", ondelete="CASCADE")
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rule.id", ondelete="RESTRICT")
    )
    # Pinned, not derived from rule_id: the rule may be superseded, and the finding
    # must still say which version produced it.
    rule_version: Mapped[int | None] = mapped_column(Integer)
    # migration 0012 (spec 005). NOT a resource_id alternative encoding -- a
    # budget_overrun finding really does attach to a project/SDA, not a resource
    # standing in for one (research.md R-508's own rejected alternative).
    sda_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sda.id", ondelete="CASCADE")
    )
    kind: Mapped[enums.FindingKind] = mapped_column(
        _pg_enum(enums.FindingKind, "finding_kind"),
        nullable=False,
        server_default=enums.FindingKind.TAG_VIOLATION.value,
    )
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
    # migration 0011 (spec 004). Orthogonal metadata, parallel in shape to
    # resolved_at -- never changes `status` or affects any compliance score
    # (FR-017, research.md R-404). A human triage signal, not a resolution, and
    # never a stand-in for the reserved `suppressed` status.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # migration 0012 (spec 005, FR-008/FR-009). Set the first time a still-open
    # finding's day-4 reminder is sent; cleared (NULL) the moment the finding
    # leaves `open` by any means. Orthogonal to `status`, the same discipline
    # `acknowledged_at` already established above -- never a stand-in for it.
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
        # migration 0012 (spec 005). The per-project mirror of the index above --
        # one open budget_overrun finding per SDA at a time. A tag_violation row's
        # sda_id is always NULL, which Postgres never treats as matching any other
        # row's NULL (data-model.md), so the two indexes never interfere.
        Index(
            "uq_finding_open_overrun_per_sda",
            "tenant_id",
            "sda_id",
            unique=True,
            postgresql_where=text("status = 'open' AND kind = 'budget_overrun'"),
        ),
        Index("ix_finding_tenant_status_severity", "tenant_id", "status", "severity"),
        CheckConstraint(
            "status <> 'resolved' OR resolved_at IS NOT NULL", name="resolved_requires_timestamp"
        ),
        # migration 0012 (spec 005, research.md R-508). Exactly one shape per kind:
        # tag_violation carries resource/rule/rule_version and no sda_id;
        # budget_overrun carries sda_id and none of the other three.
        CheckConstraint(
            "(kind = 'tag_violation' AND resource_id IS NOT NULL AND rule_id IS NOT NULL "
            "AND rule_version IS NOT NULL AND sda_id IS NULL) "
            "OR "
            "(kind = 'budget_overrun' AND sda_id IS NOT NULL AND resource_id IS NULL "
            "AND rule_id IS NULL AND rule_version IS NULL)",
            # Naming convention prepends "ck_finding_" (base.py's NAMING_CONVENTION) --
            # passing "kind_shape" here, not "ck_finding_kind_shape", is what actually
            # produces "ck_finding_kind_shape" as the constraint's real name, matching
            # data-model.md/tasks.md's documented name. resolved_requires_timestamp
            # above follows this exact same rule.
            name="kind_shape",
        ),
    )


class FindingRemediationSuggestion(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A finding's remediation suggestion and blast-radius note (spec 004).

    Unique on `finding_id`: one suggestion per finding, matching FR-018's
    singular "a platform-generated remediation suggestion" -- an upsert
    target, not an append-only log (data-model.md).
    """

    __tablename__ = "finding_remediation_suggestion"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("finding.id", ondelete="CASCADE"), nullable=False
    )
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    blast_radius_note: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[enums.SuggestionSource] = mapped_column(
        _pg_enum(enums.SuggestionSource, "suggestion_source"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "finding_id", name="uq_finding_remediation_suggestion_tenant_finding"
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


class SpendRecord(UUIDPrimaryKey, TenantScoped, Base):
    """One account/service/day's ingested spend amount (spec 005, FR-001/FR-002a).

    Deliberately no `Timestamps` mixin: `ingested_at` (below) already serves the
    "last write time" role `updated_at` would, and there is no meaningful
    `created_at` distinct from it for a row that's always either fresh or
    corrected-in-place (data-model.md).
    """

    __tablename__ = "spend_record"

    cloud_account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cloud_account.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = the "No SDA" bucket -- mirrors resource.sda_id's own nullability
    # exactly (research.md R-505).
    sda_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sda.id", ondelete="SET NULL")
    )
    # migration 0013. Nullable, not the whole-day-gap row's own placeholder value
    # -- a gap has no per-service breakdown at all, so there is nothing honest to
    # put here (same "never a guessed value" discipline amount_usd already
    # follows, applied to this column too).
    service: Mapped[str | None] = mapped_column(String(100))
    spend_date: Mapped[date] = mapped_column(Date, nullable=False)
    # NULL exactly when is_gap is true (FR-002a) -- never a guessed or zeroed
    # value for a day ingestion never actually produced.
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    is_gap: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        # migration 0013 (found while implementing T007, T003a): three partial
        # indexes, not one plain UniqueConstraint -- a plain constraint including
        # a nullable column (sda_id) silently allows duplicate "No SDA" rows for
        # the same account/service/day, since Postgres never treats two NULLs as
        # equal for uniqueness purposes. A day's correction MUST hit the same
        # existing row via ON CONFLICT regardless of whether that day's spend
        # happens to be attributed to a real SDA or the "No SDA" bucket, so the
        # NULL case needs its own index that doesn't include the NULL-valued
        # column in its key at all.
        Index(
            "uq_spend_record_tenant_account_service_date_sda",
            "tenant_id",
            "cloud_account_id",
            "service",
            "spend_date",
            "sda_id",
            unique=True,
            postgresql_where=text("is_gap = false AND sda_id IS NOT NULL"),
        ),
        Index(
            "uq_spend_record_tenant_account_service_date_no_sda",
            "tenant_id",
            "cloud_account_id",
            "service",
            "spend_date",
            unique=True,
            postgresql_where=text("is_gap = false AND sda_id IS NULL"),
        ),
        Index(
            "uq_spend_record_gap_per_account_date",
            "tenant_id",
            "cloud_account_id",
            "spend_date",
            unique=True,
            postgresql_where=text("is_gap = true"),
        ),
        CheckConstraint(
            "is_gap = true OR (service IS NOT NULL AND amount_usd IS NOT NULL)",
            name="amount_and_service_required_unless_gap",
        ),
    )


class Budget(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A spend ceiling attached to one project/SDA (spec 005, FR-015).

    Created synchronously inside `POST /sdas`'s own transaction (research.md
    R-502) -- there is no separate "create a budget" endpoint.
    """

    __tablename__ = "budget"

    sda_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sda.id", ondelete="CASCADE"), nullable=False
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    actual_80_crossed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_100_crossed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    forecast_80_crossed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    forecast_100_crossed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("tenant_id", "sda_id", name="uq_budget_tenant_sda"),)


class Notification(UUIDPrimaryKey, TenantScoped, Base):
    """One outbound-email attempt for one finding at one cadence point (spec
    005, FR-004-FR-013).

    No `Timestamps` mixin -- `attempted_at` is this row's one meaningful
    timestamp; there is no later update, a row is written once per attempt.
    """

    __tablename__ = "notification"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("finding.id", ondelete="CASCADE"), nullable=False
    )
    cadence_point: Mapped[enums.NotificationCadencePoint] = mapped_column(
        _pg_enum(enums.NotificationCadencePoint, "notification_cadence_point"), nullable=False
    )
    outcome: Mapped[enums.NotificationOutcome] = mapped_column(
        _pg_enum(enums.NotificationOutcome, "notification_outcome"), nullable=False
    )
    # Populated only when outcome = 'sent'.
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        # At most one attempt per finding per cadence point, ever -- what makes a
        # reopened finding's fresh Finding.id naturally start its own independent
        # cadence (FR-011), with no separate "cycle number" column needed.
        UniqueConstraint(
            "tenant_id",
            "finding_id",
            "cadence_point",
            name="uq_notification_tenant_finding_cadence",
        ),
    )


class IamHygieneFlag(UUIDPrimaryKey, TenantScoped, Base):
    """A flag-only unused-principal recommendation (spec 005, FR-019/FR-020).

    Deliberately not a `Finding` -- FR-019 fixes this as flag-only, never
    entering the acknowledge/notify/escalate pipeline a `Finding` carries.
    """

    __tablename__ = "iam_hygiene_flag"

    cloud_account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cloud_account.id", ondelete="CASCADE"), nullable=False
    )
    principal_type: Mapped[enums.IamPrincipalType] = mapped_column(
        _pg_enum(enums.IamPrincipalType, "iam_principal_type"), nullable=False
    )
    # A role/user ARN, or an access key ID for an `access_key` flag.
    principal_identifier: Mapped[str] = mapped_column(String(2048), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # NULL = still active. Set when a later weekly run no longer finds this
    # principal unused; re-flagged with a fresh flagged_at if it later becomes
    # unused again, rather than reusing a stale row.
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_iam_hygiene_flag_active_principal",
            "tenant_id",
            "cloud_account_id",
            "principal_identifier",
            unique=True,
            postgresql_where=text("cleared_at IS NULL"),
        ),
    )


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


class OwnerIdentityOverride(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A manual owner-identity resolution an admin maintains for one audit-trail
    identity the configured pattern can't resolve (spec 003, S23a, FR-027)."""

    __tablename__ = "owner_identity_override"

    # The raw audit-trail principal string (an IAM ARN or equivalent) -- not a
    # reference to any platform table; it inherently has no corresponding row
    # anywhere in this schema (research.md R-304).
    principal_id: Mapped[str] = mapped_column(String(2048), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(320), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "principal_id", name="uq_owner_identity_override_tenant_principal"
        ),
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
    "FindingRemediationSuggestion",
    "Sda",
    "SpendRecord",
    "Budget",
    "Notification",
    "IamHygieneFlag",
    "ResourceOwner",
    "OwnerIdentityOverride",
    "Scan",
]
