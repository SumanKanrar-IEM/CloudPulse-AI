"""notification_outcome: drop the unreachable `withheld_bounced` value
(spec 005, T017b).

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-04

REVERSIBLE: yes

The value was created by 0012 for FR-010's bounce clause, which cited a
"spec 003 bounce flagging" feature that does not exist anywhere in this
repository. T017a recorded the evidence; the decision taken was to amend
FR-010 rather than build bounce handling, so the value now has nothing that
could ever write it. Removing it keeps the schema an honest statement of what
the system can actually record.

Postgres cannot drop a value from an existing enum type, so this takes the
standard rename-create-recast-drop route. The recast fails loudly if any row
somehow holds the value -- which is the correct outcome, not a hazard: such a
row would mean bounce handling exists after all and this migration is wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WITH_BOUNCED = "'sent', 'withheld_no_owner_email', 'withheld_bounced', 'suppressed_finding_closed'"
_WITHOUT_BOUNCED = "'sent', 'withheld_no_owner_email', 'suppressed_finding_closed'"


def _swap_enum(values: str) -> None:
    op.execute("ALTER TYPE notification_outcome RENAME TO notification_outcome_old")
    op.execute(f"CREATE TYPE notification_outcome AS ENUM ({values})")
    op.execute(
        "ALTER TABLE notification ALTER COLUMN outcome "
        "TYPE notification_outcome USING outcome::text::notification_outcome"
    )
    op.execute("DROP TYPE notification_outcome_old")


def upgrade() -> None:
    _swap_enum(_WITHOUT_BOUNCED)


def downgrade() -> None:
    _swap_enum(_WITH_BOUNCED)
