"""All six P1 governance-critical types populate `resource.detail` (FR-019, R-202).

Every fixture here is real moto -- confirmed empirically (unlike Tagging/Cloud
Control) that moto mocks all six describe calls with enough fidelity to exercise the
enrichment code as written: EC2, EBS, EIP, S3 (location/versioning/encryption), RDS,
and Lambda (once its execution role's trust policy actually trusts
lambda.amazonaws.com, which moto -- correctly -- validates).
"""

from __future__ import annotations

import io
import json
import zipfile

import boto3
import pytest
from moto import mock_aws

from connectors.aws import AwsConnector
from connectors.base import NormalizedResource


def _lambda_trust_role() -> str:
    iam = boto3.client("iam", region_name="us-east-1")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    return str(
        iam.create_role(RoleName="lambda-role", AssumeRolePolicyDocument=json.dumps(trust))["Role"][
            "Arn"
        ]
    )


@mock_aws
def test_ec2_instance_enrichment() -> None:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    instance_id = ec2.run_instances(ImageId="ami-1", MinCount=1, MaxCount=1)["Instances"][0][
        "InstanceId"
    ]

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id=f"arn:aws:ec2:us-east-1:123456789012:instance/{instance_id}",
        service="ec2",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["instance_type"]
    assert enriched.detail["state"] == "running"


@mock_aws
def test_ebs_volume_enrichment() -> None:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    volume_id = ec2.create_volume(AvailabilityZone="us-east-1a", Size=8)["VolumeId"]

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id=f"arn:aws:ec2:us-east-1:123456789012:volume/{volume_id}",
        service="ec2",
        resource_type="AWS::EC2::Volume",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["size_gib"] == 8
    assert enriched.detail["encrypted"] is not None


@mock_aws
def test_eip_enrichment() -> None:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    allocation_id = ec2.allocate_address(Domain="vpc")["AllocationId"]

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id=f"arn:aws:ec2:us-east-1:123456789012:elastic-ip/{allocation_id}",
        service="ec2",
        resource_type="AWS::EC2::EIP",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["public_ip"]
    assert enriched.detail["association_state"] == "unassociated"


@mock_aws
def test_s3_bucket_enrichment() -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="my-test-bucket")

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:s3:::my-test-bucket",
        service="s3",
        resource_type="AWS::S3::Bucket",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert "region" in enriched.detail
    assert enriched.detail["encryption"] is False  # none configured


@mock_aws
def test_rds_instance_enrichment() -> None:
    rds = boto3.client("rds", region_name="us-east-1")
    rds.create_db_instance(
        DBInstanceIdentifier="mydb",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="a-fake-password-1",
        AllocatedStorage=20,
    )

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:rds:us-east-1:123456789012:db:mydb",
        service="rds",
        resource_type="AWS::RDS::DBInstance",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["engine"] == "postgres"
    assert enriched.detail["storage_gib"] == 20


@mock_aws
def test_lambda_function_enrichment() -> None:
    role_arn = _lambda_trust_role()
    lam = boto3.client("lambda", region_name="us-east-1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("lambda_function.py", "def handler(e, c): return 1")
    lam.create_function(
        FunctionName="myfn",
        Runtime="python3.12",
        Role=role_arn,
        Handler="lambda_function.handler",
        Code={"ZipFile": buf.getvalue()},
    )

    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:lambda:us-east-1:123456789012:function:myfn",
        service="lambda",
        resource_type="AWS::Lambda::Function",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail["runtime"] == "python3.12"


def test_an_uncovered_resource_type_is_returned_unchanged() -> None:
    """FR-020/FR-021: absence of coverage is expected behavior, not an error."""
    connector = AwsConnector()
    connector._session = boto3.Session()  # type: ignore[attr-defined]
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:sqs:us-east-1:123456789012:my-queue",
        service="sqs",
        resource_type="sqs:my-queue",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    enriched = connector.enrich(resource)
    assert enriched.detail == {}
    assert enriched == resource


def test_enrich_before_discover_raises_rather_than_reaching_aws() -> None:
    connector = AwsConnector()
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:ec2:us-east-1:123456789012:instance/i-x",
        service="ec2",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        name=None,
        tags={},
        state=None,
        created_at=None,
    )
    with pytest.raises(RuntimeError, match="discover"):
        connector.enrich(resource)
