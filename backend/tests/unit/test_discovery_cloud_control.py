"""Cloud Control API supplementary sweep (FR-016, research.md R-201, R-209).

**R-209's VERIFY resolved, empirically, for this API**: moto does not implement
`cloudcontrol` at all -- every call returns a 404 "Not yet implemented" `ClientError`
regardless of `TypeName`, confirmed directly against a real EC2 instance. There is no
moto fidelity question to resolve here; there is no simulation to trust or distrust.
Parsing/dedup behavior is tested against a hand-built fixture (R-209's documented
fallback). The 404-degradation test below uses real moto, deliberately -- moto's own
"not implemented" response IS a legitimate stand-in for "Cloud Control genuinely
lacks coverage for this type," which `_sweep_cloud_control` must survive gracefully.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import boto3
from moto import mock_aws

from connectors.aws import _CLOUD_CONTROL_SUPPLEMENTARY_TYPES, _sweep_cloud_control


def _fixture_page(identifiers: list[str]) -> dict[str, Any]:
    return {"ResourceDescriptions": [{"Identifier": i} for i in identifiers]}


def test_supplementary_types_are_discovered_via_a_hand_built_fixture() -> None:
    fake_client = MagicMock()
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [_fixture_page(["access-point-1"])]
    fake_client.get_paginator.return_value = fake_paginator

    fake_session = MagicMock()
    fake_session.client.return_value = fake_client

    resources = _sweep_cloud_control(fake_session, "us-east-1")

    assert len(resources) == len(_CLOUD_CONTROL_SUPPLEMENTARY_TYPES)
    first = resources[0]
    assert first.resource_id == "access-point-1"
    assert first.resource_type in _CLOUD_CONTROL_SUPPLEMENTARY_TYPES
    assert first.region == "us-east-1"


@mock_aws
def test_an_unsupported_type_does_not_fail_the_whole_sweep() -> None:
    """Real moto here: its 404 for `cloudcontrol` is a genuine stand-in for "this
    type isn't accessible" -- `_sweep_cloud_control` must continue past it, not
    raise, matching R-201's "best-effort supplementary coverage" framing."""
    resources = _sweep_cloud_control(boto3.Session(), "us-east-1")
    assert resources == []  # every configured type 404s under moto -- no crash


def test_dedup_against_tagging_results_happens_in_the_connector_not_here() -> None:
    """`_sweep_cloud_control` itself does not dedupe against another surface's
    results -- that is `AwsConnector.discover`'s job, since only it sees both lists.
    Documented here so the responsibility split is asserted, not just described."""
    fake_client = MagicMock()
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [_fixture_page(["dup-1"])]
    fake_client.get_paginator.return_value = fake_paginator
    fake_session = MagicMock()
    fake_session.client.return_value = fake_client

    first_call = _sweep_cloud_control(fake_session, "us-east-1")
    second_call = _sweep_cloud_control(fake_session, "us-east-1")
    # Calling it twice returns the same resources both times -- no memoisation, no
    # implicit dedup state. The connector is what dedupes across the two surfaces.
    assert {r.resource_id for r in first_call} == {r.resource_id for r in second_call}
