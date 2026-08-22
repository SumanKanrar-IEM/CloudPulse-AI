"""The migration Lambda gates the deployment (FR-016, FR-021, R-002).

The pipeline invokes it synchronously and fails the deployment on a non-zero result,
*before* the API alias shifts. So the property that matters is not "migrations work" —
that is covered by test_migrations.py — but "a failure is reported as a failure and
leaves the schema untouched."
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from handlers import migrate_handler

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _point_alembic_at_the_container(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres_url)


def test_upgrade_succeeds_and_reports_ok(clean_database: Engine) -> None:
    result = migrate_handler.handler({"command": "upgrade", "revision": "head"})
    assert result["ok"] is True
    assert "tenant" in inspect(clean_database).get_table_names()


def test_a_failing_revision_returns_not_ok(
    clean_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pipeline reads the payload, so a failure must be a flag, not an exception.

    An uncaught exception surfaces as a Lambda invocation error, which is harder to
    gate on than `ok: false`.
    """
    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(command, "upgrade", _boom)
    result = migrate_handler.handler({"command": "upgrade", "revision": "head"})

    assert result["ok"] is False
    assert "simulated migration failure" in result["error"]


def test_a_failing_migration_leaves_the_schema_unchanged(clean_database: Engine) -> None:
    """FR-021: a failed deployment leaves the environment in a known state.

    Alembic runs each revision in a transaction, so a mid-revision failure rolls back
    rather than leaving a half-applied schema.
    """
    migrate_handler.handler({"command": "upgrade", "revision": "0004"})
    before = set(inspect(clean_database).get_table_names())

    with clean_database.begin() as conn:
        # Force 0005 to fail by pre-creating one of its tables.
        conn.execute(text("CREATE TABLE cloud_account (id int)"))

    result = migrate_handler.handler({"command": "upgrade", "revision": "head"})
    assert result["ok"] is False

    after = set(inspect(clean_database).get_table_names())
    # Only the table we planted ourselves is new; no partial application.
    assert after - before == {"cloud_account"}


def test_downgrade_is_refused(clean_database: Engine) -> None:
    """A rollback is a deliberate human act.

    Revision 0003 is irreversible by design (FR-029), so an automated downgrade path
    would make undoing the audit-immutability controls a single API call.
    """
    result = migrate_handler.handler({"command": "downgrade", "revision": "0002"})
    assert result["ok"] is False
    assert "not permitted" in result["error"]


@pytest.mark.parametrize("command_name", ["drop", "exec", "", "UPGRADE; DROP TABLE tenant"])
def test_unknown_commands_are_refused(clean_database: Engine, command_name: str) -> None:
    """Allowlist, not denylist: anything unrecognised is refused."""
    result = migrate_handler.handler({"command": command_name})
    assert result["ok"] is False
    assert "not permitted" in result["error"]


def test_the_result_names_the_environment(clean_database: Engine, monkeypatch) -> None:
    """FR-023: the pipeline records which environment was touched."""
    monkeypatch.setenv("CLOUDPULSE_ENVIRONMENT", "dev")
    result = migrate_handler.handler({"command": "upgrade", "revision": "head"})
    assert result["environment"] == "dev"
