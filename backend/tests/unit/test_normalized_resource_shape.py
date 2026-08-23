"""Every discovered resource conforms to the FR-013 shape, regardless of source
surface (Tagging API vs Cloud Control API).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

from connectors.aws import AwsConnector
from connectors.base import ConnectorAccount, NormalizedResource

FR013_FIELDS = {
    "provider",
    "account_id",
    "resource_id",
    "service",
    "resource_type",
    "region",
    "name",
    "tags",
    "state",
    "created_at",
    "detail",
}


def test_normalized_resource_declares_exactly_the_fr013_fields() -> None:
    fields = {f.name for f in NormalizedResource.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert fields == FR013_FIELDS


@mock_aws
def test_a_tagging_api_resource_conforms_to_the_shape() -> None:
    # Tagged, not untagged: moto's Tagging API mock only ever returns tagged
    # resources (confirmed empirically -- see test_discovery_tagging_api.py's module
    # docstring), so an untagged instance here would make this test assert nothing.
    # The untagged-inclusion guarantee itself is proven there, via a hand-built
    # fixture; this test only needs a real resource to check the shape against.
    ec2 = boto3.client("ec2", region_name="us-east-1")
    instance_id = ec2.run_instances(ImageId="ami-1", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]
    ec2.create_tags(Resources=[instance_id], Tags=[{"Key": "env", "Value": "test"}])

    connector = AwsConnector()
    account = ConnectorAccount(aws_account_id="123456789012", connection_mode="local")
    resources = connector.discover(account, "us-east-1")

    assert len(resources) == 1
    _assert_conforms(resources[0])


def test_a_cloud_control_resource_conforms_to_the_shape() -> None:
    """Tagging API returns nothing (empty account); the supplementary sweep is
    exercised via a hand-built fixture, matching R-209's fallback."""
    fake_cc_client = MagicMock()
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{"ResourceDescriptions": [{"Identifier": "ap-1"}]}]
    fake_cc_client.get_paginator.return_value = fake_paginator

    fake_tagging_client = MagicMock()
    fake_tagging_paginator = MagicMock()
    fake_tagging_paginator.paginate.return_value = [{"ResourceTagMappingList": []}]
    fake_tagging_client.get_paginator.return_value = fake_tagging_paginator

    def _client(service_name: str, **_kwargs: Any) -> Any:
        return fake_cc_client if service_name == "cloudcontrol" else fake_tagging_client

    fake_session = MagicMock()
    fake_session.client.side_effect = _client

    with patch("boto3.Session", return_value=fake_session):
        connector = AwsConnector()
        account = ConnectorAccount(aws_account_id="123456789012", connection_mode="local")
        resources = connector.discover(account, "us-east-1")

    assert len(resources) >= 1
    for resource in resources:
        _assert_conforms(resource)


def _assert_conforms(resource: NormalizedResource) -> None:
    assert isinstance(resource.provider, str) and resource.provider
    assert isinstance(resource.resource_id, str) and resource.resource_id
    assert isinstance(resource.service, str) and resource.service
    assert isinstance(resource.resource_type, str) and resource.resource_type
    assert isinstance(resource.region, str) and resource.region
    assert isinstance(resource.tags, dict)
    assert isinstance(resource.detail, dict)
    # name/state/created_at/account_id may legitimately be empty/None at discovery
    # time (enrichment fills state/created_at for covered types) -- only their type
    # is asserted, not truthiness.
    assert resource.name is None or isinstance(resource.name, str)
    assert resource.state is None or isinstance(resource.state, str)
