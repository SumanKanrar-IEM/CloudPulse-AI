"""The AWS connector implementation (FR-014). `discover`/`enrich` land in Phase 5 (T034).

This file also holds the AWS-SDK-touching operations account registration needs --
role verification (FR-007) and ExternalId secret storage (FR-003a, Principle III) --
since both legitimately belong behind the connector boundary
(`ops/scripts/check_connector_boundary.py`): verification reaches into a *scanned*
account exactly like discovery does, and the secret it stores exists only to make
that reach possible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from connectors.base import ConnectorAccount

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


def verify_access(account: ConnectorAccount, region: str) -> VerificationOutcome:
    """Attempt a real, read-only action against the target account (FR-007).

    Uses `resourcegroupstaggingapi:GetResources` with a one-item page as the read
    check -- the exact permission whole-account discovery (R-201) depends on, so a
    verified account is proven to support the platform's actual core capability, not
    merely "can assume a role."
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    if account.connection_mode == "assume_role":
        if not account.role_arn:
            return VerificationOutcome("role_not_assumable", "no role reference supplied")
        sts = boto3.client("sts")
        try:
            assumed = sts.assume_role(
                RoleArn=account.role_arn,
                RoleSessionName="cloudpulse-verify",
                ExternalId=account.external_id,
                DurationSeconds=900,
            )
        except (ClientError, BotoCoreError) as exc:
            return VerificationOutcome("role_not_assumable", _error_code(exc))

        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    else:
        session = boto3.Session()

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
    "store_external_id",
    "read_external_id",
    "delete_external_id",
]
