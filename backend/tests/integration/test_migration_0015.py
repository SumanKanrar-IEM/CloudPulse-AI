"""Migration 0015 applies, reverses, and enforces what it claims (T005; spec
006, FR-005, FR-006a, FR-019, FR-020).

Against a real PostgreSQL, because every property worth testing here is one an
emulation would let slide: native enum membership, partial unique indexes, and
CHECK constraints that encode requirements rather than conventions.

Two deliberate choices in how these assert:

* **`IntegrityError`, never bare `Exception`.** A broad catch would pass on a
  typo'd statement raising `ProgrammingError`, so the test would prove the
  constraint works while actually proving the SQL was wrong.
* **Enum membership asserted exactly, not with `<=`.** Migration 0014 had to
  perform a rename-create-recast-drop to remove `withheld_bounced`, which
  shipped in 0012 with no code path able to write it. An exact assertion makes a
  speculative value fail here rather than survive into someone else's migration.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

EXPECTED_ENUMS: dict[str, set[str]] = {
    "agent_capability": {"digest", "suggester", "advisor", "narrator"},
    "agent_run_status": {"succeeded", "truncated", "failed"},
    "grounding_reference_kind": {"arn", "resource_id", "finding_id", "sda", "figure"},
    "coverage_proposal_kind": {"rule_extension", "enable_existing_enricher"},
    "proposal_review_state": {"pending", "accepted", "rejected"},
    "resource_metric_kind": {"cpu", "memory", "network", "storage"},
    "forecast_kind": {"spend", "capacity"},
}

NEW_TABLES = (
    "agent_run",
    "insight_digest",
    "grounding_rejection",
    "coverage_proposal",
    "resource_metric",
    "forecast",
    "rightsizing_recommendation",
)

_INSERT_RUN = text(
    "INSERT INTO agent_run (tenant_id, capability, definition_hash, status, cost_units, "
    "cost_cap_units, failure_reason) "
    "VALUES (:t, 'digest', 'abc', :status, 1, 10, :reason) RETURNING id"
)
_INSERT_DIGEST = text(
    "INSERT INTO insight_digest (tenant_id, agent_run_id, period_date, content, is_empty) "
    "VALUES (:t, :r, DATE '2026-09-07', '{}'::jsonb, false)"
)
_INSERT_METRIC = text(
    "INSERT INTO resource_metric (tenant_id, resource_id, metric, period_start, value, "
    "is_unavailable) VALUES (:t, :r, 'cpu', :period, :value, :unavailable)"
)
_INSERT_RIGHTSIZING = text(
    "INSERT INTO rightsizing_recommendation (tenant_id, resource_id, current_class, "
    "recommended_class, evidence, estimated_monthly_saving_usd, superseded_at) "
    "VALUES (:t, :r, 'm5.large', 'm5.small', '{}'::jsonb, 10.00, :superseded)"
)
_INSERT_PROPOSAL = text(
    "INSERT INTO coverage_proposal (tenant_id, agent_run_id, proposal_kind, resource_type, "
    "evidence_account_id, proposed_change, review_state, decided_at) "
    "VALUES (:t, :r, 'rule_extension', 'AWS::SQS::Queue', :a, '{}'::jsonb, :state, :decided)"
)
_INSERT_ACCOUNT = text(
    "INSERT INTO cloud_account (tenant_id, aws_account_id, alias, connection_mode, scan_regions, "
    "status) VALUES (:t, '123456789012', 'a', 'local', ARRAY['us-east-1'], 'verified') "
    "RETURNING id"
)
_INSERT_RESOURCE = text(
    "INSERT INTO resource (tenant_id, cloud_account_id, arn, resource_type, service, region, tags) "
    "VALUES (:t, :a, 'arn:aws:ec2:::i-1', 'AWS::EC2::Instance', 'ec2', 'us-east-1', '{}'::jsonb) "
    "RETURNING id"
)


def _enum_values(conn: Any, type_name: str) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = :n"
            ),
            {"n": type_name},
        )
        .scalars()
        .all()
    )


def _tables(conn: Any) -> set[str]:
    return set(
        conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        .scalars()
        .all()
    )


def _tenant_id(conn: Any) -> uuid.UUID:
    return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


def _run(conn: Any, tenant_id: uuid.UUID, status: str = "succeeded") -> uuid.UUID:
    reason = "model unreachable" if status == "failed" else None
    return uuid.UUID(
        str(
            conn.execute(
                _INSERT_RUN, {"t": tenant_id, "status": status, "reason": reason}
            ).scalar_one()
        )
    )


def _account_and_resource(conn: Any, tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    account = conn.execute(_INSERT_ACCOUNT, {"t": tenant_id}).scalar_one()
    resource = conn.execute(_INSERT_RESOURCE, {"t": tenant_id, "a": account}).scalar_one()
    return account, resource


def test_every_new_table_exists_after_upgrade(clean_database: Engine, alembic_config: Any) -> None:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        assert set(NEW_TABLES) <= _tables(conn)


@pytest.mark.parametrize(("type_name", "values"), sorted(EXPECTED_ENUMS.items()))
def test_each_enum_holds_exactly_its_documented_values(
    clean_database: Engine, alembic_config: Any, type_name: str, values: set[str]
) -> None:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        assert _enum_values(conn, type_name) == values


def test_coverage_proposal_kind_has_no_third_value(
    clean_database: Engine, alembic_config: Any
) -> None:
    """R-603, guarded rather than trusted: a resource type with no existing
    enricher cannot be proposed, because accepting it could not take effect
    without a code change (FR-017). A third enum value would be the first step
    toward offering one anyway."""
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        assert len(_enum_values(conn, "coverage_proposal_kind")) == 2


def test_the_migration_downgrades_cleanly(clean_database: Engine, alembic_config: Any) -> None:
    """0015 declares REVERSIBLE: yes. An additive migration is exactly where that
    claim is cheap to make and easy to get wrong -- a dropped table whose enum
    type survives makes the next upgrade fail on CREATE TYPE."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0014")
    with clean_database.connect() as conn:
        assert not (set(NEW_TABLES) & _tables(conn))
        for type_name in EXPECTED_ENUMS:
            assert _enum_values(conn, type_name) == set(), f"{type_name} survived downgrade"
    command.upgrade(alembic_config, "head")


def test_a_failed_run_requires_a_reason(clean_database: Engine, alembic_config: Any) -> None:
    """`ck_agent_run_failure_reason_shape`. An unexplained failure is useless for
    diagnosing FR-007a's unreachable-model case."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        _run(conn, tenant_id, "failed")  # reason supplied: accepted

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(_INSERT_RUN, {"t": tenant_id, "status": "failed", "reason": None})


def test_a_succeeded_run_may_not_carry_a_failure_reason(
    clean_database: Engine, alembic_config: Any
) -> None:
    """The other half of the same constraint: a reason on a success is a
    contradiction the database should refuse to store."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(_INSERT_RUN, {"t": tenant_id, "status": "succeeded", "reason": "why?"})


def test_one_digest_per_tenant_per_day(clean_database: Engine, alembic_config: Any) -> None:
    """Two overlapping runs must not both leave a digest behind (Edge Cases)."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        run = _run(conn, tenant_id)
        conn.execute(_INSERT_DIGEST, {"t": tenant_id, "r": run})

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(_INSERT_DIGEST, {"t": tenant_id, "r": run})


def test_a_metric_is_either_unknown_or_valued(clean_database: Engine, alembic_config: Any) -> None:
    """FR-020's whole point, enforced at the database: a missing measurement is
    recorded as missing, never as a zero that would drag an average down and
    understate utilization."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        _, resource = _account_and_resource(conn, tenant_id)
        base = {"t": tenant_id, "r": resource}
        conn.execute(
            _INSERT_METRIC,
            {**base, "period": "2026-09-01T00:00:00Z", "value": 12.5, "unavailable": False},
        )
        conn.execute(
            _INSERT_METRIC,
            {**base, "period": "2026-09-02T00:00:00Z", "value": None, "unavailable": True},
        )

    for value, unavailable in ((12.5, True), (None, False)):
        with clean_database.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(
                _INSERT_METRIC,
                {
                    "t": tenant_id,
                    "r": resource,
                    "period": "2026-09-03T00:00:00Z",
                    "value": value,
                    "unavailable": unavailable,
                },
            )


def test_a_period_is_collected_once(clean_database: Engine, alembic_config: Any) -> None:
    """FR-019: a re-run updates rather than appends."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        _, resource = _account_and_resource(conn, tenant_id)
        row = {
            "t": tenant_id,
            "r": resource,
            "period": "2026-09-01T00:00:00Z",
            "value": 1.0,
            "unavailable": False,
        }
        conn.execute(_INSERT_METRIC, row)

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(_INSERT_METRIC, row)


def test_only_one_live_rightsizing_recommendation_per_resource(
    clean_database: Engine, alembic_config: Any
) -> None:
    """The partial index: superseded rows stay as history, but a resource never
    carries two live recommendations that could contradict each other."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        _, resource = _account_and_resource(conn, tenant_id)
        base = {"t": tenant_id, "r": resource}
        conn.execute(_INSERT_RIGHTSIZING, {**base, "superseded": "2026-09-01T00:00:00Z"})
        conn.execute(_INSERT_RIGHTSIZING, {**base, "superseded": None})

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(_INSERT_RIGHTSIZING, {"t": tenant_id, "r": resource, "superseded": None})


def test_the_advisor_cannot_raise_the_same_pending_proposal_twice(
    clean_database: Engine, alembic_config: Any
) -> None:
    """Partial unique index on pending only -- a rejected proposal stays as
    history and does not block a later one for the same resource type."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        run = _run(conn, tenant_id)
        account, _ = _account_and_resource(conn, tenant_id)
        base = {"t": tenant_id, "r": run, "a": account}
        conn.execute(
            _INSERT_PROPOSAL,
            {**base, "state": "rejected", "decided": "2026-09-01T00:00:00Z"},
        )
        conn.execute(_INSERT_PROPOSAL, {**base, "state": "pending", "decided": None})

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            _INSERT_PROPOSAL,
            {"t": tenant_id, "r": run, "a": account, "state": "pending", "decided": None},
        )


def test_a_pending_proposal_has_no_decision_timestamp(
    clean_database: Engine, alembic_config: Any
) -> None:
    """`ck_coverage_proposal_decision_shape`: FR-016's "no proposal takes effect
    without explicit acceptance" is only auditable if pending and decided are
    distinguishable at the row level."""
    command.upgrade(alembic_config, "head")
    with clean_database.begin() as conn:
        tenant_id = _tenant_id(conn)
        run = _run(conn, tenant_id)
        account, _ = _account_and_resource(conn, tenant_id)

    with clean_database.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            _INSERT_PROPOSAL,
            {
                "t": tenant_id,
                "r": run,
                "a": account,
                "state": "pending",
                "decided": "2026-09-01T00:00:00Z",
            },
        )
