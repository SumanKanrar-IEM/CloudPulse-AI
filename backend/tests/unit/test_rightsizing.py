"""A recommendation carries its evidence, and is never made for a high or
variable resource (T048; spec 006, FR-023, S52).

The negative cases outnumber the positive one on purpose. FR-023's "MUST NOT
recommend downsizing a resource whose utilization is high or variable" is the
half that costs money when it fails -- an over-eager recommendation followed
is an outage -- so every reason `recommend` returns None is asserted
individually, and the boundary of each threshold is asserted from both sides.

Pure: the ladders are built inline rather than read from the JSON file, so a
price edit does not rewrite these expectations. The file's own shape is
checked once at the end.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.governance.rightsizing import (
    Candidate,
    ClassLadders,
    CpuHistory,
    load_class_ladders,
    low_cpu_percent,
    minimum_periods,
    recommend,
)

LADDERS = ClassLadders(
    ladders={"m5": ["m5.large", "m5.xlarge", "m5.2xlarge"]},
    hourly_usd={
        "m5.large": Decimal("0.096"),
        "m5.xlarge": Decimal("0.192"),
        "m5.2xlarge": Decimal("0.384"),
    },
)
FIRST, LAST = date(2026, 2, 1), date(2026, 2, 20)


def _history(*, days: int = 20, mean: str, peak: str) -> CpuHistory:
    return CpuHistory(
        days=days,
        mean_percent=Decimal(mean),
        peak_percent=Decimal(peak),
        first_day=FIRST,
        last_day=LAST,
    )


def _candidate(*, current_class: str | None = "m5.xlarge", history: CpuHistory | None) -> Candidate:
    return Candidate(
        resource_id=uuid.uuid4(),
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        resource_type="AWS::EC2::Instance",
        current_class=current_class,
        history=history,
    )


def _recommend(candidate: Candidate):  # type: ignore[no-untyped-def]
    return recommend(candidate, ladders=LADDERS, minimum=14, low=Decimal("20"))


# --- acceptance scenario 1: low, with evidence and a saving --------------------------


def test_a_persistently_low_resource_is_recommended_one_rung_down() -> None:
    rec = _recommend(_candidate(history=_history(mean="8.5", peak="19.0")))

    assert rec is not None
    assert (rec.current_class, rec.recommended_class) == ("m5.xlarge", "m5.large")
    # (0.192 - 0.096) * 730 = 70.08
    assert rec.estimated_monthly_saving_usd == Decimal("70.08")


def test_the_evidence_lets_a_reader_recompute_the_verdict() -> None:
    """Measurements *and* the thresholds they were judged against. Without the
    thresholds, "mean 8.5%" is a number; with them, it is a reason."""
    rec = _recommend(_candidate(history=_history(mean="8.5", peak="19.0")))

    assert rec is not None
    assert rec.evidence == {
        "metric": "cpu",
        "periods": 20,
        "period_first": "2026-02-01",
        "period_last": "2026-02-20",
        "mean_percent": "8.5",
        "peak_percent": "19.0",
        "low_threshold_percent": "20",
        "peak_threshold_percent": "40",
    }


# --- acceptance scenario 2: high or variable is never recommended down ---------------


def test_a_high_mean_is_not_recommended_down() -> None:
    assert _recommend(_candidate(history=_history(mean="55.0", peak="70.0"))) is None


def test_a_mean_exactly_at_the_threshold_is_not_low() -> None:
    assert _recommend(_candidate(history=_history(mean="20.0", peak="25.0"))) is None


def test_a_mean_just_under_the_threshold_is_low() -> None:
    assert _recommend(_candidate(history=_history(mean="19.9", peak="25.0"))) is not None


def test_a_low_mean_with_a_high_peak_is_variable_and_not_recommended_down() -> None:
    """Averages 8% and spikes to 90% nightly: provisioned for the spike. The
    case mean-only logic gets wrong, and the one that turns into an outage."""
    assert _recommend(_candidate(history=_history(mean="8.0", peak="90.0"))) is None


def test_a_peak_exactly_at_twice_the_threshold_is_variable() -> None:
    assert _recommend(_candidate(history=_history(mean="8.0", peak="40.0"))) is None


def test_a_peak_just_under_twice_the_threshold_is_not_variable() -> None:
    assert _recommend(_candidate(history=_history(mean="8.0", peak="39.9"))) is not None


# --- every other reason for None ------------------------------------------------------


def test_too_little_history_is_not_a_recommendation() -> None:
    assert _recommend(_candidate(history=_history(days=13, mean="8.0", peak="10.0"))) is None


def test_exactly_the_minimum_history_is_enough() -> None:
    assert _recommend(_candidate(history=_history(days=14, mean="8.0", peak="10.0"))) is not None


def test_no_history_is_not_a_recommendation() -> None:
    assert _recommend(_candidate(history=None)) is None


def test_no_known_class_is_not_a_recommendation() -> None:
    """A resource never enriched has no class in `detail`. Recommending a
    smaller class than an unknown one is a guess."""
    assert _recommend(_candidate(current_class=None, history=_history(mean="8", peak="10"))) is None


def test_the_smallest_class_has_nowhere_to_go() -> None:
    assert (
        _recommend(_candidate(current_class="m5.large", history=_history(mean="8", peak="10")))
        is None
    )


def test_a_class_the_ladder_does_not_know_is_not_a_recommendation() -> None:
    assert (
        _recommend(_candidate(current_class="z9.mega", history=_history(mean="8", peak="10")))
        is None
    )


def test_a_class_with_no_price_is_not_a_recommendation() -> None:
    """A rung without a price could still be named, but FR-023 requires the
    saving beside it, and a saving of "unknown" is not a saving."""
    unpriced = ClassLadders(ladders={"m5": ["m5.large", "m5.xlarge"]}, hourly_usd={})
    assert (
        recommend(
            _candidate(history=_history(mean="8", peak="10")),
            ladders=unpriced,
            minimum=14,
            low=Decimal("20"),
        )
        is None
    )


# --- thresholds from the environment, R-612 -------------------------------------------


def test_thresholds_read_from_the_environment_with_safe_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDPULSE_RIGHTSIZING_MIN_PERIODS", "21")
    monkeypatch.setenv("CLOUDPULSE_RIGHTSIZING_LOW_CPU_PERCENT", "15")
    assert (minimum_periods(), low_cpu_percent()) == (21, Decimal("15"))

    for bad in ("0", "-1", "abc", ""):
        monkeypatch.setenv("CLOUDPULSE_RIGHTSIZING_MIN_PERIODS", bad)
        assert minimum_periods() == 14, bad
    for bad in ("0", "100", "150", "low", ""):
        monkeypatch.setenv("CLOUDPULSE_RIGHTSIZING_LOW_CPU_PERCENT", bad)
        assert low_cpu_percent() == Decimal("20"), bad


# --- the shipped data file ----------------------------------------------------------------


def test_every_class_on_a_shipped_ladder_has_a_price() -> None:
    """A rung with no price silently produces no recommendation (above). That
    is the right runtime behaviour and the wrong thing to ship, so the file is
    checked whole."""
    ladders = load_class_ladders()
    for family, rungs in ladders.ladders.items():
        for rung in rungs:
            assert rung in ladders.hourly_usd, f"{family}: {rung} has no price"
        # Smallest first, or step_down steps up.
        prices = [ladders.hourly_usd[r] for r in rungs]
        assert prices == sorted(prices), family
