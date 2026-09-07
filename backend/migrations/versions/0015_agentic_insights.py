"""agentic insights: agent runs, digests, grounding rejections, coverage
proposals, metrics, forecasts, rightsizing (spec 006, T002).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-07

REVERSIBLE: yes

Seven new tenant-scoped tables and the seven enum types they need. Nothing
existing changes shape -- this migration is purely additive, so no spec 001-005
row is touched and no backfill is required.

Every enum below is defined with **only the values something can actually write
today**. That is the lesson migration 0014 had to pay for: `withheld_bounced`
shipped in 0012 with no code path able to set it, and removing a value from a
native Postgres enum needs the rename-create-recast-drop dance 0014 performs.
Adding a value later is additive and cheap; removing one is not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS: dict[str, tuple[str, ...]] = {
    "agent_capability": ("digest", "suggester", "advisor", "narrator"),
    # `truncated` is a first-class status, not a failure: FR-004 requires a run
    # reaching its cost cap to stop and say so.
    "agent_run_status": ("succeeded", "truncated", "failed"),
    "grounding_reference_kind": ("arn", "resource_id", "finding_id", "sda", "figure"),
    # Exactly two, deliberately (research.md R-603): a resource type with no
    # existing enricher cannot be proposed at all, because accepting it could not
    # take effect without a code change and FR-017 would be unsatisfiable. Those
    # gaps surface as read-only advisory content, never as a row here.
    "coverage_proposal_kind": ("rule_extension", "enable_existing_enricher"),
    "proposal_review_state": ("pending", "accepted", "rejected"),
    "resource_metric_kind": ("cpu", "memory", "network", "storage"),
    "forecast_kind": ("spend", "capacity"),
}


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


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    for name, values in _ENUMS.items():
        op.execute(f"CREATE TYPE {name} AS ENUM ({', '.join(repr(v) for v in values)})")

    # --- agent_run --------------------------------------------------------------
    op.create_table(
        "agent_run",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column("capability", _enum("agent_capability"), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("status", _enum("agent_run_status"), nullable=False),
        sa.Column("cost_units", sa.Numeric(12, 4), nullable=False),
        sa.Column("cost_cap_units", sa.Numeric(12, 4), nullable=False),
        sa.Column("failure_reason", sa.Text()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    # `failure_reason` is populated exactly when the run failed -- so an
    # unexplained failure and a reason attached to a success are both refused at
    # the database rather than left to every writer to remember.
    op.create_check_constraint(
        "ck_agent_run_failure_reason_shape",
        "agent_run",
        "(status = 'failed' AND failure_reason IS NOT NULL) "
        "OR (status <> 'failed' AND failure_reason IS NULL)",
    )
    op.create_index("ix_agent_run_tenant_started", "agent_run", ["tenant_id", "started_at"])

    # --- insight_digest ---------------------------------------------------------
    op.create_table(
        "insight_digest",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("is_empty", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # One digest per tenant per day: a re-run replaces rather than appends,
        # which is what stops two overlapping runs producing a duplicate.
        sa.UniqueConstraint("tenant_id", "period_date", name="uq_insight_digest_tenant_date"),
    )

    # --- grounding_rejection ----------------------------------------------------
    #
    # The rejected output itself is deliberately NOT stored. It is unvalidated
    # model text, and keeping it would create a place where fabricated ARNs live
    # inside the platform -- the exact thing FR-001 exists to prevent. The
    # reference that failed is enough to diagnose.
    op.create_table(
        "grounding_rejection",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rejected_reference", sa.Text(), nullable=False),
        sa.Column("reference_kind", _enum("grounding_reference_kind"), nullable=False),
        sa.Column(
            "rejected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_grounding_rejection_tenant_rejected",
        "grounding_rejection",
        ["tenant_id", "rejected_at"],
    )

    # --- coverage_proposal (P2) -------------------------------------------------
    op.create_table(
        "coverage_proposal",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposal_kind", _enum("coverage_proposal_kind"), nullable=False),
        sa.Column("resource_type", sa.String(200), nullable=False),
        # Evidence, not scope: acceptance applies tenant-wide (FR-017).
        sa.Column(
            "evidence_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cloud_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposed_change", postgresql.JSONB(), nullable=False),
        sa.Column(
            "review_state", _enum("proposal_review_state"), nullable=False, server_default="pending"
        ),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_coverage_proposal_decision_shape",
        "coverage_proposal",
        "(review_state = 'pending' AND decided_at IS NULL) "
        "OR (review_state <> 'pending' AND decided_at IS NOT NULL)",
    )
    # Partial, so the advisor cannot raise the same pending proposal twice while
    # every decided one stays as history. Same shape as spec 005's
    # `uq_iam_hygiene_flag_active_principal`.
    op.create_index(
        "uq_coverage_proposal_pending",
        "coverage_proposal",
        ["tenant_id", "resource_type", "proposal_kind"],
        unique=True,
        postgresql_where=sa.text("review_state = 'pending'"),
    )

    # --- resource_metric (P2) ---------------------------------------------------
    op.create_table(
        "resource_metric",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resource.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", _enum("resource_metric_kind"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(12, 4)),
        sa.Column("is_unavailable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # FR-019: a re-run updates rather than appends.
        sa.UniqueConstraint(
            "tenant_id",
            "resource_id",
            "metric",
            "period_start",
            name="uq_resource_metric_tenant_resource_metric_period",
        ),
    )
    # FR-020: unknown, never zero. The same discipline `spend_record`'s
    # amount_usd/is_gap pairing already uses -- a missing measurement recorded as
    # a zero would drag an average down and understate utilization.
    op.create_check_constraint(
        "ck_resource_metric_unavailable_shape",
        "resource_metric",
        "(is_unavailable AND value IS NULL) OR (NOT is_unavailable AND value IS NOT NULL)",
    )

    # --- forecast (P2) ----------------------------------------------------------
    #
    # No agent_run_id: forecasts are a deterministic calculation, not an agent
    # output (FR-021). The agent narrates them; the narrative is a separate
    # concern. `history_days` is what makes FR-021a's "not enough data" state
    # auditable rather than a runtime-only decision.
    op.create_table(
        "forecast",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "sda_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sda.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _enum("forecast_kind"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("projected_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("history_days", sa.Integer(), nullable=False),
        sa.Column("actual_value", sa.Numeric(14, 4)),
        sa.Column("absolute_percentage_error", sa.Numeric(6, 3)),
        sa.UniqueConstraint(
            "tenant_id",
            "sda_id",
            "kind",
            "period_start",
            name="uq_forecast_tenant_sda_kind_period",
        ),
    )

    # --- rightsizing_recommendation (P2) ----------------------------------------
    op.create_table(
        "rightsizing_recommendation",
        _uuid_pk(),
        _tenant_fk(),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resource.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("current_class", sa.String(100), nullable=False),
        sa.Column("recommended_class", sa.String(100), nullable=False),
        # NOT NULL because FR-023 requires it: a recommendation to downsize
        # something, without the measurements behind it, is a guess presented as
        # a fact.
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("estimated_monthly_saving_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_rightsizing_live_per_resource",
        "rightsizing_recommendation",
        ["tenant_id", "resource_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    for table in (
        "rightsizing_recommendation",
        "forecast",
        "resource_metric",
        "coverage_proposal",
        "grounding_rejection",
        "insight_digest",
        "agent_run",
    ):
        op.drop_table(table)
    for name in _ENUMS:
        op.execute(f"DROP TYPE {name}")
