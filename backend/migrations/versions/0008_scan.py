"""scan -- created empty for spec 002.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-22

REVERSIBLE: yes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "trigger", postgresql.ENUM(name="scan_trigger", create_type=False), nullable=False
        ),
        sa.Column("status", postgresql.ENUM(name="scan_status", create_type=False), nullable=False),
        sa.Column("resource_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # Points at the immutable raw snapshot in S3. The bucket is provisioned by this
        # spec; its lifecycle policy belongs to spec 002.
        sa.Column("snapshot_s3_key", sa.String(2048), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_scan_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["cloud_account_id"],
            ["cloud_account.id"],
            name="fk_scan_cloud_account_id_cloud_account",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_scan_tenant_id", "scan", ["tenant_id"])
    op.create_index("ix_scan_account_started", "scan", ["cloud_account_id", "started_at"])


def downgrade() -> None:
    op.drop_table("scan")
