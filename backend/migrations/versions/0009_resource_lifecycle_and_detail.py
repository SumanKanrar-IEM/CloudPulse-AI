"""resource lifecycle and detail columns -- state, deleted_at, detail (spec 002).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-24

REVERSIBLE: yes

Additive only (data-model.md, constitution Principle I / spec 1's FR-048a-style
discipline applied to schema): three nullable/defaulted columns, no rewrite of
existing rows, no data migration needed since the table is currently empty.
`account_status` already has `disabled` and `scan_status` already has `partial`
from migration 0001's original enum definitions -- neither needs a migration here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resource", sa.Column("state", sa.String(100), nullable=True))
    op.add_column("resource", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "resource",
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("resource", "detail")
    op.drop_column("resource", "deleted_at")
    op.drop_column("resource", "state")
