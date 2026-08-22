"""deployment, with the prod-approval constraint enforced in the database.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-22

REVERSIBLE: yes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deployment",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "environment",
            postgresql.ENUM(name="deployment_environment", create_type=False),
            nullable=False,
        ),
        sa.Column("git_sha", sa.String(40), nullable=False),
        sa.Column("triggered_by", sa.String(200), nullable=False),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("self_approved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("migration_revision", sa.String(64), nullable=True),
        sa.Column(
            "status", postgresql.ENUM(name="deployment_status", create_type=False), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_deployment"),
        # FR-017 / FR-018: a prod deployment row cannot exist without a recorded
        # approver. Enforced by the database so no future code path can route around
        # it -- an application-level check is only as good as the last developer who
        # remembered it.
        sa.CheckConstraint(
            "environment <> 'prod' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_deployment_prod_requires_approver",
        ),
    )
    op.create_index("ix_deployment_env_started", "deployment", ["environment", "started_at"])

    # deployment is the ONE table without tenant_id: it records an act on the platform
    # itself, not on a tenant's data. Called out so it does not read as an FR-030
    # oversight during review.


def downgrade() -> None:
    op.drop_index("ix_deployment_env_started", table_name="deployment")
    op.drop_table("deployment")
