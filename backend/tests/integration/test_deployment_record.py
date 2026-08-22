"""A prod deployment cannot be recorded without an approver (FR-017, FR-018).

Enforced by a database CHECK constraint, not by application code — so these tests go
through raw SQL as well as the module. An application-level check is only as good as the
last developer who remembered it; a constraint holds against any code path, including
ones written by a later spec.

FR-021's third condition is also tested here: a failed deployment must be recorded as
`failed`, not left `running`. A row stuck in `running` is indistinguishable from one
still in progress, which makes the record useless exactly when someone needs it.
"""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated(clean_database: Engine, alembic_config) -> Engine:
    command.upgrade(alembic_config, "head")
    return clean_database


def test_prod_without_approver_is_refused_by_the_database(migrated: Engine) -> None:
    """FR-017/FR-018 at the constraint level."""
    with migrated.connect() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(
                text(
                    "INSERT INTO deployment (environment, git_sha, triggered_by, status) "
                    "VALUES ('prod', 'abc1234', 'ci-runner', 'running')"
                )
            )
    assert "prod_requires_approver" in str(exc.value)


def test_prod_with_only_approved_by_is_still_refused(migrated: Engine) -> None:
    """Both fields are required. A name with no timestamp is not an audit trail."""
    with migrated.connect() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(
                text(
                    "INSERT INTO deployment (environment, git_sha, triggered_by, status, "
                    "approved_by) VALUES ('prod', 'abc1234', 'ci', 'running', 'someone')"
                )
            )
    assert "prod_requires_approver" in str(exc.value)


def test_prod_with_a_full_approval_is_accepted(migrated: Engine) -> None:
    """The inverse half: the constraint must not block a legitimate prod deploy."""
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deployment (environment, git_sha, triggered_by, status, "
                "approved_by, approved_at) VALUES ('prod', 'abc1234', 'ci', 'running', "
                "'maintainer', now())"
            )
        )
    with migrated.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM deployment WHERE environment = 'prod'")
        ).scalar_one() == 1


def test_dev_needs_no_approver(migrated: Engine) -> None:
    """FR-015: dev deploys automatically, with no human in the loop."""
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deployment (environment, git_sha, triggered_by, status) "
                "VALUES ('dev', 'abc1234', 'ci', 'running')"
            )
        )


def test_self_approval_is_recorded_as_such(migrated: Engine) -> None:
    """Spec Assumptions: with one maintainer every prod approval is a self-approval.

    Permitted — but the record has to say so, or the merge history overstates the
    strength of the gate.
    """
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deployment (environment, git_sha, triggered_by, status, "
                "approved_by, approved_at, self_approved) VALUES ('prod', 'abc', "
                "'maintainer', 'running', 'maintainer', now(), true)"
            )
        )
    with migrated.connect() as conn:
        row = conn.execute(
            text("SELECT triggered_by, approved_by, self_approved FROM deployment")
        ).one()
    assert row.self_approved is True
    assert row.triggered_by == row.approved_by


def test_a_deployment_records_everything_fr023_names(migrated: Engine) -> None:
    """FR-023: what was deployed, to which environment, when, and by whom."""
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deployment (environment, git_sha, triggered_by, status, "
                "migration_revision) VALUES ('dev', 'deadbee', 'maintainer', 'succeeded', "
                "'0008')"
            )
        )
    with migrated.connect() as conn:
        row = conn.execute(
            text(
                "SELECT environment, git_sha, triggered_by, status, migration_revision, "
                "started_at FROM deployment"
            )
        ).one()
    assert row.git_sha == "deadbee"
    assert row.environment == "dev"
    assert row.triggered_by == "maintainer"
    assert row.migration_revision == "0008"
    assert row.started_at is not None


def test_a_failed_deployment_is_recorded_as_failed(migrated: Engine) -> None:
    """FR-021 condition 3: not left in `running`.

    A row stuck in `running` forever is indistinguishable from one still in progress.
    """
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deployment (id, environment, git_sha, triggered_by, status) "
                "VALUES (:i, 'dev', 'abc', 'ci', 'running')"
            ),
            {"i": (dep_id := uuid.uuid4())},
        )
        conn.execute(
            text("UPDATE deployment SET status = 'failed', finished_at = now() WHERE id = :i"),
            {"i": dep_id},
        )
    with migrated.connect() as conn:
        row = conn.execute(
            text("SELECT status, finished_at FROM deployment WHERE id = :i"), {"i": dep_id}
        ).one()
    assert row.status == "failed"
    assert row.finished_at is not None


def test_deployment_is_not_tenant_scoped(migrated: Engine) -> None:
    """The one deliberate FR-030 exception, asserted so it does not read as an
    oversight — and so nobody 'fixes' it by adding a tenant_id."""
    from sqlalchemy import inspect

    columns = {c["name"] for c in inspect(migrated).get_columns("deployment")}
    assert "tenant_id" not in columns
