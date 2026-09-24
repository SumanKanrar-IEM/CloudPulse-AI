"""cloud_account.failure_reason: why a failed account failed (spec 002, T062).

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-25

REVERSIBLE: yes

One nullable column and one check constraint, nothing existing changed. No
backfill: before this revision nothing ever set `status = 'failed'`, so every
existing row already satisfies the constraint.

FR-012 needs the reason an admin sees stored with the status it explains, so
the constraint mirrors `ck_agent_run_failure_reason_shape` (0015): a failed
account always carries a reason, and no other status ever does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cloud_account", sa.Column("failure_reason", sa.Text()))
    op.create_check_constraint(
        "ck_cloud_account_failure_reason_shape",
        "cloud_account",
        "(status = 'failed' AND failure_reason IS NOT NULL) "
        "OR (status <> 'failed' AND failure_reason IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cloud_account_failure_reason_shape", "cloud_account", type_="check")
    op.drop_column("cloud_account", "failure_reason")
