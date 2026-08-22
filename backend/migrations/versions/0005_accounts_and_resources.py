"""cloud_account and resource -- created empty for spec 002.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-22

REVERSIBLE: yes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cloud_account",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aws_account_id", sa.String(12), nullable=False),
        sa.Column("alias", sa.String(200), nullable=False),
        sa.Column(
            "connection_mode",
            postgresql.ENUM(name="connection_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("role_arn", sa.String(2048), nullable=True),
        # A Secrets Manager REFERENCE, never a value. Principle III, FR-007.
        sa.Column("external_id_ref", sa.String(2048), nullable=True),
        sa.Column(
            "scan_regions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="account_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cloud_account"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_cloud_account_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "aws_account_id", name="uq_cloud_account_tenant_account"),
        sa.CheckConstraint(
            "aws_account_id ~ '^[0-9]{12}$'", name="ck_cloud_account_aws_account_id_is_12_digits"
        ),
        sa.CheckConstraint(
            "connection_mode <> 'assume_role' OR role_arn IS NOT NULL",
            name="ck_cloud_account_assume_role_requires_arn",
        ),
    )
    op.create_index("ix_cloud_account_tenant_id", "cloud_account", ["tenant_id"])

    op.create_table(
        "resource",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("arn", sa.String(2048), nullable=False),
        sa.Column("resource_type", sa.String(200), nullable=False),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("region", sa.String(50), nullable=False),
        sa.Column(
            "tags", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("parent_resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
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
        sa.PrimaryKeyConstraint("id", name="pk_resource"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_resource_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["cloud_account_id"],
            ["cloud_account.id"],
            name="fk_resource_cloud_account_id_cloud_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_resource_id"],
            ["resource.id"],
            name="fk_resource_parent_resource_id_resource",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("tenant_id", "arn", name="uq_resource_tenant_arn"),
    )
    op.create_index("ix_resource_tenant_id", "resource", ["tenant_id"])
    op.create_index("ix_resource_account_type", "resource", ["cloud_account_id", "resource_type"])
    # GIN over tags: spec 003 filters on tag keys across the whole inventory, and a
    # btree index cannot answer "which resources lack the owner key".
    op.create_index("ix_resource_tags", "resource", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("resource")
    op.drop_table("cloud_account")
