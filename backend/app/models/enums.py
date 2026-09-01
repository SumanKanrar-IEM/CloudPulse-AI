"""PostgreSQL native enum types.

Declared in one place so migration `0001_extensions_and_enums` and the models cannot
drift. Extending an enum is an additive migration; removing a member is breaking.
"""

from __future__ import annotations

from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class DeploymentEnvironment(StrEnum):
    """FR-002 permits exactly two environments."""

    DEV = "dev"
    PROD = "prod"


class DeploymentStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConnectionMode(StrEnum):
    """FR-031-adjacent: how the platform reaches a scanned account.

    Both modes are roles-only. There is deliberately no mode that accepts an access
    key -- Principle III forbids storing one, so it is absent from the vocabulary
    rather than merely discouraged.
    """

    LOCAL = "local"
    ASSUME_ROLE = "assume_role"


class AccountStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    DISABLED = "disabled"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    """Spec 003 owns the lifecycle semantics (FR-055).

    These members are the schema's accommodation of them, not the authoritative
    definition. Spec 003 may extend this enum by additive migration without
    renegotiating the table.
    """

    OPEN = "open"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class ScanTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class ScanStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class OwnerConfidence(StrEnum):
    """How much weight the ownership attribution carries (spec 003)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SuggestionSource(StrEnum):
    """A remediation suggestion's provenance (spec 004, FR-018/FR-020a).

    `ADMIN_SEEDED` is deliberately the only value `PUT
    /findings/{id}/suggestion` (admin-only) can ever write -- the endpoint has
    no path to writing `AI_GENERATED`, so a seeded suggestion can never be
    mistaken for a genuine platform recommendation at the write layer, not
    merely trusted to stay accurate at display time. `AI_GENERATED` is
    reserved for the AI-insights capability (a later spec) to write.
    """

    AI_GENERATED = "ai_generated"
    ADMIN_SEEDED = "admin_seeded"


# name -> members, consumed by migration 0001 so the two cannot drift.
ENUM_TYPES: dict[str, type[StrEnum]] = {
    "tenant_status": TenantStatus,
    "deployment_environment": DeploymentEnvironment,
    "deployment_status": DeploymentStatus,
    "connection_mode": ConnectionMode,
    "account_status": AccountStatus,
    "finding_severity": FindingSeverity,
    "finding_status": FindingStatus,
    "scan_trigger": ScanTrigger,
    "scan_status": ScanStatus,
    "owner_confidence": OwnerConfidence,
}
