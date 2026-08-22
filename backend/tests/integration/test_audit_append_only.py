"""audit_event is genuinely append-only (FR-029, FR-029a).

Three layers protect it, and each is tested separately — because "the ORM does not
expose a delete" is worth very little if raw SQL can still do it, and a control that
has never been tested against the real engine is an assumption.

    layer 1  the application role holds INSERT/SELECT, not UPDATE/DELETE
    layer 2  a BEFORE UPDATE OR DELETE trigger raises
    layer 3  no ORM update or delete path exists

Layer 2 is the one that matters most: it applies to every caller including the schema
owner, so it holds where a grant does not.
"""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(clean_database: Engine, alembic_config) -> tuple[Engine, uuid.UUID, uuid.UUID]:
    """A migrated database with one tenant and one audit event."""
    command.upgrade(alembic_config, "head")
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    with clean_database.begin() as conn:
        conn.execute(
            text("INSERT INTO tenant (id, name) VALUES (:i, 'AuditTest')"), {"i": tenant_id}
        )
        conn.execute(
            text(
                "INSERT INTO audit_event (id, tenant_id, actor_label, action, target_type) "
                "VALUES (:i, :t, 'maintainer@example.com', 'account.register', 'cloud_account')"
            ),
            {"i": event_id, "t": tenant_id},
        )
    return clean_database, tenant_id, event_id


def test_insert_is_permitted(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """The inverse half: a table nothing can write to is not an audit trail."""
    engine, tenant_id, _ = seeded
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_event (tenant_id, actor_label, action, target_type) "
                "VALUES (:t, 'ci', 'deploy.approve', 'deployment')"
            ),
            {"t": tenant_id},
        )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_event")).scalar_one() == 2


def test_update_raises(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """FR-029: once written, a record can never be modified."""
    engine, _, event_id = seeded
    with engine.connect() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(
                text("UPDATE audit_event SET action = 'tampered' WHERE id = :i"), {"i": event_id}
            )
    assert "append-only" in str(exc.value).lower()


def test_delete_raises(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """FR-029: once written, a record can never be deleted."""
    engine, _, event_id = seeded
    with engine.connect() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(text("DELETE FROM audit_event WHERE id = :i"), {"i": event_id})
    assert "append-only" in str(exc.value).lower()


def test_bulk_delete_raises(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """A row-level trigger must fire per row, so an unqualified DELETE is caught too.

    This is the case a naive implementation misses: single-row deletes blocked, but
    `DELETE FROM audit_event` succeeding.
    """
    engine, _, _ = seeded
    with engine.connect() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(text("DELETE FROM audit_event"))
    assert "append-only" in str(exc.value).lower()


def test_the_record_survives_every_attempt(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """After all of the above, the original row is unchanged."""
    engine, _, event_id = seeded
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT action, actor_label FROM audit_event WHERE id = :i"), {"i": event_id}
        ).one()
    assert row.action == "account.register"
    assert row.actor_label == "maintainer@example.com"


def test_the_trigger_exists_on_the_real_table(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """Layer 2, verified structurally rather than inferred from behaviour."""
    engine, _, _ = seeded
    with engine.connect() as conn:
        triggers = (
            conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger t JOIN pg_class c ON t.tgrelid = c.oid "
                    "WHERE c.relname = 'audit_event' AND NOT t.tgisinternal"
                )
            )
            .scalars()
            .all()
        )
    assert "audit_event_no_update_or_delete" in triggers


def test_application_role_lacks_update_and_delete(
    seeded: tuple[Engine, uuid.UUID, uuid.UUID],
) -> None:
    """Layer 1: the grant itself, independent of the trigger."""
    engine, _, _ = seeded
    with engine.connect() as conn:
        granted = (
            conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = 'audit_event' AND grantee = 'cloudpulse_app'"
                )
            )
            .scalars()
            .all()
        )
    assert "INSERT" in granted and "SELECT" in granted
    assert "UPDATE" not in granted, "cloudpulse_app must not hold UPDATE on audit_event"
    assert "DELETE" not in granted, "cloudpulse_app must not hold DELETE on audit_event"


def test_no_expiry_mechanism_exists_on_audit_event(
    seeded: tuple[Engine, uuid.UUID, uuid.UUID],
) -> None:
    """FR-029a makes the ABSENCE of a retention mechanism the correct implementation.

    Audit events are retained indefinitely — no expiry, no purge job, and no retention
    setting that could remove them. This asserts the absence, so a later PR adding one
    fails rather than passing review as a tidy-up.
    """
    engine, _, _ = seeded
    with engine.connect() as conn:
        rules = (
            conn.execute(text("SELECT rulename FROM pg_rules WHERE tablename = 'audit_event'"))
            .scalars()
            .all()
        )
        partitions = conn.execute(
            text(
                "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON i.inhparent = c.oid "
                "WHERE c.relname = 'audit_event'"
            )
        ).scalar_one()
    assert not rules, f"unexpected rules on audit_event: {rules}"
    assert partitions == 0, "audit_event is partitioned; partition dropping would be an expiry path"


def test_audit_event_has_no_updated_at_column(seeded: tuple[Engine, uuid.UUID, uuid.UUID]) -> None:
    """A row that can never change has no meaningful update time."""
    engine, _, _ = seeded
    columns = {c["name"] for c in inspect(engine).get_columns("audit_event")}
    assert "updated_at" not in columns
