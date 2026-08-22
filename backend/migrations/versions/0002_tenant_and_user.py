"""Tenant and app_user, and the single seeded tenant.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-22

REVERSIBLE: yes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEEDED_TENANT_NAME = "CloudPulse"


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="tenant_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant"),
        sa.UniqueConstraint("name", name="uq_tenant_name"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_tenant_name_not_blank"),
    )

    # FR-030 / spec Assumptions: exactly one tenant in the MVP, but every table is
    # tenant-scoped from day one so multi-tenancy never needs a schema rewrite.
    op.execute(
        sa.text("INSERT INTO tenant (name) VALUES (:name)").bindparams(name=SEEDED_TENANT_NAME)
    )

    op.create_table(
        "app_user",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cognito_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_app_user_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("cognito_sub", name="uq_app_user_cognito_sub"),
    )
    op.create_index("ix_app_user_tenant_id", "app_user", ["tenant_id"])

    # NOTE: app_user has NO role column, deliberately.
    #
    # FR-031a makes the identity provider the sole authority for a person's role; it is
    # derived from the directory group claim on every request (FR-038). A column here
    # would be a second, drifting source of truth and a privilege-escalation surface.
    # A later migration adding one is a constitution violation, not a feature.


def downgrade() -> None:
    op.drop_index("ix_app_user_tenant_id", table_name="app_user")
    op.drop_table("app_user")
    op.drop_table("tenant")
