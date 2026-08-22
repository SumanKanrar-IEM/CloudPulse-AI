"""Migrations apply in order, to empty and populated databases alike.

FR-025 (ordered, versioned), FR-026 (no data loss), FR-027 (reversibility declared),
SC-007 (shape matches the committed ERD; zero rows lost).

Runs against a real PostgreSQL container. That is deliberate: native enums, a
``BEFORE UPDATE OR DELETE`` trigger, a partial unique index, and ``gen_random_uuid()``
all behave differently or not at all under emulation, and each one is load-bearing.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

pytestmark = pytest.mark.integration

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

EXPECTED_TABLES = {
    "tenant", "app_user", "audit_event", "deployment", "cloud_account",
    "resource", "rule", "finding", "sda", "resource_owner", "scan",
}


def test_all_revisions_apply_in_order_to_an_empty_database(
    clean_database: Engine, alembic_config
) -> None:
    """FR-025 / SC-007: 0001 -> head yields the full governance shape."""
    command.upgrade(alembic_config, "head")

    tables = set(inspect(clean_database).get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing after migration: {missing}"


def test_migration_chain_is_linear_and_complete(alembic_config) -> None:
    """A branch point means two revisions claim the same parent -- silent divergence."""
    script = ScriptDirectory.from_config(alembic_config)
    revisions = list(script.walk_revisions())
    assert len(revisions) == len(list(VERSIONS_DIR.glob("0*.py")))
    for rev in revisions:
        assert not isinstance(rev.down_revision, tuple), f"{rev.revision} is a merge point"


@pytest.mark.parametrize("path", sorted(VERSIONS_DIR.glob("0*.py")), ids=lambda p: p.stem)
def test_every_revision_declares_reversibility(path: Path) -> None:
    """FR-027: an irreversible migration must be identifiable BEFORE merge."""
    marker = re.search(r"^REVERSIBLE:\s*(yes|no)\s*$", path.read_text(), re.MULTILINE)
    assert marker, f"{path.name} does not declare 'REVERSIBLE: yes|no' in its docstring"


def test_the_single_tenant_is_seeded(clean_database: Engine, alembic_config) -> None:
    """Spec Assumptions: exactly one tenant in the MVP, schema tenant-aware throughout."""
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM tenant")).scalar_one()
    assert count == 1


def test_app_user_has_no_role_column_in_the_real_schema(
    clean_database: Engine, alembic_config
) -> None:
    """FR-031a, verified against the actual database rather than the model.

    A migration could add the column without the model knowing, so this checks what
    was really created.
    """
    command.upgrade(alembic_config, "head")
    columns = {c["name"] for c in inspect(clean_database).get_columns("app_user")}
    assert "role" not in columns


def test_prod_deployment_without_an_approver_is_rejected(
    clean_database: Engine, alembic_config
) -> None:
    """FR-017/FR-018 enforced by the database, not by application code."""
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(
                text(
                    "INSERT INTO deployment (environment, git_sha, triggered_by, status) "
                    "VALUES ('prod', 'abc123', 'ci', 'running')"
                )
            )
        assert "prod_requires_approver" in str(exc.value)


def test_dev_deployment_without_an_approver_is_allowed(
    clean_database: Engine, alembic_config
) -> None:
    """The inverse half: the constraint must not reject legitimate dev rows."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deployment (environment, git_sha, triggered_by, status) "
                "VALUES ('dev', 'abc123', 'ci', 'running')"
            )
        )


def test_migrations_lose_no_rows_on_a_populated_database(
    clean_database: Engine, alembic_config
) -> None:
    """FR-026 / SC-007 -- the assertion that only a real engine can make.

    Migrate to an intermediate revision, seed representative rows, then migrate to
    head and confirm every row survives.
    """
    command.upgrade(alembic_config, "0005")

    tenant_id = uuid.uuid4()
    account_id = uuid.uuid4()
    with clean_database.begin() as conn:
        conn.execute(
            text("INSERT INTO tenant (id, name) VALUES (:i, 'Seeded')"), {"i": tenant_id}
        )
        conn.execute(
            text(
                "INSERT INTO cloud_account (id, tenant_id, aws_account_id, alias, "
                "connection_mode, status) VALUES (:i, :t, '123456789012', 'seed', "
                "'local', 'verified')"
            ),
            {"i": account_id, "t": tenant_id},
        )
        for n in range(25):
            conn.execute(
                text(
                    "INSERT INTO resource (tenant_id, cloud_account_id, arn, "
                    "resource_type, service, region) VALUES (:t, :a, :arn, "
                    "'AWS::S3::Bucket', 's3', 'us-east-1')"
                ),
                {"t": tenant_id, "a": account_id, "arn": f"arn:aws:s3:::seed-{n}"},
            )

    command.upgrade(alembic_config, "head")

    with clean_database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM resource")).scalar_one() == 25
        assert conn.execute(
            text("SELECT count(*) FROM cloud_account WHERE id = :i"), {"i": account_id}
        ).scalar_one() == 1
        assert conn.execute(
            text("SELECT count(*) FROM tenant WHERE id = :i"), {"i": tenant_id}
        ).scalar_one() == 1


def test_reversible_revisions_actually_downgrade(clean_database: Engine, alembic_config) -> None:
    """A revision claiming REVERSIBLE: yes must survive a real downgrade.

    0003 is irreversible by design, so the reversible span below it is 0004..head.
    """
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0004")
    tables = set(inspect(clean_database).get_table_names())
    assert "scan" not in tables
    assert "deployment" in tables

    command.upgrade(alembic_config, "head")
    assert EXPECTED_TABLES <= set(inspect(clean_database).get_table_names())


def test_irreversible_revision_refuses_to_downgrade(
    clean_database: Engine, alembic_config
) -> None:
    """0003 declares REVERSIBLE: no and must behave like it.

    Downgrading would restore UPDATE/DELETE on audit_event and drop the immutability
    trigger -- undoing the control FR-029 exists to provide.
    """
    command.upgrade(alembic_config, "head")
    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(alembic_config, "0002")
