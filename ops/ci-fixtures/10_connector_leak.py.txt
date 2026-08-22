# Breaks: connector-boundary (FR-054). Provider SDK imported outside connectors/.
import boto3


def list_buckets() -> list[str]:
    return [b["Name"] for b in boto3.client("s3").list_buckets()["Buckets"]]
