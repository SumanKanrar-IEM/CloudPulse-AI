"""Utilization classification, without a database (T038; S54, S55, FR-018,
research.md R-509).

All of it is pure on purpose: R-509 computes utilization from
`resource.state`, which spec 002 already persisted, so this whole capability
makes no AWS call and needs no fixture to prove. That is also why User Story 6
is the one story in this spec that stays live-verifiable regardless of R-407
and R-511 (see T051).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.governance.utilization import Utilization, classify, is_idle


def _rows(*triples: tuple[str | None, str | None, str | None]) -> list[Any]:
    return list(triples)


# --- the NULL rule, which is the whole scope claim ---------------------------------


def test_a_resource_with_no_known_state_is_counted_in_neither_half() -> None:
    """R-509's central decision. `state` is only ever populated by the
    enrichment functions -- `connectors/aws.py` defaults it to None at
    discovery -- so most resources have none. Counting them idle would
    systematically understate utilization for every account holding
    unenriched types; counting them used would overstate it."""
    result = classify(
        [
            ("ec2", "AWS::EC2::Instance", "running"),
            ("s3", "AWS::S3::Bucket", None),
            ("lambda", "AWS::Lambda::Function", None),
        ]
    )
    assert result == Utilization(used=1, provisioned=1)
    assert result.percent == 100.0


def test_nothing_measurable_reports_not_enough_data_rather_than_a_number() -> None:
    """An explicit "not enough data" state, not a divide-by-zero and not a
    misleading 0% or 100%."""
    result = classify([("s3", "AWS::S3::Bucket", None)])
    assert result.has_enough_data is False
    assert result.percent is None


def test_an_empty_account_reports_not_enough_data() -> None:
    result = classify([])
    assert result.has_enough_data is False
    assert result.percent is None


# --- classification ----------------------------------------------------------------


@pytest.mark.parametrize(
    "state", ["stopped", "stopping", "terminated", "deleting", "shutting-down"]
)
def test_the_known_idle_states_are_idle(state: str) -> None:
    assert is_idle("ec2", "AWS::EC2::Instance", state) is True


@pytest.mark.parametrize("state", ["running", "pending", "available", "active"])
def test_every_other_known_state_counts_as_used(state: str) -> None:
    """R-509: the idle set is the documented exception; anything else known and
    non-null is used."""
    assert is_idle("ec2", "AWS::EC2::Instance", state) is False


def test_classification_is_case_insensitive() -> None:
    """AWS is not consistent about casing across services, and a state string
    that failed to match would silently count an idle resource as used."""
    assert is_idle("ec2", "AWS::EC2::Instance", "STOPPED") is True
    assert is_idle("ec2", "AWS::EC2::Instance", "Stopped") is True


def test_an_unattached_volume_is_idle_not_used() -> None:
    """The one row in the table that inverts the intuitive reading: an EBS
    volume in state `available` is attached to nothing. Reading "available" as
    healthy would count every orphaned volume -- exactly the waste this feature
    exists to surface -- as utilized."""
    assert is_idle("ec2", "AWS::EC2::Volume", "available") is True
    assert is_idle("ec2", "AWS::EC2::Volume", "in-use") is False


def test_an_unknown_service_falls_back_to_the_default_idle_set() -> None:
    """A service this table has no entry for still classifies, rather than
    treating every one of its resources as used by default."""
    assert is_idle("some-future-service", "AWS::Future::Thing", "stopped") is True
    assert is_idle("some-future-service", "AWS::Future::Thing", "running") is False


# --- the ratio ---------------------------------------------------------------------


def test_a_mixed_account_reports_the_ratio_over_known_states_only() -> None:
    result = classify(
        [
            ("ec2", "AWS::EC2::Instance", "running"),
            ("ec2", "AWS::EC2::Instance", "running"),
            ("ec2", "AWS::EC2::Instance", "stopped"),
            ("ec2", "AWS::EC2::Volume", "available"),  # unattached: idle
            ("s3", "AWS::S3::Bucket", None),  # excluded entirely
        ]
    )
    assert result == Utilization(used=2, provisioned=4)
    assert result.percent == 50.0


def test_the_counts_travel_with_the_percentage() -> None:
    """FR-018's number means nothing without the population it was measured
    against, and R-509 requires the scope to be stated rather than implied."""
    result = classify([("ec2", "AWS::EC2::Instance", "running")])
    assert (result.used, result.provisioned) == (1, 1)


def test_the_percentage_is_rounded_to_one_decimal() -> None:
    result = classify(
        [("ec2", "AWS::EC2::Instance", "running")] * 1
        + [("ec2", "AWS::EC2::Instance", "stopped")] * 2
    )
    assert result.percent == 33.3
