"""rule and finding -- created empty for spec 003.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22

REVERSIBLE: yes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rule",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        # Rules are DATA, not code (Principle V). The rule body lives here so a rule
        # change is a data change and needs no deployment.
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rule"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_rule_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "key", "version", name="uq_rule_tenant_key_version"),
    )
    op.create_index("ix_rule_tenant_id", "rule", ["tenant_id"])

    op.create_table(
        "finding",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Pinned rather than derived: the rule may be superseded, and the finding must
        # still say which version produced it.
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column(
            "severity", postgresql.ENUM(name="finding_severity", create_type=False), nullable=False
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="finding_status", create_type=False),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_finding_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resource.id"],
            name="fk_finding_resource_id_resource",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["rule.id"], name="fk_finding_rule_id_rule", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "status <> 'resolved' OR resolved_at IS NOT NULL",
            name="ck_finding_resolved_requires_timestamp",
        ),
    )
    op.create_index("ix_finding_tenant_id", "finding", ["tenant_id"])
    op.create_index(
        "ix_finding_tenant_status_severity", "finding", ["tenant_id", "status", "severity"]
    )
    # Partial unique index: at most ONE open finding per (resource, rule). Re-running a
    # scan must not create duplicates, but a resolved finding may coexist with a later
    # re-opened one -- which a plain unique constraint would forbid.
    op.create_index(
        "uq_finding_open_per_resource_rule",
        "finding",
        ["tenant_id", "resource_id", "rule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("finding")
    op.drop_table("rule")
