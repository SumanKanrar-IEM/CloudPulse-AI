"""IAM hygiene classification, without AWS or a database (T042; S56, FR-019,
FR-020).

FR-020 -- "MUST NOT flag an actively-used role, user, or key" -- is the
constraint worth the most test surface here, because it is the failure mode
that matters: a false flag asks a human to delete something that is in use.
Every rule below is written to fail toward *not* flagging, and each of those
escape hatches is pinned by its own test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.governance.iam_hygiene import (
    MIN_AGE_BEFORE_FLAGGING,
    UNUSED_AFTER,
    Candidate,
    evidence_for,
    is_unused,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)
LONG_AGO = NOW - UNUSED_AFTER - timedelta(days=1)
RECENTLY = NOW - timedelta(days=3)
OLD_ENOUGH = NOW - MIN_AGE_BEFORE_FLAGGING - timedelta(days=1)


def _candidate(**overrides: object) -> Candidate:
    base: dict[str, object] = {
        "principal_type": "role",
        "identifier": "arn:aws:iam::123456789012:role/example",
        "name": "example",
        "created_at": OLD_ENOUGH,
        "last_used_at": None,
    }
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]


# --- FR-020: never flag something in use -------------------------------------------


def test_a_recently_used_principal_is_never_flagged() -> None:
    assert is_unused(_candidate(last_used_at=RECENTLY), now=NOW) is False


def test_a_principal_used_on_the_boundary_is_not_flagged() -> None:
    """Exactly at the window edge counts as used. FR-020 is a hard "must not",
    so the boundary resolves in favour of not flagging."""
    assert is_unused(_candidate(last_used_at=NOW - UNUSED_AFTER), now=NOW) is False


def test_a_recently_used_principal_is_not_flagged_even_when_ancient() -> None:
    """Age never overrides evidence of use -- the used check runs first
    precisely so no later rule can promote an active principal to unused."""
    candidate = _candidate(created_at=datetime(2019, 1, 1, tzinfo=UTC), last_used_at=RECENTLY)
    assert is_unused(candidate, now=NOW) is False


# --- what does get flagged ---------------------------------------------------------


def test_a_principal_unused_for_longer_than_the_window_is_flagged() -> None:
    assert is_unused(_candidate(last_used_at=LONG_AGO), now=NOW) is True


def test_a_never_used_principal_old_enough_to_judge_is_flagged() -> None:
    assert is_unused(_candidate(created_at=OLD_ENOUGH, last_used_at=None), now=NOW) is True


# --- the escape hatches, each one a deliberate refusal to guess --------------------


def test_a_young_never_used_principal_is_not_flagged() -> None:
    """A role created last week with no recorded use is new, not abandoned."""
    candidate = _candidate(created_at=NOW - timedelta(days=7), last_used_at=None)
    assert is_unused(candidate, now=NOW) is False


def test_a_principal_with_no_creation_date_is_not_flagged() -> None:
    """The age test cannot be applied, and guessing would risk exactly the
    false positive FR-020 forbids."""
    assert is_unused(_candidate(created_at=None, last_used_at=None), now=NOW) is False


def test_a_naive_timestamp_is_compared_rather_than_raising() -> None:
    """boto3 returns tz-aware datetimes, but a fixture or replayed payload may
    not -- and one odd record must not fail the whole account's run."""
    naive = _candidate(last_used_at=LONG_AGO.replace(tzinfo=None))
    assert is_unused(naive, now=NOW) is True


@pytest.mark.parametrize("principal_type", ["role", "user", "access_key"])
def test_every_principal_type_classifies_the_same_way(principal_type: str) -> None:
    """FR-019 names all three, and none of them gets a looser rule."""
    used = _candidate(principal_type=principal_type, last_used_at=RECENTLY)
    unused = _candidate(principal_type=principal_type, last_used_at=LONG_AGO)
    assert is_unused(used, now=NOW) is False
    assert is_unused(unused, now=NOW) is True


# --- evidence ----------------------------------------------------------------------


def test_evidence_records_why_we_believe_it_is_unused() -> None:
    """A recommendation without its basis is a guess presented as a fact, and
    this one asks a human to delete something."""
    evidence = evidence_for(_candidate(last_used_at=LONG_AGO), now=NOW)
    assert evidence["lastUsedAt"] == LONG_AGO.isoformat()
    assert evidence["daysSinceLastUse"] == (NOW - LONG_AGO).days
    assert evidence["unusedAfterDays"] == UNUSED_AFTER.days


def test_evidence_for_a_never_used_principal_says_so_rather_than_faking_a_date() -> None:
    evidence = evidence_for(_candidate(last_used_at=None, reason="never used"), now=NOW)
    assert evidence["lastUsedAt"] is None
    assert evidence["daysSinceLastUse"] is None
    assert evidence["reason"] == "never used"
