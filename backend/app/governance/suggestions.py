"""A finding's remediation suggestion: fetch-or-none, admin-seed write
(spec 004, FR-018-FR-020a).

Thin -- FR-019's "no suggestion available" is the normal case for most
findings until the AI-insights capability (a later spec) exists to write
`ai_generated` rows; this module has no path to writing that value itself
(research.md's data-model.md), only `admin_seeded`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import TenantSession
from app.models.core import FindingRemediationSuggestion
from app.models.enums import SuggestionSource


def get_suggestion(
    session: TenantSession, finding_id: uuid.UUID
) -> FindingRemediationSuggestion | None:
    """FR-019: None means "no suggestion available", not an error."""
    stmt = session.scoped(select(FindingRemediationSuggestion), FindingRemediationSuggestion).where(
        FindingRemediationSuggestion.finding_id == finding_id
    )
    return session.raw.execute(stmt).scalar_one_or_none()


def seed_suggestion(
    session: TenantSession,
    finding_id: uuid.UUID,
    suggestion_text: str,
    blast_radius_note: str,
) -> FindingRemediationSuggestion:
    """FR-020a: always writes `source=admin_seeded` -- there is no parameter
    that could make this write `ai_generated` instead. Upserts on
    `(tenant_id, finding_id)` (data-model.md: one suggestion per finding, not
    an append-only log)."""
    stmt = (
        pg_insert(FindingRemediationSuggestion)
        .values(
            tenant_id=session.tenant_id,
            finding_id=finding_id,
            suggestion_text=suggestion_text,
            blast_radius_note=blast_radius_note,
            source=SuggestionSource.ADMIN_SEEDED,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "finding_id"],
            set_={
                "suggestion_text": suggestion_text,
                "blast_radius_note": blast_radius_note,
                "source": SuggestionSource.ADMIN_SEEDED,
            },
        )
        .returning(FindingRemediationSuggestion)
    )
    result = session.raw.execute(stmt).scalar_one()
    session.raw.flush()
    return result


__all__ = ["get_suggestion", "seed_suggestion"]
