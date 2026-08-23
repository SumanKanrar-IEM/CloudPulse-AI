"""The AWS connector implementation (FR-014).

This file holds every AWS-SDK-touching operation this spec needs -- role
verification (FR-007), ExternalId secret storage (FR-003a, Principle III), and now
whole-account discovery (R-201) and targeted enrichment (R-202) -- because
`ops/scripts/check_connector_boundary.py` (FR-054) allows `boto3`/`botocore` imports
**only** inside this package. `app/scan/discovery.py` and `app/scan/enrichment.py`
orchestrate calling `discover()`/`enrich()` below; they contain no AWS SDK import
themselves, by construction, not by convention -- the boundary gate would fail their
PR immediately if they did.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from connectors.base import ConnectorAccount, NormalizedResource

VerificationKind = Literal["verified", "role_not_assumable", "no_usable_access"]


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """The result of a registration-time verification attempt (FR-007).

    ``kind`` distinguishes "role not found or cannot be assumed" from "assumed, but
    grants no usable read access" wherever the underlying AWS error allows -- the two
    failure kinds FR-007 requires callers be able to tell apart.
    """

    kind: VerificationKind
    detail: str


class _SessionError(Exception):
    """Raised by `_build_session` when a role cannot be assumed. Caught by callers
    that need to distinguish this from a downstream API failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _build_session(account: ConnectorAccount, *, session_name: str) -> Any:
    """Same-account: the platform's own ambient identity. Cross-account: assume the
    account's scanner role once (research.md R-206), using its ExternalId.

    Raises `_SessionError` if the role cannot be assumed at all -- distinct from a
    downstream API call failing on a session that *was* successfully built.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    if account.connection_mode != "assume_role":
        return boto3.Session()

    if not account.role_arn:
        raise _SessionError("no role reference supplied")

    sts = boto3.client("sts")
    try:
        assumed = sts.assume_role(
            RoleArn=account.role_arn,
            RoleSessionName=session_name,
            ExternalId=account.external_id,
            DurationSeconds=900,
        )
    except (ClientError, BotoCoreError) as exc:
        raise _SessionError(_error_code(exc)) from exc

    creds = assumed["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def verify_access(account: ConnectorAccount, region: str) -> VerificationOutcome:
    """Attempt a real, read-only action against the target account (FR-007).

    Uses `resourcegroupstaggingapi:GetResources` with a one-item page as the read
    check -- the exact permission whole-account discovery (R-201) depends on, so a
    verified account is proven to support the platform's actual core capability, not
    merely "can assume a role."
    """
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        session = _build_session(account, session_name="cloudpulse-verify")
    except _SessionError as exc:
        return VerificationOutcome("role_not_assumable", exc.code)

    try:
        session.client("resourcegroupstaggingapi", region_name=region).get_resources(
            ResourcesPerPage=1
        )
    except (ClientError, BotoCoreError) as exc:
        return VerificationOutcome("no_usable_access", _error_code(exc))

    return VerificationOutcome("verified", "")


def get_local_account_id() -> str:
    """The AWS account the platform's own execution identity runs in (FR-002).

    Same-account mode scans this account like any other -- derived from STS rather
    than trusted from client input, since an admin should not be able to register an
    arbitrary account ID as "same-account."
    """
    import boto3

    return str(boto3.client("sts").get_caller_identity()["Account"])


# --- Whole-account discovery (FR-016, FR-017, FR-018, research.md R-201) ----------
#
# Resource Groups Tagging API is the primary sweep (broad, fast, untagged resources
# included). Cloud Control API supplements it for resource types the tagging index
# does not cover. FR-016 forbids a hand-maintained list for DISCOVERY itself -- the
# hint table below exists only to let a discovered ARN be recognised for ENRICHMENT
# dispatch (FR-019/FR-021, which coverage-as-data explicitly makes a curated,
# data-driven concern), not to gate which resources are found at all. A resource
# whose ARN matches nothing here still gets a resource_type string, derived purely
# from its ARN structure, and still appears in inventory with full identity fields.

_ARN_TYPE_HINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "ec2": (
        ("instance/", "AWS::EC2::Instance"),
        ("volume/", "AWS::EC2::Volume"),
        ("elastic-ip/", "AWS::EC2::EIP"),
    ),
    "s3": (("", "AWS::S3::Bucket"),),
    "rds": (("db:", "AWS::RDS::DBInstance"),),
    "lambda": (("function:", "AWS::Lambda::Function"),),
}

# Cloud Control API's own IAM actions are under the `cloudformation:` prefix (it is
# built on CloudFormation's resource-provider framework), but its boto3 CLIENT is a
# distinct service named `cloudcontrol` -- easy to conflate; cfn-lint caught the IAM
# side of this mix-up in cross_account_template.yaml (T017) before this ever reached
# a real account.
_CLOUD_CONTROL_SUPPLEMENTARY_TYPES: tuple[str, ...] = (
    # A small, demo-scale-appropriate set the Tagging API sweep is known to miss,
    # not the full CloudFormation registry (thousands of types) -- iterating the
    # full registry on every scan is future tuning work if SC-002's >95% discovery
    # rate is not met in practice for a real account (spec Assumptions).
    "AWS::S3::AccessPoint",
    "AWS::EC2::TransitGateway",
)


def _parse_arn(arn: str) -> dict[str, str]:
    parts = arn.split(":", 5)
    if len(parts) != 6:
        return {"service": "unknown", "region": "", "account_id": "", "resource": arn}
    _, _partition, service, region, account_id, resource = parts
    return {"service": service, "region": region, "account_id": account_id, "resource": resource}


def _resource_type_from_arn(service: str, resource: str) -> str:
    for prefix, cfn_type in _ARN_TYPE_HINTS.get(service, ()):
        if resource.startswith(prefix):
            return cfn_type
    # Generic, service-agnostic fallback (FR-016): the ARN's own structure, not a
    # hand-maintained list. "instance/i-abc" -> "ec2:instance"; a bare bucket name
    # -> "s3:resource" (S3 ARNs carry no "/"-delimited type segment to read).
    component = resource.split("/", 1)[0].split(":", 1)[0] if resource else "resource"
    return f"{service}:{component or 'resource'}"


def _name_from_tags(tags: dict[str, str]) -> str | None:
    return tags.get("Name") or tags.get("name")


def _sweep_tagging_api(session: Any, region: str) -> list[NormalizedResource]:
    """The primary discovery surface (R-201): broad, one call per region, untagged
    resources included (FR-017) -- `GetResources` does not filter by tag presence."""
    from botocore.exceptions import BotoCoreError, ClientError

    client = session.client("resourcegroupstaggingapi", region_name=region)
    resources: list[NormalizedResource] = []
    try:
        paginator = client.get_paginator("get_resources")
        for page in paginator.paginate():
            for mapping in page.get("ResourceTagMappingList", []):
                arn = mapping["ResourceARN"]
                tags = {t["Key"]: t["Value"] for t in mapping.get("Tags", [])}
                parsed = _parse_arn(arn)
                resources.append(
                    NormalizedResource(
                        provider="aws",
                        account_id=parsed["account_id"],
                        resource_id=arn,
                        service=parsed["service"],
                        resource_type=_resource_type_from_arn(
                            parsed["service"], parsed["resource"]
                        ),
                        region=parsed["region"] or region,
                        name=_name_from_tags(tags),
                        tags=tags,
                        state=None,
                        created_at=None,
                    )
                )
    except (ClientError, BotoCoreError):
        # A failed unit of work is retried at the orchestration layer (FR-024), not
        # swallowed here -- re-raise so the caller's retry/failure accounting sees it.
        raise
    return resources


def _sweep_cloud_control(session: Any, region: str) -> list[NormalizedResource]:
    """Fills gaps in the Tagging API's coverage for a small supplementary type list
    (research.md R-201's "iterated over the CloudFormation resource-type registry",
    scoped to demo scale -- see `_CLOUD_CONTROL_SUPPLEMENTARY_TYPES`)."""
    from botocore.exceptions import BotoCoreError, ClientError

    client = session.client("cloudcontrol", region_name=region)
    resources: list[NormalizedResource] = []
    for type_name in _CLOUD_CONTROL_SUPPLEMENTARY_TYPES:
        try:
            paginator = client.get_paginator("list_resources")
            for page in paginator.paginate(TypeName=type_name):
                for item in page.get("ResourceDescriptions", []):
                    identifier = item["Identifier"]
                    resources.append(
                        NormalizedResource(
                            provider="aws",
                            account_id="",
                            resource_id=identifier,
                            service=type_name.split("::")[1].lower(),
                            resource_type=type_name,
                            region=region,
                            name=None,
                            tags={},
                            state=None,
                            created_at=None,
                        )
                    )
        except (ClientError, BotoCoreError):
            # One unsupported/inaccessible type must not fail the whole sweep -- the
            # Tagging API sweep already covers the common case; this is best-effort
            # supplementary coverage (research.md R-201's VERIFY note on Cloud
            # Control's real gap list applies here).
            continue
    return resources


def discover(account: ConnectorAccount, region: str) -> list[NormalizedResource]:
    """Combined, deduplicated whole-account discovery for one region (FR-016, FR-017).

    A free function for callers (tests, or a future stateless use) that don't need
    the enrichment session `AwsConnector` caches -- delegates to a throwaway instance
    so the sweep logic is written once. Deduplicates by ARN within this call (a
    resource the Tagging API sweep already found is not re-added if Cloud Control
    also lists it). Cross-*region* dedup for genuinely global resources like S3
    buckets (FR-018) is NOT this function's job -- it has no visibility into other
    regions' results, since the orchestrator invokes it once per (account, region)
    unit of work (research.md R-211). That dedup is the persistence layer's job in
    Phase 6, via `resource`'s `UNIQUE(tenant_id, arn)` constraint: a global resource
    discovered again from a second region updates `last_seen_at` rather than
    inserting a second row.
    """
    return AwsConnector().discover(account, region)


# --- Targeted enrichment for the six P1 governance-critical types (FR-019, R-202) --


def _enrich_ec2_instance(session: Any, resource: NormalizedResource) -> dict[str, Any]:
    instance_id = resource.resource_id.rsplit("/", 1)[-1]
    ec2 = session.client("ec2", region_name=resource.region)
    reservations = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"]
    instance = reservations[0]["Instances"][0]
    return {
        "instance_type": instance.get("InstanceType"),
        "state": instance.get("State", {}).get("Name"),
        "launch_time": str(instance.get("LaunchTime", "")),
        "vpc_id": instance.get("VpcId"),
        "subnet_id": instance.get("SubnetId"),
        "attached_volume_ids": [
            m["Ebs"]["VolumeId"] for m in instance.get("BlockDeviceMappings", []) if "Ebs" in m
        ],
    }


def _enrich_ebs_volume(session: Any, resource: NormalizedResource) -> dict[str, Any]:
    volume_id = resource.resource_id.rsplit("/", 1)[-1]
    ec2 = session.client("ec2", region_name=resource.region)
    volume = ec2.describe_volumes(VolumeIds=[volume_id])["Volumes"][0]
    attachments = volume.get("Attachments", [])
    return {
        "size_gib": volume.get("Size"),
        "volume_type": volume.get("VolumeType"),
        "state": volume.get("State"),
        "attached_instance_id": attachments[0]["InstanceId"] if attachments else None,
        "encrypted": volume.get("Encrypted"),
    }


def _enrich_elastic_ip(session: Any, resource: NormalizedResource) -> dict[str, Any]:
    allocation_id = resource.resource_id.rsplit("/", 1)[-1]
    ec2 = session.client("ec2", region_name=resource.region)
    addresses = ec2.describe_addresses(AllocationIds=[allocation_id])["Addresses"][0]
    return {
        "public_ip": addresses.get("PublicIp"),
        "association_state": "associated" if addresses.get("AssociationId") else "unassociated",
        "associated_instance_id": addresses.get("InstanceId"),
    }


def _enrich_s3_bucket(session: Any, resource: NormalizedResource) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    bucket_name = resource.resource_id.rsplit(":", 1)[-1]
    s3 = session.client("s3")
    detail: dict[str, Any] = {}
    try:
        location = s3.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
        detail["region"] = location or "us-east-1"
    except ClientError:
        detail["region"] = resource.region
    try:
        versioning = s3.get_bucket_versioning(Bucket=bucket_name)
        detail["versioning_status"] = versioning.get("Status", "Disabled")
    except ClientError:
        detail["versioning_status"] = None
    try:
        s3.get_bucket_encryption(Bucket=bucket_name)
        detail["encryption"] = True
    except ClientError:
        detail["encryption"] = False
    return detail


def _enrich_rds_instance(session: Any, resource: NormalizedResource) -> dict[str, Any]:
    db_id = resource.resource_id.rsplit(":", 1)[-1]
    rds = session.client("rds", region_name=resource.region)
    instance = rds.describe_db_instances(DBInstanceIdentifier=db_id)["DBInstances"][0]
    return {
        "engine": instance.get("Engine"),
        "instance_class": instance.get("DBInstanceClass"),
        "status": instance.get("DBInstanceStatus"),
        "multi_az": instance.get("MultiAZ"),
        "storage_gib": instance.get("AllocatedStorage"),
    }


def _enrich_lambda_function(session: Any, resource: NormalizedResource) -> dict[str, Any]:
    function_name = resource.resource_id.rsplit(":", 1)[-1]
    lambda_client = session.client("lambda", region_name=resource.region)
    config = lambda_client.get_function(FunctionName=function_name)["Configuration"]
    return {
        "runtime": config.get("Runtime"),
        "memory_mb": config.get("MemorySize"),
        "timeout_seconds": config.get("Timeout"),
        "last_modified": config.get("LastModified"),
        "state": config.get("State"),
    }


# Names here MUST match `enrichment_function` values in coverage_definitions.json
# (app/scan/coverage.py's data-driven registry, FR-021) -- the seam that lets a new
# type ship as a data change plus one new function, never an if/elif rewrite.
ENRICHMENT_FUNCTIONS: dict[str, Callable[[Any, NormalizedResource], dict[str, Any]]] = {
    "enrich_ec2_instance": _enrich_ec2_instance,
    "enrich_ebs_volume": _enrich_ebs_volume,
    "enrich_elastic_ip": _enrich_elastic_ip,
    "enrich_s3_bucket": _enrich_s3_bucket,
    "enrich_rds_instance": _enrich_rds_instance,
    "enrich_lambda_function": _enrich_lambda_function,
}


class AwsConnector:
    """The one connector implementation this spec ships (FR-014, data-model.md).

    Stateful by construction, not by accident: the `Connector` protocol's
    `enrich(resource) -> NormalizedResource` takes no account parameter, but
    enrichment needs a live AWS session to make its describe call. One connector
    instance is built per (account, region) unit of work (research.md R-211), so
    `discover()` runs first, caches the session and account it built, and `enrich()`
    reuses both -- the natural lifetime of one Step Functions Map iteration.
    """

    def __init__(self) -> None:
        self._session: Any = None

    def discover(self, account: ConnectorAccount, region: str) -> list[NormalizedResource]:
        self._session = _build_session(account, session_name="cloudpulse-scan")
        tagged = _sweep_tagging_api(self._session, region)
        seen_arns = {r.resource_id for r in tagged}
        supplementary = [
            r for r in _sweep_cloud_control(self._session, region) if r.resource_id not in seen_arns
        ]
        return tagged + supplementary

    def enrich(self, resource: NormalizedResource) -> NormalizedResource:
        """Look up and run the resource type's enrichment function (FR-021, R-202).

        A resource type with no registered coverage (anything outside the six P1
        types, until Phase 8's FR-020 extension) is returned unchanged -- absence of
        enrichment is expected behavior, not an error (FR-016 already guarantees the
        resource itself was found; enrichment depth is a separate, narrower promise).
        """
        if self._session is None:
            raise RuntimeError("enrich() called before discover() -- no session to reuse")

        from app.scan.coverage import load_coverage_definitions, resolve_enrichment_function

        definitions = load_coverage_definitions()
        fn = resolve_enrichment_function(resource.resource_type, definitions, ENRICHMENT_FUNCTIONS)
        if fn is None:
            return resource

        detail = fn(self._session, resource)
        # Frozen dataclass (FR-014's shape) -- replace() returns a new record rather
        # than mutating the one callers may still hold a reference to.
        return replace(resource, detail={**resource.detail, **detail})


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


# --- ExternalId secret storage (FR-003a, Principle III) --------------------
#
# The platform generates this value itself (never accepts an admin-supplied one) and
# stores only a Secrets Manager ARN reference on `cloud_account.external_id_ref`. The
# plaintext value is never a column, never logged, and only ever held in memory for
# the life of one registration or scan unit of work (research.md R-206).


def store_external_id(*, tenant_id: str, cloud_account_id: str, external_id: str) -> str:
    """Write the value to Secrets Manager and return its ARN."""
    import boto3

    client = boto3.client("secretsmanager")
    name = f"cloudpulse/external-id/{tenant_id}/{cloud_account_id}"
    response = client.create_secret(
        Name=name, SecretString=json.dumps({"external_id": external_id})
    )
    return str(response["ARN"])


def read_external_id(secret_arn: str) -> str:
    """Fetch the plaintext value. Never logged, never returned in an API response."""
    import boto3

    client = boto3.client("secretsmanager")
    payload = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    return str(payload["external_id"])


def delete_external_id(secret_arn: str) -> None:
    """Remove the secret, e.g. as part of account teardown (research.md R-208)."""
    import boto3

    boto3.client("secretsmanager").delete_secret(
        SecretId=secret_arn, ForceDeleteWithoutRecovery=True
    )


__all__ = [
    "VerificationOutcome",
    "verify_access",
    "get_local_account_id",
    "discover",
    "AwsConnector",
    "ENRICHMENT_FUNCTIONS",
    "store_external_id",
    "read_external_id",
    "delete_external_id",
]
