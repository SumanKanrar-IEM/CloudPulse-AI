"""The four P2 extended-enrichment types populate `resource.detail` (FR-020, T056).

Proves SC-005's coverage-as-data extensibility claim on a second, real addition --
not just the original six P1 types (T036/T037's `coverage_definitions.json`
seeding) -- by exercising the same `AwsConnector.enrich()` dispatch path with zero
code change to `app/scan/enrichment.py` or `AwsConnector.enrich()` itself: adding a
type here is a `coverage_definitions.json` entry plus one new function in
`connectors/aws.py`'s registry, same as T036 established.

Every fixture is real moto -- confirmed empirically (same standard
`test_enrichment_p1_types.py` set for the P1 six): EKS, DynamoDB, and IAM mock their
describe calls with enough fidelity to exercise this code as written. ELBv2's mock
returns `Scheme: None` when the create call omits `Scheme` (AWS itself defaults it
to "internet-facing" server-side) -- a moto fidelity gap, not this code's bug -- so
the fixture passes `Scheme` explicitly to test the field CloudPulse actually reads.
"""

from __future__ import annotations

import json

import boto3
from moto import mock_aws

from connectors.aws import AwsConnector
from connectors.base import NormalizedResource


@mock_aws
def test_eks_cluster_enrichment() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "eks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    role_arn = iam.create_role(RoleName="eks-role", AssumeRolePolicyDocument=json.dumps(trust))[
        "Role"
    ]["Arn"]
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet_ids = [
        ec2.create_subnet(
            VpcId=vpc_id, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=f"us-east-1{az}"
        )["Subnet"]["SubnetId"]
        for i, az in enumerate(("a", "b"), start=1)
    ]
    eks = boto3.client("eks", region_name="us-east-1")
    eks.create_cluster(
        name="mycluster", roleArn=role_arn, resourcesVpcConfig={"subnetIds": subnet_ids}
    )

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:eks:us-east-1:123456789012:cluster/mycluster",
        service="eks",
        resource_type="AWS::EKS::Cluster",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["status"] == "ACTIVE"
    assert enriched.detail["version"]
    assert enriched.detail["endpoint"]


@mock_aws
def test_dynamodb_table_enrichment() -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="mytable",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:dynamodb:us-east-1:123456789012:table/mytable",
        service="dynamodb",
        resource_type="AWS::DynamoDB::Table",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["status"] == "ACTIVE"
    assert enriched.detail["billing_mode"] == "PAY_PER_REQUEST"
    assert enriched.detail["item_count"] == 0


@mock_aws
def test_elb_v2_enrichment() -> None:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet_ids = [
        ec2.create_subnet(
            VpcId=vpc_id, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=f"us-east-1{az}"
        )["Subnet"]["SubnetId"]
        for i, az in enumerate(("a", "b"), start=1)
    ]
    elbv2 = boto3.client("elbv2", region_name="us-east-1")
    created = elbv2.create_load_balancer(
        Name="my-lb", Subnets=subnet_ids, Type="application", Scheme="internet-facing"
    )["LoadBalancers"][0]

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id=created["LoadBalancerArn"],
        service="elasticloadbalancing",
        resource_type="AWS::ElasticLoadBalancingV2::LoadBalancer",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["type"] == "application"
    assert enriched.detail["scheme"] == "internet-facing"
    assert enriched.detail["vpc_id"] == vpc_id


@mock_aws
def test_iam_role_enrichment() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    iam.create_role(RoleName="my-role", AssumeRolePolicyDocument=json.dumps(trust))
    policy_arn = iam.create_policy(
        PolicyName="my-policy",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}],
            }
        ),
    )["Policy"]["Arn"]
    iam.attach_role_policy(RoleName="my-role", PolicyArn=policy_arn)

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:iam::123456789012:role/my-role",
        service="iam",
        resource_type="AWS::IAM::Role",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["attached_policy_count"] == 1
    assert enriched.detail["max_session_duration"] == 3600
    assert enriched.detail["create_date"]


def test_extended_types_resolve_via_the_same_data_driven_dispatch() -> None:
    """SC-005: adding these four types required zero change to `enrich()` itself --
    `coverage_definitions.json` plus `ENRICHMENT_FUNCTIONS` is the whole seam."""
    from app.scan.coverage import load_coverage_definitions, resolve_enrichment_function
    from connectors.aws import ENRICHMENT_FUNCTIONS

    definitions = load_coverage_definitions()
    for resource_type in (
        "AWS::EKS::Cluster",
        "AWS::DynamoDB::Table",
        "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "AWS::IAM::Role",
    ):
        fn = resolve_enrichment_function(resource_type, definitions, ENRICHMENT_FUNCTIONS)
        assert fn is not None, f"{resource_type} has no resolvable enrichment function"
