"""Alarm thresholds and evaluation windows (S7, FR-050, FR-052, FR-053). **P2.**

Parses the Terraform rather than a live environment, so the values are pinned at review
time. FR-050 originally said only "agreed threshold" — these tests are what stop that
staying vague, and what makes a later change to a threshold a visible, reviewed act.

The `treat_missing_data` assertions matter more than the numbers. An alarm on a failure
COUNT that uses the default ("missing") sits in INSUFFICIENT_DATA and never fires, which
is indistinguishable from healthy — the most common way an alarm is silently useless.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[3] / "infra" / "modules" / "observability" / "main.tf"


@pytest.fixture(scope="module")
def terraform() -> str:
    if not MODULE.exists():
        pytest.skip("observability module not present (P2)")
    return MODULE.read_text()


def _block(source: str, resource: str, name: str) -> str:
    """Extract one resource block."""
    match = re.search(rf'resource\s+"{resource}"\s+"{name}"\s*\{{(.*?)\n\}}', source, re.DOTALL)
    assert match, f"{resource}.{name} not found"
    return match.group(1)


def test_api_error_alarm_needs_two_periods(terraform: str) -> None:
    """A single cold-start blip must not page anyone."""
    block = _block(terraform, "aws_cloudwatch_metric_alarm", "api_errors")
    assert "evaluation_periods  = 2" in block or "evaluation_periods = 2" in block
    assert "period              = 300" in block or "period = 300" in block


def test_api_error_threshold_is_not_zero() -> None:
    """A threshold of 0 with GreaterThanOrEqual fires on every evaluation period.

    Enforced by a Terraform variable validation, asserted here so the guard itself
    cannot be removed unnoticed.
    """
    variables = (MODULE.parent / "variables.tf").read_text()
    assert "var.api_error_threshold >= 1" in variables


def test_scan_failure_alarm_fires_on_a_single_failure(terraform: str) -> None:
    """Unlike an error rate, one failed scan means an account went unscanned.

    There is no tolerable rate to tune, so the threshold is 1.
    """
    block = _block(terraform, "aws_cloudwatch_metric_alarm", "scan_failures")
    assert re.search(r"threshold\s+=\s+1", block)
    assert re.search(r"evaluation_periods\s+=\s+1", block)


def test_dlq_alarm_fires_on_any_message(terraform: str) -> None:
    """A DLQ is where work goes when it could not be processed.

    Non-zero depth is already the failure; there is nothing to tolerate.
    """
    block = _block(terraform, "aws_cloudwatch_metric_alarm", "dlq_depth")
    assert re.search(r"threshold\s+=\s+0", block)
    assert "GreaterThanThreshold" in block


@pytest.mark.parametrize("alarm", ["api_errors", "scan_failures", "dlq_depth"])
def test_failure_count_alarms_treat_missing_data_as_healthy(terraform: str, alarm: str) -> None:
    """No traffic genuinely means no errors, for a COUNT metric.

    Leaving this at the default would park the alarm in INSUFFICIENT_DATA — which never
    fires and never recovers.
    """
    block = _block(terraform, "aws_cloudwatch_metric_alarm", alarm)
    assert 'treat_missing_data = "notBreaching"' in block


def test_the_heartbeat_alarm_inverts_missing_data(terraform: str) -> None:
    """FR-053, and the reason this alarm exists at all.

    Without a heartbeat, silence means either 'nothing is wrong' or 'alerting is
    broken', and the two are indistinguishable. The heartbeat fires when the metric
    STOPS arriving, so `treat_missing_data` must be "breaching" — the opposite of every
    other alarm here. Getting this backwards would produce an alarm that can never fire.
    """
    block = _block(terraform, "aws_cloudwatch_metric_alarm", "alerting_heartbeat")
    assert 'treat_missing_data = "breaching"' in block
    assert "LessThanThreshold" in block


@pytest.mark.parametrize(
    "alarm", ["api_errors", "scan_failures", "dlq_depth", "alerting_heartbeat"]
)
def test_every_alarm_recovers_automatically(terraform: str, alarm: str) -> None:
    """FR-052: an alarm returns to healthy when its condition clears, with no reset.

    `ok_actions` is what makes the recovery visible; without it the alarm goes quiet but
    nobody learns it recovered.
    """
    block = _block(terraform, "aws_cloudwatch_metric_alarm", alarm)
    assert "ok_actions" in block, f"{alarm} has no ok_actions -- FR-052 unmet"


@pytest.mark.parametrize(
    "alarm", ["api_errors", "scan_failures", "dlq_depth", "alerting_heartbeat"]
)
def test_every_alarm_publishes_to_the_alert_topic(terraform: str, alarm: str) -> None:
    """FR-051: an alarm with no action is a dashboard widget, not an alert."""
    block = _block(terraform, "aws_cloudwatch_metric_alarm", alarm)
    assert "aws_sns_topic.alerts.arn" in block


def test_all_three_fr050_conditions_have_an_alarm(terraform: str) -> None:
    """FR-050 names exactly three: service errors, scan failures, and DLQ depth."""
    for required in ("api_errors", "scan_failures", "dlq_depth"):
        assert f'"{required}"' in terraform


def test_the_dashboard_covers_what_fr049_names(terraform: str) -> None:
    """FR-049: error rates, scan outcomes, and unprocessed-work depth in one place."""
    for widget in ("API errors", "Scan outcomes", "Dead-letter queue depth"):
        assert widget in terraform
