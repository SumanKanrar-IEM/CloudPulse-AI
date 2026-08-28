"""Rule evaluation, parent/child resolution, and finding lifecycle
(FR-013-FR-017, research.md R-301).

`validate_scan` is the function Phase 7's compliance-validation worker calls once
per finalized scan (research.md R-303); it is invoked directly here and in
tests/integration/test_validation_engine.py,
tests/integration/test_finding_rule_version_repointing.py, and
tests/integration/test_parent_child_resolution.py to prove the evaluation logic
itself, independent of how it gets triggered -- the same split
`app.governance.sda_matching` already follows.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.db import TenantSession
from app.core.logging import logger
from app.models.core import Finding, Resource, Scan
from app.models.core import Rule as RuleRow
from app.models.enums import FindingStatus, ScanStatus

# --- Parent/child resolution (FR-013a) ----------------------------------------

# Enrichment detail keys spec 002's P1 enrichment already captures that identify an
# owning resource -- the same fields research.md's Assumptions section named.
_ATTACHMENT_DETAIL_KEYS: tuple[str, ...] = ("attached_instance_id", "associated_instance_id")


def resolve_parent_child_relationships(session: TenantSession, cloud_account_id: uuid.UUID) -> int:
    """FR-013a: a resource whose enrichment `detail` names an owning resource
    gets `parent_resource_id` set to that resource's row; everything else keeps
    it `NULL`. Returns the number of resources whose `parent_resource_id`
    changed."""
    resources = (
        session.raw.execute(
            session.scoped(select(Resource), Resource).where(
                Resource.cloud_account_id == cloud_account_id,
                Resource.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    by_instance_id = {r.arn.rsplit("/", 1)[-1]: r for r in resources if "instance/" in r.arn}
    changed = 0
    for resource in resources:
        owner_instance_id = next(
            (
                resource.detail.get(key)
                for key in _ATTACHMENT_DETAIL_KEYS
                if resource.detail.get(key)
            ),
            None,
        )
        parent = by_instance_id.get(owner_instance_id) if owner_instance_id else None
        new_parent_id = parent.id if parent is not None else None
        if resource.parent_resource_id != new_parent_id:
            resource.parent_resource_id = new_parent_id
            changed += 1
    session.flush()
    return changed


# --- Pure per-rule evaluation (FR-002, FR-004, FR-014) -------------------------


def evaluate_rule_against_tags(
    tag_key: str, definition: dict[str, Any], tags: dict[str, str]
) -> str | None:
    """FR-002/FR-004/FR-014: which violation (if any) this rule finds, given a
    case-insensitive-keyed view of the resource's tags. Returns
    `"missing_tag"`, `"invalid_value"`, `"invalid_format"`, or `None`.

    An empty or whitespace-only tag value is treated as equivalent to a missing
    one (spec.md Assumptions/Edge Cases) -- it never satisfies a `required` rule
    on a technicality.
    """
    value = tags.get(tag_key.lower(), "").strip()
    if not value:
        return "missing_tag" if definition.get("required") else None

    allowed_values = definition.get("allowed_values")
    if allowed_values is not None and value not in allowed_values:
        return "invalid_value"

    format_pattern = definition.get("format_pattern")
    if format_pattern is not None and not re.match(format_pattern, value):
        return "invalid_format"

    return None


# --- Finding lifecycle (FR-014-FR-016, research.md R-301) ----------------------


def _find_open_finding_by_rule_key(
    session: TenantSession, resource_id: uuid.UUID, rule_key: str
) -> Finding | None:
    """The join-on-`key` lookup research.md R-301 requires -- NOT a lookup by
    `rule_id` directly, since a rule edit creates a new row under the same key.
    A finding opened under a superseded version is still found here, because the
    join follows the *key*, letting it be re-pointed rather than orphaned."""
    stmt = (
        session.scoped(select(Finding), Finding)
        .join(RuleRow, Finding.rule_id == RuleRow.id)
        .where(
            RuleRow.tenant_id == session.tenant_id,
            Finding.resource_id == resource_id,
            RuleRow.key == rule_key,
            Finding.status == FindingStatus.OPEN,
        )
    )
    return session.raw.execute(stmt).scalars().first()


def evaluate_resource(session: TenantSession, resource: Resource, rules: list[RuleRow]) -> None:
    """FR-013-FR-016: evaluate one top-level resource against every enabled
    rule, opening, re-pointing, or auto-closing findings as needed."""
    tags_lower = {k.lower(): v for k, v in resource.tags.items()}
    for rule in rules:
        if not rule.enabled:
            continue
        violation_kind = evaluate_rule_against_tags(rule.key, rule.definition, tags_lower)
        existing = _find_open_finding_by_rule_key(session, resource.id, rule.key)

        if violation_kind is None:
            if existing is not None:
                # FR-006: record which version most recently evaluated this
                # finding even on the closing evaluation -- a finding resolved
                # under version 2 must show version 2, not stay stuck showing
                # the stale version 1 that originally opened it (found by
                # writing test_a_finding_follows_its_rule_across_an_edit and
                # getting rule_v1's id back after a version-2 close, not by
                # inspection).
                existing.rule_id = rule.id
                existing.rule_version = rule.version
                existing.status = FindingStatus.RESOLVED
                existing.resolved_at = datetime.now(UTC)
            continue

        severity = rule.definition.get("severity", "medium")
        if existing is not None:
            # research.md R-301: re-point to the current version rather than
            # inserting a duplicate (FR-015) -- a no-op if nothing changed.
            existing.rule_id = rule.id
            existing.rule_version = rule.version
            existing.severity = severity
        else:
            session.add(
                Finding(
                    resource_id=resource.id,
                    rule_id=rule.id,
                    rule_version=rule.version,
                    severity=severity,
                    status=FindingStatus.OPEN,
                )
            )
    session.flush()


def _latest_enabled_rules(session: TenantSession) -> list[RuleRow]:
    """One row per key -- the current (latest) version, matching `rules.py`'s
    own `list_rules` query -- filtered to `enabled` only (a disabled rule
    produces no finding, regardless of its own definition)."""
    stmt = (
        session.scoped(select(RuleRow), RuleRow)
        .distinct(RuleRow.key)
        .order_by(RuleRow.key, RuleRow.version.desc())
    )
    rows = session.raw.execute(stmt).scalars().all()
    return [r for r in rows if r.enabled]


def validate_account(session: TenantSession, cloud_account_id: uuid.UUID) -> int:
    """FR-013: evaluate every top-level, non-deleted resource in this account
    against every enabled rule. Returns the count of resources evaluated."""
    resolve_parent_child_relationships(session, cloud_account_id)
    rules = _latest_enabled_rules(session)
    resources = (
        session.raw.execute(
            session.scoped(select(Resource), Resource).where(
                Resource.cloud_account_id == cloud_account_id,
                Resource.parent_resource_id.is_(None),
                Resource.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    for resource in resources:
        evaluate_resource(session, resource, rules)
    logger.info(
        "validation complete",
        extra={"cloud_account_id": str(cloud_account_id), "resources_evaluated": len(resources)},
    )
    return len(resources)


def validate_scan(session: TenantSession, scan: Scan) -> int:
    """FR-017: validation runs only for a scan recorded `succeeded` or
    `partial`, never `failed` -- reusing spec 002's R-204 completion gating
    exactly, the same way spec 002's own deleted-marker sweep is gated."""
    if scan.status not in (ScanStatus.SUCCEEDED, ScanStatus.PARTIAL):
        return 0
    return validate_account(session, scan.cloud_account_id)


__all__ = [
    "resolve_parent_child_relationships",
    "evaluate_rule_against_tags",
    "evaluate_resource",
    "validate_account",
    "validate_scan",
]
