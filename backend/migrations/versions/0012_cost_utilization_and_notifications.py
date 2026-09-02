"""spend_record, budget, notification, iam_hygiene_flag; finding gains
kind/sda_id/escalated_at and nullable resource/rule columns (spec 005).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-03

REVERSIBLE: yes

Additive for every existing row (data-model.md, constitution Principle I): four
new tables, four new enum types, and `finding` gains three new nullable columns
plus a widened nullability on three existing ones. No existing `finding` row's
`kind` changes -- the new column defaults to `tag_violation`, so every row
already in the table keeps exactly the shape it always had, and
`ck_finding_kind_shape` (below) is satisfied by every one of them without a
backfill. `uq_finding_open_per_resource_rule` (spec 003's existing partial
unique index) is untouched -- a `budget_overrun` row's `resource_id`/`rule_id`
are always NULL, which Postgres never treats as matching any other row's NULL
(research.md R-508).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- New enum types (app/models/enums.py's FindingKind/NotificationCadencePoint/
    # NotificationOutcome/IamPrincipalType) -- created directly here, following
    # migration 0011's own suggestion_source precedent, not the ENUM_TYPES dict
    # (that dict is migration 0001's one-time initial registry only).
    op.execute("CREATE TYPE finding_kind AS ENUM ('tag_violation', 'budget_overrun')")
    op.execute("CREATE TYPE notification_cadence_point AS ENUM ('day_0', 'day_2', 'day_4')")
    op.execute(
        "CREATE TYPE notification_outcome AS ENUM "
        "('sent', 'withheld_no_owner_email', 'withheld_bounced', 'suppressed_finding_closed')"
    )
    op.execute("CREATE TYPE iam_principal_type AS ENUM ('role', 'user', 'access_key')")

    # --- finding: widen nullability, add kind/sda_id/escalated_at -------------
    op.alter_column("finding", "resource_id", nullable=True)
    op.alter_column("finding", "rule_id", nullable=True)
    op.alter_column("finding", "rule_version", nullable=True)
    op.add_column(
        "finding",
        sa.Column(
            "kind",
            postgresql.ENUM(name="finding_kind", create_type=False),
            nullable=False,
            server_default="tag_violation",
        ),
    )
    op.add_column("finding", sa.Column("sda_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_finding_sda_id_sda", "finding", "sda", ["sda_id"], ["id"], ondelete="CASCADE"
    )
    op.add_column("finding", sa.Column("escalated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_finding_kind_shape",
        "finding",
        "(kind = 'tag_violation' AND resource_id IS NOT NULL AND rule_id IS NOT NULL "
        "AND rule_version IS NOT NULL AND sda_id IS NULL) "
        "OR "
        "(kind = 'budget_overrun' AND sda_id IS NOT NULL AND resource_id IS NULL "
        "AND rule_id IS NULL AND rule_version IS NULL)",
    )
    op.create_index(
        "uq_finding_open_overrun_per_sda",
        "finding",
        ["tenant_id", "sda_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open' AND kind = 'budget_overrun'"),
    )

    # --- spend_record -----------------------------------------------------------
    op.create_table(
        "spend_record",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sda_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("spend_date", sa.Date(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("is_gap", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_spend_record"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_spend_record_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cloud_account_id"],
            ["cloud_account.id"],
            name="fk_spend_record_cloud_account_id_cloud_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sda_id"], ["sda.id"], name="fk_spend_record_sda_id_sda", ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "cloud_account_id",
            "service",
            "spend_date",
            "sda_id",
            name="uq_spend_record_tenant_account_service_date_sda",
        ),
        sa.CheckConstraint(
            "is_gap = true OR amount_usd IS NOT NULL",
            name="ck_spend_record_amount_required_unless_gap",
        ),
    )
    op.create_index("ix_spend_record_tenant_id", "spend_record", ["tenant_id"])
    op.create_index(
        "ix_spend_record_account_date", "spend_record", ["cloud_account_id", "spend_date"]
    )

    # --- budget -------------------------------------------------------------
    op.create_table(
        "budget",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sda_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("actual_80_crossed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_100_crossed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forecast_80_crossed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forecast_100_crossed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_budget"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_budget_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["sda_id"], ["sda.id"], name="fk_budget_sda_id_sda", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("tenant_id", "sda_id", name="uq_budget_tenant_sda"),
    )
    op.create_index("ix_budget_tenant_id", "budget", ["tenant_id"])

    # --- notification ---------------------------------------------------------
    op.create_table(
        "notification",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "cadence_point",
            postgresql.ENUM(name="notification_cadence_point", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="notification_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column("recipient_email", sa.String(320), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_notification_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.id"],
            name="fk_notification_finding_id_finding",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "finding_id",
            "cadence_point",
            name="uq_notification_tenant_finding_cadence",
        ),
    )
    op.create_index("ix_notification_tenant_id", "notification", ["tenant_id"])

    # --- iam_hygiene_flag -----------------------------------------------------
    op.create_table(
        "iam_hygiene_flag",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "principal_type",
            postgresql.ENUM(name="iam_principal_type", create_type=False),
            nullable=False,
        ),
        sa.Column("principal_identifier", sa.String(2048), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "flagged_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_iam_hygiene_flag"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_iam_hygiene_flag_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cloud_account_id"],
            ["cloud_account.id"],
            name="fk_iam_hygiene_flag_cloud_account_id_cloud_account",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_iam_hygiene_flag_tenant_id", "iam_hygiene_flag", ["tenant_id"])
    op.create_index(
        "uq_iam_hygiene_flag_active_principal",
        "iam_hygiene_flag",
        ["tenant_id", "cloud_account_id", "principal_identifier"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_iam_hygiene_flag_active_principal", table_name="iam_hygiene_flag")
    op.drop_index("ix_iam_hygiene_flag_tenant_id", table_name="iam_hygiene_flag")
    op.drop_table("iam_hygiene_flag")

    op.drop_index("ix_notification_tenant_id", table_name="notification")
    op.drop_table("notification")

    op.drop_index("ix_budget_tenant_id", table_name="budget")
    op.drop_table("budget")

    op.drop_index("ix_spend_record_account_date", table_name="spend_record")
    op.drop_index("ix_spend_record_tenant_id", table_name="spend_record")
    op.drop_table("spend_record")

    op.drop_index("uq_finding_open_overrun_per_sda", table_name="finding")
    op.drop_constraint("ck_finding_kind_shape", "finding", type_="check")
    op.drop_column("finding", "escalated_at")
    op.drop_constraint("fk_finding_sda_id_sda", "finding", type_="foreignkey")
    op.drop_column("finding", "sda_id")
    op.drop_column("finding", "kind")
    op.alter_column("finding", "rule_version", nullable=False)
    op.alter_column("finding", "rule_id", nullable=False)
    op.alter_column("finding", "resource_id", nullable=False)

    op.execute("DROP TYPE iam_principal_type")
    op.execute("DROP TYPE notification_outcome")
    op.execute("DROP TYPE notification_cadence_point")
    op.execute("DROP TYPE finding_kind")
