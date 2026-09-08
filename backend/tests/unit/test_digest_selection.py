"""Deterministic selection of the findings a digest covers (T013; spec 006,
FR-008a, research.md R-606a).

The platform ranks; the agent explains. Ranking is a scoring decision and
Principle IV reserves scoring for the deterministic core — and an agent-chosen
ranking would be unverifiable anyway, since the grounding validator can confirm
a finding exists but not that it was genuinely the most urgent.

Pure, so "the same finding set always selects the same digest set" is provable
without a database. That reproducibility is the requirement, not an
implementation nicety.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.governance.digest import (
    DIGEST_FINDING_LIMIT,
    DigestCandidate,
    NotabilityThresholds,
    is_compliance_move_notable,
    is_spend_change_notable,
    notability_thresholds,
    select_digest_findings,
)
from app.models.enums import FindingSeverity

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def _candidate(
    severity: FindingSeverity = FindingSeverity.MEDIUM,
    *,
    escalated: bool = False,
    age_days: int = 1,
    label: str = "",
) -> DigestCandidate:
    return DigestCandidate(
        finding_id=uuid.uuid4(),
        severity=severity,
        escalated=escalated,
        opened_at=NOW - timedelta(days=age_days),
        label=label or f"{severity.value}-{age_days}d",
    )


def test_severity_outranks_everything_else() -> None:
    """A fresh critical beats an old escalated low. Severity is the first key
    because it is the one an operator acts on first."""
    old_escalated_low = _candidate(FindingSeverity.LOW, escalated=True, age_days=90)
    fresh_critical = _candidate(FindingSeverity.CRITICAL, age_days=0)

    selected = select_digest_findings([old_escalated_low, fresh_critical])

    assert selected[0] is fresh_critical


def test_severity_orders_by_rank_not_alphabetically() -> None:
    """The guard on the obvious bug: sorting the enum's string values would give
    critical < high < low < medium, putting `low` above `medium`."""
    order = [
        FindingSeverity.LOW,
        FindingSeverity.MEDIUM,
        FindingSeverity.HIGH,
        FindingSeverity.CRITICAL,
    ]
    candidates = [_candidate(s) for s in order]

    selected = select_digest_findings(candidates)

    assert [c.severity for c in selected] == list(reversed(order))


def test_escalation_breaks_a_severity_tie() -> None:
    """FR-008a's second key: among equals, the one already escalated has been
    unattended longest through the cadence."""
    plain = _candidate(FindingSeverity.HIGH, escalated=False, age_days=1)
    escalated = _candidate(FindingSeverity.HIGH, escalated=True, age_days=1)

    selected = select_digest_findings([plain, escalated])

    assert selected[0] is escalated


def test_age_breaks_a_severity_and_escalation_tie() -> None:
    """Oldest first: a finding open for a month is a worse fact than one opened
    yesterday, all else equal."""
    newer = _candidate(FindingSeverity.HIGH, age_days=1)
    older = _candidate(FindingSeverity.HIGH, age_days=30)

    selected = select_digest_findings([newer, older])

    assert selected[0] is older


def test_the_full_key_order_is_severity_then_escalation_then_age() -> None:
    """All three keys exercised together, since each pairwise test alone would
    pass under several wrong orderings."""
    expected = [
        _candidate(FindingSeverity.CRITICAL, escalated=False, age_days=1, label="crit"),
        _candidate(FindingSeverity.HIGH, escalated=True, age_days=1, label="high-esc"),
        _candidate(FindingSeverity.HIGH, escalated=False, age_days=30, label="high-old"),
        _candidate(FindingSeverity.HIGH, escalated=False, age_days=2, label="high-new"),
        _candidate(FindingSeverity.LOW, escalated=True, age_days=99, label="low"),
    ]
    shuffled = [expected[3], expected[0], expected[4], expected[2], expected[1]]

    assert [c.label for c in select_digest_findings(shuffled)] == [c.label for c in expected]


def test_the_same_finding_set_always_selects_the_same_digest_set() -> None:
    """FR-008a's reproducibility clause. Two runs over the same input that
    disagreed would make the digest unexplainable."""
    candidates = [_candidate(FindingSeverity.HIGH, age_days=n, label=f"f{n}") for n in range(10)]
    first = [c.label for c in select_digest_findings(candidates)]
    second = [c.label for c in select_digest_findings(list(reversed(candidates)))]
    assert first == second


def test_selection_is_capped_so_a_digest_stays_readable() -> None:
    """A digest naming 400 findings answers "what should I care about today?"
    no better than the findings list it exists to summarise."""
    candidates = [_candidate(FindingSeverity.HIGH, age_days=n) for n in range(50)]
    assert len(select_digest_findings(candidates)) == DIGEST_FINDING_LIMIT


def test_an_empty_finding_set_selects_nothing_rather_than_erroring() -> None:
    """FR-010's "nothing notable" case reaches here as an empty list."""
    assert select_digest_findings([]) == []


def test_the_input_list_is_not_mutated() -> None:
    """The caller may still need its own ordering — sorting in place would be an
    invisible side effect on a shared list."""
    candidates = [_candidate(FindingSeverity.LOW), _candidate(FindingSeverity.CRITICAL)]
    before = list(candidates)
    select_digest_findings(candidates)
    assert candidates == before


@pytest.mark.parametrize("severity", list(FindingSeverity))
def test_every_severity_has_a_rank(severity: FindingSeverity) -> None:
    """A severity added later must be ranked deliberately rather than sorting to
    an accidental position."""
    assert select_digest_findings([_candidate(severity)])


# --- notability (FR-008b) ----------------------------------------------------------
#
# "Notable" is a platform-computed threshold, not the agent's judgement. Leaving
# it to the model would make FR-010's nothing-notable branch unverifiable: the
# grounding validator can confirm a figure is real, but not that omitting it was
# correct.


def _thresholds(
    percent: str = "20", absolute: str = "50", points: str = "5"
) -> NotabilityThresholds:
    return NotabilityThresholds(
        spend_percent=Decimal(percent),
        spend_absolute_usd=Decimal(absolute),
        compliance_points=Decimal(points),
    )


def test_a_large_absolute_move_is_notable_even_at_a_small_percentage() -> None:
    """$500 on a $10,000 project is 5% — under the percentage bar, over the
    absolute one. A percentage-only rule would stay silent on it."""
    assert is_spend_change_notable(Decimal("10000"), Decimal("10500"), _thresholds())


def test_a_large_percentage_move_is_notable_even_at_a_small_absolute() -> None:
    """$40 on a $100 project is 40% — under the absolute bar, over the
    percentage one. An absolute-only rule would stay silent on it."""
    assert is_spend_change_notable(Decimal("100"), Decimal("140"), _thresholds())


def test_a_move_under_both_bars_is_not_notable() -> None:
    assert not is_spend_change_notable(Decimal("10000"), Decimal("10010"), _thresholds())


def test_a_decrease_is_as_notable_as_an_increase() -> None:
    """Spend halving is a fact worth reporting — often it means something broke."""
    assert is_spend_change_notable(Decimal("1000"), Decimal("400"), _thresholds())


def test_a_projects_first_spend_is_notable_only_on_the_absolute_bar() -> None:
    """There is no baseline to take a percentage of. Treating it as an infinite
    increase would make every new project's first day notable."""
    assert not is_spend_change_notable(Decimal("0"), Decimal("10"), _thresholds())
    assert is_spend_change_notable(Decimal("0"), Decimal("500"), _thresholds())


def test_a_move_exactly_on_a_bar_counts_as_notable() -> None:
    """At the threshold is over it — the same reading FR-004's cost cap uses, so
    the two do not disagree about what a boundary means."""
    assert is_spend_change_notable(Decimal("1000"), Decimal("1050"), _thresholds())


def test_a_compliance_move_is_notable_in_either_direction() -> None:
    """A score that improved sharply is as worth reporting as one that fell. A
    digest that only ever delivers bad news gets read as noise."""
    assert is_compliance_move_notable(Decimal("70"), Decimal("78"), _thresholds())
    assert is_compliance_move_notable(Decimal("78"), Decimal("70"), _thresholds())
    assert not is_compliance_move_notable(Decimal("70"), Decimal("72"), _thresholds())


@pytest.mark.parametrize("bad", ["", "not-a-number", "0", "-5"])
def test_an_unusable_threshold_falls_back_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """R-612: a bad configuration value must not take a scheduled digest run
    down. A threshold of zero would make every move notable, which is the same
    as having no threshold at all."""
    monkeypatch.setenv("CLOUDPULSE_DIGEST_SPEND_NOTABLE_USD", bad)
    assert notability_thresholds().spend_absolute_usd == Decimal("50")


def test_a_configured_threshold_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDPULSE_DIGEST_SPEND_NOTABLE_USD", "250")
    assert notability_thresholds().spend_absolute_usd == Decimal("250")
