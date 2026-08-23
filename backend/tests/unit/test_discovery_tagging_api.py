"""Resource Groups Tagging API sweep (FR-016, FR-017, research.md R-201).

**R-209's VERIFY resolved, empirically, for this API**: moto DOES mock
`resourcegroupstaggingapi.get_resources` for tagged resources (confirmed against a
real EC2 instance), but its mock only ever returns *tagged* resources -- an untagged
instance created alongside a tagged one never appears in moto's response at all. That
is the opposite of what FR-017 needs to prove. The untagged-resource guarantee is
therefore tested against a hand-built fixture (R-209's own documented fallback),
which tests the parsing code we actually wrote rather than moto's simulation gap.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from connectors.aws import _sweep_tagging_api
from connectors.base import ConnectorAccount


@mock_aws
def test_a_tagged_resource_is_discovered_with_its_tags() -> None:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    instance_id = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]
    ec2.create_tags(Resources=[instance_id], Tags=[{"Key": "Name", "Value": "web-1"}])

    resources = _sweep_tagging_api(boto3.Session(), "us-east-1")

    assert len(resources) == 1
    resource = resources[0]
    assert resource.resource_id.endswith(instance_id)
    assert resource.tags == {"Name": "web-1"}
    assert resource.name == "web-1"
    assert resource.resource_type == "AWS::EC2::Instance"
    assert resource.region == "us-east-1"


def _fixture_page(arns_and_tags: list[tuple[str, dict[str, str]]]) -> dict[str, Any]:
    return {
        "ResourceTagMappingList": [
            {"ResourceARN": arn, "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}
            for arn, tags in arns_and_tags
        ]
    }


def test_untagged_resources_appear_with_the_same_completeness_as_tagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-017, via a hand-built fixture -- see module docstring for why moto cannot
    exercise this path."""
    tagged_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-tagged"
    untagged_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-untagged"

    fake_client = MagicMock()
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [
        _fixture_page([(tagged_arn, {"env": "prod"}), (untagged_arn, {})])
    ]
    fake_client.get_paginator.return_value = fake_paginator

    fake_session = MagicMock()
    fake_session.client.return_value = fake_client

    resources = _sweep_tagging_api(fake_session, "us-east-1")

    assert len(resources) == 2
    by_arn = {r.resource_id: r for r in resources}
    untagged = by_arn[untagged_arn]
    tagged = by_arn[tagged_arn]
    # Same shape, same completeness -- only the tags (and derived name) differ.
    assert untagged.tags == {}
    assert untagged.resource_type == tagged.resource_type == "AWS::EC2::Instance"
    assert untagged.service == tagged.service == "ec2"
    assert untagged.region == tagged.region == "us-east-1"


def test_connector_account_supplies_no_credential_to_the_sweep() -> None:
    """Sanity check: the sweep takes a boto3 session, never a raw key pair -- the
    ConnectorAccount type this session was built from carries no such field either
    (Principle III), confirmed here since discovery is the consumer."""
    account = ConnectorAccount(aws_account_id="123456789012", connection_mode="local")
    for forbidden in ("access_key", "secret_key", "access_key_id", "secret_access_key"):
        assert not hasattr(account, forbidden)
