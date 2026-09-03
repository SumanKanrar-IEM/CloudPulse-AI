"""spend_record: nullable service, NULL-safe uniqueness (spec 005, T003a).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-03

REVERSIBLE: yes

Fixes a real defect found while implementing T007 (spend ingestion), before
any row existed in the table this migration touches -- `spend_record` was
created empty by 0012 in this same feature branch, so there is no data to
migrate, only shape to correct. `service` becomes nullable (a whole-day gap
row has no per-service breakdown to report -- the same "never guess" rule
`amount_usd` already followed, now applied here too). The single plain
`UniqueConstraint` migration 0012 created is replaced by three partial unique
indexes: Postgres never treats two NULLs as equal for a plain constraint's
purposes, so a nullable `sda_id` ("No SDA" bucket) silently let duplicate
rows through for the same account/service/day -- a correction ingestion
would have inserted a second row instead of updating the first. See
data-model.md and app/models/core.py's own SpendRecord docstring for the
full account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_spend_record_tenant_account_service_date_sda", "spend_record", type_="unique"
    )
    op.drop_constraint("ck_spend_record_amount_required_unless_gap", "spend_record", type_="check")
    op.alter_column("spend_record", "service", nullable=True)
    op.create_check_constraint(
        "ck_spend_record_amount_and_service_required_unless_gap",
        "spend_record",
        "is_gap = true OR (service IS NOT NULL AND amount_usd IS NOT NULL)",
    )
    op.create_index(
        "uq_spend_record_tenant_account_service_date_sda",
        "spend_record",
        ["tenant_id", "cloud_account_id", "service", "spend_date", "sda_id"],
        unique=True,
        postgresql_where=sa.text("is_gap = false AND sda_id IS NOT NULL"),
    )
    op.create_index(
        "uq_spend_record_tenant_account_service_date_no_sda",
        "spend_record",
        ["tenant_id", "cloud_account_id", "service", "spend_date"],
        unique=True,
        postgresql_where=sa.text("is_gap = false AND sda_id IS NULL"),
    )
    op.create_index(
        "uq_spend_record_gap_per_account_date",
        "spend_record",
        ["tenant_id", "cloud_account_id", "spend_date"],
        unique=True,
        postgresql_where=sa.text("is_gap = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_spend_record_gap_per_account_date", table_name="spend_record")
    op.drop_index("uq_spend_record_tenant_account_service_date_no_sda", table_name="spend_record")
    op.drop_index("uq_spend_record_tenant_account_service_date_sda", table_name="spend_record")
    op.drop_constraint(
        "ck_spend_record_amount_and_service_required_unless_gap", "spend_record", type_="check"
    )
    op.alter_column("spend_record", "service", nullable=False)
    op.create_check_constraint(
        "ck_spend_record_amount_required_unless_gap",
        "spend_record",
        "is_gap = true OR amount_usd IS NOT NULL",
    )
    op.create_unique_constraint(
        "uq_spend_record_tenant_account_service_date_sda",
        "spend_record",
        ["tenant_id", "cloud_account_id", "service", "spend_date", "sda_id"],
    )
