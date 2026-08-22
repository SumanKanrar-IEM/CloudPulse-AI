"""Extensions and enum types.

Revision ID: 0001
Revises:
Create Date: 2026-08-22

REVERSIBLE: yes

Every native enum is created here, in one place, so the type vocabulary is settled
before any table references it. Members come from app.models.enums, which is the
single source of truth -- migration and models cannot drift.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors app.models.enums.ENUM_TYPES. Duplicated as literals rather than imported,
# because a migration must describe the schema at the moment it ran -- importing the
# live models would make old revisions silently change meaning as the code evolves.
ENUMS: dict[str, tuple[str, ...]] = {
    "tenant_status": ("active", "suspended"),
    "deployment_environment": ("dev", "prod"),
    "deployment_status": ("running", "succeeded", "failed"),
    "connection_mode": ("local", "assume_role"),
    "account_status": ("pending", "verified", "failed", "disabled"),
    "finding_severity": ("low", "medium", "high", "critical"),
    "finding_status": ("open", "resolved", "suppressed"),
    "scan_trigger": ("scheduled", "manual"),
    "scan_status": ("running", "succeeded", "partial", "failed"),
    "owner_confidence": ("high", "medium", "low"),
}


def upgrade() -> None:
    # gen_random_uuid() for server-side UUID primary keys.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    for name, members in ENUMS.items():
        values = ", ".join(f"'{m}'" for m in members)
        op.execute(f"CREATE TYPE {name} AS ENUM ({values})")


def downgrade() -> None:
    for name in reversed(list(ENUMS)):
        op.execute(f"DROP TYPE IF EXISTS {name}")
    # pgcrypto is left in place: other schemas in the same database may rely on it,
    # and dropping a shared extension on downgrade is a wider blast radius than the
    # revision's own scope.
