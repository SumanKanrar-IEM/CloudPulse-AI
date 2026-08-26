"""SDA tag-value matching, overlap detection, and reclassification
(FR-008, FR-009, FR-010, FR-010a, research.md R-305).

`reclassify_account_resources` is the function Phase 7's compliance-validation
worker calls once per finalized scan (research.md R-303); it is invoked directly
here and in tests/integration/test_sda_matching_and_reclassification.py to prove
the matching/reclassification logic itself, independent of how it gets triggered
-- the same "pure logic module now, wired to a real scan later" split Phase 5's
`validation.py` and Phase 7's worker wiring also follow.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import TenantSession
from app.models.core import Resource, Sda


def matches(resource_tags: dict[str, str], sda_tag_values: dict[str, str]) -> bool:
    """FR-008: every key in `sda_tag_values` is present on the resource with
    exactly that value. An empty mapping matches nothing -- an SDA with no
    criteria yet must never silently claim every resource."""
    if not sda_tag_values:
        return False
    return all(resource_tags.get(key) == value for key, value in sda_tag_values.items())


def find_matching_sda(resource_tags: dict[str, str], sdas: list[Sda]) -> Sda | None:
    """FR-008/FR-009: the SDA whose mapping this resource's tags satisfy, or
    `None` (the "No SDA" bucket). At most one match exists by construction --
    `mappings_overlap` refuses any registration that would make two SDAs' mappings
    both matchable by the same resource (FR-010a)."""
    for sda in sdas:
        if matches(resource_tags, sda.tag_values):
            return sda
    return None


def mappings_overlap(a: dict[str, str], b: dict[str, str]) -> bool:
    """research.md R-305: two mappings overlap if, for every key present in
    *both*, the required value is the same -- catches identical mappings and the
    subset case (`{team: platform}` vs. `{team: platform, env: prod}`), not just
    exact duplicates. Two mappings sharing no keys at all are not considered
    overlapping under this rule (a deliberate, documented simplicity tradeoff,
    not resolved by a tie-break rule -- research.md R-305's own "Alternatives
    considered")."""
    shared_keys = set(a) & set(b)
    if not shared_keys:
        return False
    return all(a[key] == b[key] for key in shared_keys)


def reclassify_account_resources(session: TenantSession, cloud_account_id: uuid.UUID) -> int:
    """FR-008/FR-010: (re-)evaluate every top-level, non-deleted resource in this
    account against every currently-registered SDA, updating `sda_id`
    accordingly. Idempotent -- safe to call once per scan's governance pass
    regardless of whether anything actually changed. Returns the number of
    resources whose `sda_id` changed."""
    sdas = session.raw.execute(session.scoped(select(Sda), Sda)).scalars().all()
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
    changed = 0
    for resource in resources:
        matched = find_matching_sda(resource.tags, list(sdas))
        new_sda_id = matched.id if matched else None
        if resource.sda_id != new_sda_id:
            resource.sda_id = new_sda_id
            changed += 1
    session.flush()
    return changed


__all__ = ["matches", "find_matching_sda", "mappings_overlap", "reclassify_account_resources"]
