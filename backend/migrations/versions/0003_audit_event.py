"""audit_event, with the append-only controls that make FR-029 real.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-22

REVERSIBLE: no

Deliberately irreversible. The downgrade would have to restore UPDATE and DELETE
privileges on the audit table and drop the immutability trigger -- undoing the exact
control FR-029 exists to provide. An audit trail that can be made mutable by running
one command is not an audit trail.

If this revision must be rolled back, that is a decision to be taken deliberately and
by hand, with the reasoning recorded in AI_WORKFLOW_JOURNAL.md -- not by `alembic
downgrade`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The role the application connects as. Distinct from the migration role, which owns
# the schema -- that separation is what lets us withhold UPDATE/DELETE from the
# application while migrations can still create and alter the table.
APP_ROLE = "cloudpulse_app"

IMMUTABILITY_TRIGGER = """
CREATE OR REPLACE FUNCTION audit_event_is_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'audit_event is append-only (FR-029): % is not permitted on this table',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW
    EXECUTE FUNCTION audit_event_is_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "audit_event",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(320), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(2048), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_event"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_audit_event_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["app_user.id"],
            name="fk_audit_event_actor_user_id_app_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_audit_event_tenant_id", "audit_event", ["tenant_id"])
    op.create_index("ix_audit_event_tenant_occurred", "audit_event", ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_event_correlation", "audit_event", ["correlation_id"])

    # --- Layer 2 of three: a trigger that refuses UPDATE and DELETE outright.
    # Applies to every caller including the schema owner, so it holds even where the
    # grant in layer 1 does not.
    op.execute(IMMUTABILITY_TRIGGER)

    # --- Layer 1 of three: the application role never receives UPDATE or DELETE.
    # Created here rather than assumed to exist, so a fresh environment is governed
    # identically to an existing one.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT INSERT, SELECT ON audit_event TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM {APP_ROLE}")

    # Layer 3 -- no ORM update or delete path -- lives in app/models/core.py and
    # app/core/audit.py.
    #
    # No retention mechanism is created here, and none may be added later: FR-029a
    # makes the ABSENCE of an expiry the correct implementation. A reviewer should
    # treat any lifecycle rule, partition drop, or purge job on this table as a defect.


def downgrade() -> None:
    raise RuntimeError(
        "Revision 0003 is irreversible (REVERSIBLE: no). Downgrading would restore "
        "UPDATE/DELETE on audit_event and drop the immutability trigger, undoing the "
        "control FR-029 exists to provide. If this is genuinely required, do it by "
        "hand and record the reasoning in AI_WORKFLOW_JOURNAL.md."
    )
