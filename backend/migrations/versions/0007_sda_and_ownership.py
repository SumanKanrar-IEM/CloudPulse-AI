"""sda and resource_owner -- created empty for spec 003.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-22

REVERSIBLE: yes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sda",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_email", sa.String(320), nullable=False),
        sa.Column("team", sa.String(200), nullable=True),
        sa.Column(
            "tag_values", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sda"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_sda_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_sda_tenant_name"),
    )
    op.create_index("ix_sda_tenant_id", "sda", ["tenant_id"])

    op.create_table(
        "resource_owner",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_email", sa.String(320), nullable=True),
        # An attribution without evidence is a guess presented as a fact, so the
        # evidence column is NOT NULL even when empty.
        sa.Column(
            "evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "confidence",
            postgresql.ENUM(name="owner_confidence", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "attributed_at",
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
        sa.PrimaryKeyConstraint("id", name="pk_resource_owner"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_resource_owner_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resource.id"],
            name="fk_resource_owner_resource_id_resource",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "resource_id", name="uq_resource_owner_tenant_resource"),
    )
    op.create_index("ix_resource_owner_tenant_id", "resource_owner", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("resource_owner")
    op.drop_table("sda")
