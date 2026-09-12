"""Metrics collection: the normalisation and the CloudWatch call (T039; spec
006, FR-019, FR-020, S50).

FR-020 is the property this file pins hardest: **a resource with no measurement
is recorded as unknown, never as zero.** Two silences reach `normalise`, and
both must become `value=None`: a metric CloudWatch returned no datapoint for,
and a metric the platform never queries for that type (EC2 memory). A zero in
either place would drag an average down and understate utilization -- the same
argument `spend_record.is_gap` already made for spend.

The no-duplicate half of FR-019 lives in the database (a unique constraint and
a conditional upsert) and is proven in
`tests/integration/test_metrics_persistence.py` against a real PostgreSQL.
Here, the pure parts: query construction, id shape, and the moto-backed
connector call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import boto3
from moto import mock_aws

from app.governance.metrics import (
    ALL_KINDS,
    MeteredResource,
    build_queries,
    normalise,
    period_start_for,
    query_id,
)
from app.models.enums import ResourceMetricKind
from connectors.aws import ConnectorAccount, get_metric_data

PERIOD_START = period_start_for(datetime(2026, 3, 1, tzinfo=UTC).date())
EC2 = MeteredResource(
    resource_id=uuid.uuid4(),
    resource_type="AWS::EC2::Instance",
    arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abc",
    region="us-east-1",
)
RDS = MeteredResource(
    resource_id=uuid.uuid4(),
    resource_type="AWS::RDS::DBInstance",
    arn="arn:aws:rds:us-east-1:123456789012:db:orders-primary",
    region="us-east-1",
)


# --- query construction --------------------------------------------------------


def test_queries_use_the_arn_tail_as_the_dimension_for_both_shapes() -> None:
    """EC2 ARNs end in `/i-...`, RDS ARNs in `:name`. One rule covers both."""
    queries = build_queries([EC2, RDS])

    dims = {q["Id"]: q["MetricStat"]["Metric"]["Dimensions"][0] for q in queries}
    assert dims[query_id(0, ResourceMetricKind.CPU)] == {"Name": "InstanceId", "Value": "i-0abc"}
    assert dims[query_id(1, ResourceMetricKind.CPU)] == {
        "Name": "DBInstanceIdentifier",
        "Value": "orders-primary",
    }


def test_ec2_has_no_memory_query_and_rds_has_all_four() -> None:
    """The absence is the FR-020 mechanism: `normalise` turns a kind with no
    query into an unavailable row, so EC2 memory is never reported as 0."""
    kinds_for = {
        resource.arn: {q["Id"].split("_", 1)[1] for q in build_queries([resource])}
        for resource in (EC2, RDS)
    }
    assert kinds_for[EC2.arn] == {"cpu", "network"}
    assert kinds_for[RDS.arn] == {"cpu", "memory", "storage", "network"}


def test_a_type_with_no_entry_produces_no_queries() -> None:
    bucket = MeteredResource(
        resource_id=uuid.uuid4(),
        resource_type="AWS::S3::Bucket",
        arn="arn:aws:s3:::b",
        region="us-east-1",
    )
    assert build_queries([bucket]) == []


def test_query_ids_satisfy_cloudwatch_s_identifier_rule() -> None:
    """^[a-z][a-zA-Z0-9_]*$. A UUID would fail on the leading digit and the
    hyphens, which is why the id is an index, not the resource id."""
    import re

    for q in build_queries([EC2, RDS]):
        assert re.fullmatch(r"[a-z][a-zA-Z0-9_]*", q["Id"]), q["Id"]


# --- normalisation: FR-020 -------------------------------------------------------


def test_every_resource_gets_a_row_for_every_kind() -> None:
    measurements = normalise([EC2, RDS], [], period_start=PERIOD_START)

    assert len(measurements) == 2 * len(ALL_KINDS)
    assert {(m.resource_id, m.metric) for m in measurements} == {
        (r.resource_id, k) for r in (EC2, RDS) for k in ALL_KINDS
    }


def test_a_present_value_is_stored_and_a_missing_one_is_none_not_zero() -> None:
    results = [
        {"Id": query_id(0, ResourceMetricKind.CPU), "Values": [12.5]},
        # CloudWatch answered, with nothing: an empty Values list.
        {"Id": query_id(0, ResourceMetricKind.NETWORK), "Values": []},
    ]

    by_kind = {m.metric: m.value for m in normalise([EC2], results, period_start=PERIOD_START)}

    assert by_kind[ResourceMetricKind.CPU] == Decimal("12.5000")
    assert by_kind[ResourceMetricKind.NETWORK] is None  # answered, empty
    assert by_kind[ResourceMetricKind.MEMORY] is None  # never asked
    assert by_kind[ResourceMetricKind.STORAGE] is None  # never asked
    assert 0 not in by_kind.values()
    assert Decimal(0) not in by_kind.values()


def test_a_value_is_quantised_to_the_column_s_precision() -> None:
    results = [{"Id": query_id(0, ResourceMetricKind.CPU), "Values": [33.333333333]}]

    (cpu,) = (
        m
        for m in normalise([EC2], results, period_start=PERIOD_START)
        if m.metric is ResourceMetricKind.CPU
    )

    assert cpu.value == Decimal("33.3333")


def test_an_unexpected_result_id_is_ignored_rather_than_misattributed() -> None:
    """A result for a query index the caller did not send cannot be matched to
    a resource, and guessing would attribute a number to the wrong one."""
    results = [{"Id": query_id(7, ResourceMetricKind.CPU), "Values": [99.0]}]

    values = {m.value for m in normalise([EC2], results, period_start=PERIOD_START)}

    assert values == {None}


# --- the connector call, against moto ---------------------------------------------


@mock_aws
def test_get_metric_data_returns_only_ids_and_values() -> None:
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-0abc"}],
                "Timestamp": datetime(2026, 3, 1, 12, tzinfo=UTC),
                "Value": 40.0,
            }
        ],
    )
    account = ConnectorAccount(
        aws_account_id="123456789012", connection_mode="local", role_arn=None, external_id=None
    )

    results = get_metric_data(
        account,
        "us-east-1",
        build_queries([EC2]),
        start=PERIOD_START,
        end=datetime(2026, 3, 2, tzinfo=UTC),
    )

    by_id = {r["Id"]: r for r in results}
    assert set(by_id[query_id(0, ResourceMetricKind.CPU)]) == {"Id", "Values"}
    assert by_id[query_id(0, ResourceMetricKind.CPU)]["Values"] == [40.0]
    # Asked for, nothing published: present in the results with no values,
    # which is what normalise() turns into the unavailable row.
    assert by_id[query_id(0, ResourceMetricKind.NETWORK)]["Values"] == []


# --- units: bytes do not fit NUMERIC(12,4) ------------------------------------------


def test_byte_metrics_are_scaled_into_the_column_s_range() -> None:
    """100 GB of free storage is 1e11 bytes; the column holds eight integer
    digits. Stored in GB it is 100.0000. This is the test that fails with a
    database error, not a wrong number, if the scale is dropped."""
    results = [
        {"Id": query_id(0, ResourceMetricKind.STORAGE), "Values": [100_000_000_000.0]},
        {"Id": query_id(0, ResourceMetricKind.MEMORY), "Values": [8_589_934_592.0]},
        {"Id": query_id(0, ResourceMetricKind.CPU), "Values": [55.5]},
    ]

    by_kind = {m.metric: m.value for m in normalise([RDS], results, period_start=PERIOD_START)}

    assert by_kind[ResourceMetricKind.STORAGE] == Decimal("100.0000")
    assert by_kind[ResourceMetricKind.MEMORY] == Decimal("8.5899")
    assert by_kind[ResourceMetricKind.CPU] == Decimal("55.5000")  # percent, unscaled
    for value in by_kind.values():
        if value is not None:
            assert value < Decimal("100000000"), "would overflow NUMERIC(12,4)"
