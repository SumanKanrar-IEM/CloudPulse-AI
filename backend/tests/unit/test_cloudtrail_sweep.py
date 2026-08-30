"""Bulk CloudTrail sweep for ownership attribution (FR-020, research.md R-302).

**R-307's VERIFY resolved, empirically**: `moto`'s CloudTrail mock does not
implement `lookup_events` at all -- calling it inside `@mock_aws` raises
`NotImplementedError: The lookup_events action has not been implemented`,
confirmed against a moto-mocked `ec2.run_instances()` call before ever
correlating anything. There is no partial-fidelity path here the way R-209's
tagging-API case had; every test in this file uses R-307's documented
fallback -- a hand-built fixture mocking the boto3 `lookup_events` response
shape directly -- because moto offers no CloudTrail simulation to test
against at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from connectors.aws import sweep_cloudtrail_events, sweep_write_events
from connectors.base import ConnectorAccount

_ACCOUNT = ConnectorAccount(aws_account_id="123456789012", connection_mode="local")


def _event(
    *,
    event_name: str,
    event_time: datetime,
    resource_name: str | None,
    resource_type: str = "AWS::EC2::Instance",
    username: str = "alice",
    identity_type: str = "IAMUser",
    identity_arn: str = "arn:aws:iam::123456789012:user/alice",
    event_id: str = "evt-1",
    read_only: str = "false",
) -> dict[str, Any]:
    resources = (
        [{"ResourceType": resource_type, "ResourceName": resource_name}] if resource_name else []
    )
    return {
        "EventId": event_id,
        "EventName": event_name,
        "EventTime": event_time,
        "Username": username,
        "Resources": resources,
        "ReadOnly": read_only,
        "CloudTrailEvent": json.dumps(
            {"userIdentity": {"type": identity_type, "arn": identity_arn}}
        ),
    }


def _fake_session(pages: list[dict[str, Any]]) -> MagicMock:
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = pages
    fake_client = MagicMock()
    fake_client.get_paginator.return_value = fake_paginator
    fake_session = MagicMock()
    fake_session.client.return_value = fake_client
    return fake_session


def _sweep(monkeypatch: Any, pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    fake_session = _fake_session(pages)
    monkeypatch.setattr("connectors.aws._build_session", lambda *a, **k: fake_session)
    return sweep_cloudtrail_events(_ACCOUNT, "us-east-1", since=datetime(2026, 1, 1, tzinfo=UTC))


def test_a_creation_event_is_correlated_to_its_resource(monkeypatch: Any) -> None:
    """FR-020/R-302: `RunInstances` correlates to the instance it launched, with
    the human principal and event id captured as evidence."""
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [{"Events": [_event(event_name="RunInstances", event_time=t, resource_name="i-abc123")]}],
    )
    assert "i-abc123" in events
    entry = events["i-abc123"]
    assert entry["principal"] == "arn:aws:iam::123456789012:user/alice"
    assert entry["is_human"] is True
    assert entry["event_name"] == "RunInstances"
    assert entry["event_id"] == "evt-1"
    assert entry["is_write"] is True


def test_a_non_creation_event_is_ignored(monkeypatch: Any) -> None:
    """Only the ten governance-critical types' creation events are recognized --
    e.g. `StopInstances` is real activity but not a creator signal."""
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [{"Events": [_event(event_name="StopInstances", event_time=t, resource_name="i-abc123")]}],
    )
    assert events == {}


def test_an_event_with_no_resources_is_skipped(monkeypatch: Any) -> None:
    """Some CloudTrail events record no resource correlation at all -- must not
    crash, must simply contribute nothing to the map."""
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [{"Events": [_event(event_name="RunInstances", event_time=t, resource_name=None)]}],
    )
    assert events == {}


def test_an_assumed_role_principal_is_not_human(monkeypatch: Any) -> None:
    """FR-021's P1 scope: an AssumedRole (a CI/CD pipeline's typical shape) is
    recorded, but flagged `is_human=False` -- `app.governance.ownership`
    decides what to do with that, not the sweep itself."""
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [
            {
                "Events": [
                    _event(
                        event_name="CreateBucket",
                        event_time=t,
                        resource_name="my-bucket",
                        resource_type="AWS::S3::Bucket",
                        identity_type="AssumedRole",
                        identity_arn="arn:aws:sts::123456789012:assumed-role/ci-deploy/session",
                    )
                ]
            }
        ],
    )
    assert events["my-bucket"]["is_human"] is False


def test_pagination_combines_events_across_pages(monkeypatch: Any) -> None:
    t1 = datetime(2026, 3, 1, tzinfo=UTC)
    t2 = datetime(2026, 3, 2, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [
            {"Events": [_event(event_name="RunInstances", event_time=t1, resource_name="i-page1")]},
            {
                "Events": [
                    _event(event_name="CreateVolume", event_time=t2, resource_name="vol-page2")
                ]
            },
        ],
    )
    assert set(events) == {"i-page1", "vol-page2"}


def test_the_earliest_creation_event_wins_when_a_resource_has_more_than_one(
    monkeypatch: Any,
) -> None:
    """Defensive: a resource id should only ever get one true creation event,
    but if more than one shows up, the earliest is the actual creation
    moment, not whichever page happened to list it last."""
    earlier = datetime(2026, 3, 1, tzinfo=UTC)
    later = datetime(2026, 3, 5, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [
            {
                "Events": [
                    _event(
                        event_name="RunInstances",
                        event_time=later,
                        resource_name="i-dup",
                        username="bob",
                        identity_arn="arn:aws:iam::123456789012:user/bob",
                        event_id="evt-later",
                    ),
                    _event(
                        event_name="RunInstances",
                        event_time=earlier,
                        resource_name="i-dup",
                        username="alice",
                        identity_arn="arn:aws:iam::123456789012:user/alice",
                        event_id="evt-earlier",
                    ),
                ]
            }
        ],
    )
    assert events["i-dup"]["event_id"] == "evt-earlier"
    assert events["i-dup"]["principal"] == "arn:aws:iam::123456789012:user/alice"


def test_a_root_principal_is_treated_as_human(monkeypatch: Any) -> None:
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep(
        monkeypatch,
        [
            {
                "Events": [
                    _event(
                        event_name="AllocateAddress",
                        event_time=t,
                        resource_name="eipalloc-root1",
                        resource_type="AWS::EC2::EIP",
                        identity_type="Root",
                        identity_arn="arn:aws:iam::123456789012:root",
                    )
                ]
            }
        ],
    )
    assert events["eipalloc-root1"]["is_human"] is True


# --- sweep_write_events (P2 fallback, FR-024/FR-025) ---------------------------


def _sweep_writes(monkeypatch: Any, pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    fake_session = _fake_session(pages)
    monkeypatch.setattr("connectors.aws._build_session", lambda *a, **k: fake_session)
    return sweep_write_events(_ACCOUNT, "us-east-1", since=datetime(2026, 1, 1, tzinfo=UTC))


def test_write_events_are_collected_per_resource(monkeypatch: Any) -> None:
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep_writes(
        monkeypatch,
        [{"Events": [_event(event_name="StopInstances", event_time=t, resource_name="i-abc")]}],
    )
    assert len(events["i-abc"]) == 1
    assert events["i-abc"][0]["principal"] == "arn:aws:iam::123456789012:user/alice"
    assert events["i-abc"][0]["is_human"] is True


def test_read_only_events_are_excluded(monkeypatch: Any) -> None:
    t = datetime(2026, 3, 1, tzinfo=UTC)
    events = _sweep_writes(
        monkeypatch,
        [
            {
                "Events": [
                    _event(
                        event_name="DescribeInstances",
                        event_time=t,
                        resource_name="i-abc",
                        read_only="true",
                    )
                ]
            }
        ],
    )
    assert events == {}


def test_multiple_write_events_accumulate_for_the_same_resource(monkeypatch: Any) -> None:
    t1 = datetime(2026, 3, 1, tzinfo=UTC)
    t2 = datetime(2026, 3, 2, tzinfo=UTC)
    events = _sweep_writes(
        monkeypatch,
        [
            {
                "Events": [
                    _event(event_name="StopInstances", event_time=t1, resource_name="i-abc"),
                    _event(event_name="StartInstances", event_time=t2, resource_name="i-abc"),
                ]
            }
        ],
    )
    assert len(events["i-abc"]) == 2
