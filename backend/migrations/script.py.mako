"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

REVERSIBLE: yes

<!-- FR-027: every revision MUST declare REVERSIBLE: yes or no in this docstring.
     CI extracts it, so an irreversible migration is identified before merge rather
     than discovered during a prod release. Change to `no` and explain why if the
     downgrade cannot restore the prior state. -->
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
