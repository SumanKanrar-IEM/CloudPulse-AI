"""A finding's remediation suggestion: fetch-or-none, admin-seed write, and --
as of spec 006 -- the agent write (spec 004 FR-018-FR-020a; spec 006 T023,
FR-011-FR-013).

Two writers, and each can only ever write its own `source`. `seed_suggestion`
has no parameter that could make it write `ai_generated`, and
`write_ai_suggestion` none that could make it write `admin_seeded`. Provenance
is therefore a property of which function ran, not a value a caller passes --
which is what makes FR-012's "distinguishable in the interface" true at the
write layer rather than merely trusted to stay accurate at display time.

`write_ai_suggestion` is deliberately not reachable from any human-facing
endpoint (FR-013). The only caller is the suggester worker.
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


def write_ai_suggestion(
    session: TenantSession,
    finding_id: uuid.UUID,
    suggestion_text: str,
    blast_radius_note: str,
) -> bool:
    """FR-011/FR-013: write an agent suggestion, never over an admin-seeded one.

    Returns True when the row was written, False when an `admin_seeded`
    suggestion already held the slot.

    **FR-013 is enforced by the conflict clause, not by reading first.** A
    read-then-write would leave a window in which an admin seeds a suggestion
    between the check and the insert, and the agent overwrites it -- rare, silent
    and exactly the outcome the requirement forbids. The `where` below makes the
    database refuse it instead, so the race cannot exist.

    Always writes `source=ai_generated`; there is no parameter that could make it
    write anything else, mirroring `seed_suggestion`'s own guarantee.
    """
    stmt = (
        pg_insert(FindingRemediationSuggestion)
        .values(
            tenant_id=session.tenant_id,
            finding_id=finding_id,
            suggestion_text=suggestion_text,
            blast_radius_note=blast_radius_note,
            source=SuggestionSource.AI_GENERATED,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "finding_id"],
            set_={
                "suggestion_text": suggestion_text,
                "blast_radius_note": blast_radius_note,
                "source": SuggestionSource.AI_GENERATED,
            },
            where=FindingRemediationSuggestion.source == SuggestionSource.AI_GENERATED,
        )
        .returning(FindingRemediationSuggestion.id)
    )
    written = session.raw.execute(stmt).scalar_one_or_none()
    session.raw.flush()
    return written is not None


__all__ = ["get_suggestion", "seed_suggestion", "write_ai_suggestion"]
