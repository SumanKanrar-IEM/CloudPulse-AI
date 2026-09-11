"""coverage advisory gaps: gaps that need code and can never be proposals
(spec 006, T038a).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-11

REVERSIBLE: yes

One additive tenant-scoped table, no new enum, nothing existing changed.

A separate table rather than a third `coverage_proposal_kind` value or a fourth
`proposal_review_state`. FR-015a's rule is that these gaps are not decidable at
all, and the cheapest way to keep that true is to give them a row shape with no
decision columns to fill in. Migration 0015's own note applies in the same
spirit: adding a value to a native Postgres enum is cheap, removing one is the
rename-create-recast-drop dance 0014 had to perform -- so a value that exists
only to be excluded everywhere is worth not adding.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        primary_key=True,
    )


def _tenant_fk() -> sa.Column[Any]:
    return sa.Column(
        "tenant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "coverage_advisory_gap",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(200), nullable=False),
        sa.Column(
            "evidence_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cloud_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # One row per type per tenant: each advisor run refreshes the standing gap
    # in place instead of stacking a daily copy of the same unchanged finding.
    op.create_index(
        "uq_coverage_advisory_gap_type",
        "coverage_advisory_gap",
        ["tenant_id", "resource_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("coverage_advisory_gap")
