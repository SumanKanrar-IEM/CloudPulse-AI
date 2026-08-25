"""resource.sda_id, owner_identity_override, tenant.owner_identity_pattern,
and the five seeded tagging rules (spec 003).

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-25

REVERSIBLE: yes

Additive only (data-model.md, constitution Principle I): one nullable FK column on
`resource`, one new table, one nullable column on `tenant` -- no rewrite of existing
rows. The five seeded `rule` rows are FR-001's discipline applied to seeding itself
(data-model.md's "seed data" note): delivered as a migration-time INSERT against the
single seeded tenant (migration 0002), not application code.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# spec.md FR-003: four required, one recognized-but-not-required.
_SEEDED_RULES: tuple[tuple[str, bool], ...] = (
    ("project_name", True),
    ("owner", True),
    ("project_id", True),
    ("created_by", True),
    ("environment", False),
)


def upgrade() -> None:
    op.add_column("resource", sa.Column("sda_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_resource_sda_id_sda",
        "resource",
        "sda",
        ["sda_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_resource_sda_id", "resource", ["sda_id"])

    op.add_column("tenant", sa.Column("owner_identity_pattern", sa.String(500), nullable=True))

    op.create_table(
        "owner_identity_override",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", sa.String(2048), nullable=False),
        sa.Column("owner_email", sa.String(320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_owner_identity_override"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_owner_identity_override_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "principal_id", name="uq_owner_identity_override_tenant_principal"
        ),
    )
    op.create_index(
        "ix_owner_identity_override_tenant_id", "owner_identity_override", ["tenant_id"]
    )

    connection = op.get_bind()
    tenant_id = connection.execute(sa.text("SELECT id FROM tenant LIMIT 1")).scalar_one()
    rule_table = sa.table(
        "rule",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tenant_id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("definition", postgresql.JSONB),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        rule_table,
        [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "key": key,
                "version": 1,
                "definition": json.dumps(
                    {
                        "required": required,
                        "allowed_values": None,
                        "format_pattern": None,
                        "severity": "medium",
                    }
                ),
                "enabled": True,
            }
            for key, required in _SEEDED_RULES
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM rule WHERE key = ANY(:keys) AND version = 1").bindparams(
            keys=[key for key, _ in _SEEDED_RULES]
        )
    )
    op.drop_index("ix_owner_identity_override_tenant_id", table_name="owner_identity_override")
    op.drop_table("owner_identity_override")
    op.drop_column("tenant", "owner_identity_pattern")
    op.drop_index("ix_resource_sda_id", table_name="resource")
    op.drop_constraint("fk_resource_sda_id_sda", "resource", type_="foreignkey")
    op.drop_column("resource", "sda_id")
