# Breaks: connector-boundary (FR-054). Provider SDK imported outside connectors/.
# Verified: ops/scripts/check_connector_boundary.py exits 1 on this, 0 once removed.
import boto3

def list_buckets() -> list[str]:
    return [b["Name"] for b in boto3.client("s3").list_buckets()["Buckets"]]
