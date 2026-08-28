"""Compliance scoring per account and per SDA (FR-018, FR-019a, research.md
data-model.md — reuses T016's canonical top-level-resource definition).

Score = count of top-level resources with zero open findings, divided by the
total count of top-level resources in scope. A scope with no top-level
resources is well-defined as fully compliant (1.0), not a division error
(FR-019a) — the contract's `ComplianceScore.score` doc already commits to
this reading.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import TenantSession
from app.models.core import Finding, Resource
from app.models.enums import FindingStatus


def compute_score(compliant_count: int, total_count: int) -> float:
    """FR-018/FR-019a: the score formula in isolation from any query."""
    if total_count == 0:
        return 1.0
    return compliant_count / total_count


def _counts(session: TenantSession, resources: list[Resource]) -> tuple[int, int]:
    total_count = len(resources)
    if total_count == 0:
        return 0, 0
    resource_ids = [r.id for r in resources]
    open_resource_ids = set(
        session.raw.execute(
            session.scoped(select(Finding.resource_id).distinct(), Finding).where(
                Finding.resource_id.in_(resource_ids),
                Finding.status == FindingStatus.OPEN,
            )
        )
        .scalars()
        .all()
    )
    compliant_count = total_count - len(open_resource_ids)
    return compliant_count, total_count


def account_compliance_score(
    session: TenantSession, cloud_account_id: uuid.UUID
) -> tuple[int, int, float]:
    """FR-018, scoped to one account. Returns (compliant_count, total_count, score)."""
    stmt = session.scoped(select(Resource), Resource).where(
        Resource.cloud_account_id == cloud_account_id,
        Resource.parent_resource_id.is_(None),
        Resource.deleted_at.is_(None),
    )
    resources = session.raw.execute(stmt).scalars().all()
    compliant_count, total_count = _counts(session, list(resources))
    return compliant_count, total_count, compute_score(compliant_count, total_count)


def sda_compliance_score(session: TenantSession, sda_id: uuid.UUID) -> tuple[int, int, float]:
    """FR-018, scoped to one SDA (FR-019a: well-defined at zero resources)."""
    stmt = session.scoped(select(Resource), Resource).where(
        Resource.sda_id == sda_id,
        Resource.parent_resource_id.is_(None),
        Resource.deleted_at.is_(None),
    )
    resources = session.raw.execute(stmt).scalars().all()
    compliant_count, total_count = _counts(session, list(resources))
    return compliant_count, total_count, compute_score(compliant_count, total_count)


__all__ = ["compute_score", "account_compliance_score", "sda_compliance_score"]
