"""finding.acknowledged_at/acknowledged_by, finding_remediation_suggestion
(spec 004).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-01

REVERSIBLE: yes

Additive only (data-model.md, constitution Principle I): two nullable columns on
`finding`, one new table, one new enum type. No rewrite of existing rows.
`acknowledged_at`/`acknowledged_by` are orthogonal to `finding.status` -- never
changes what that column means (research.md R-404); `finding_remediation_suggestion`
is unique on `finding_id` (one suggestion per finding, an upsert target, not an
append-only log).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("finding", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.add_column(
        "finding", sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_finding_acknowledged_by_app_user",
        "finding",
        "app_user",
        ["acknowledged_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute("CREATE TYPE suggestion_source AS ENUM ('ai_generated', 'admin_seeded')")

    op.create_table(
        "finding_remediation_suggestion",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_text", sa.Text(), nullable=False),
        sa.Column("blast_radius_note", sa.Text(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(name="suggestion_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding_remediation_suggestion"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_finding_remediation_suggestion_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.id"],
            name="fk_finding_remediation_suggestion_finding_id_finding",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "finding_id",
            name="uq_finding_remediation_suggestion_tenant_finding",
        ),
    )
    op.create_index(
        "ix_finding_remediation_suggestion_tenant_id",
        "finding_remediation_suggestion",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finding_remediation_suggestion_tenant_id",
        table_name="finding_remediation_suggestion",
    )
    op.drop_table("finding_remediation_suggestion")
    op.execute("DROP TYPE suggestion_source")
    op.drop_constraint("fk_finding_acknowledged_by_app_user", "finding", type_="foreignkey")
    op.drop_column("finding", "acknowledged_by")
    op.drop_column("finding", "acknowledged_at")
