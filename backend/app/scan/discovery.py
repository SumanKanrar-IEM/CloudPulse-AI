"""Whole-account discovery orchestration (FR-016, FR-017, FR-018).

Contains no AWS SDK import (`ops/scripts/check_connector_boundary.py`, FR-054) --
the actual Tagging API / Cloud Control API calls live in
`connectors/aws.py::AwsConnector.discover`, which this module calls through the
`Connector` protocol (FR-014, Principle V). This file's job is turning a database
row into the connector's input shape and back.
"""

from __future__ import annotations

from connectors.base import Connector, ConnectorAccount, NormalizedResource


def discover_account_region(
    *,
    aws_account_id: str,
    connection_mode: str,
    role_arn: str | None,
    external_id: str | None,
    region: str,
    connector: Connector,
) -> list[NormalizedResource]:
    """One (account, region) unit of work's discovery sweep (research.md R-211).

    `external_id` is the resolved plaintext value (from
    `connectors.aws.read_external_id`), held only for the life of this call -- never
    logged, never persisted here (Principle III).

    `connector` is not defaulted: the caller (Phase 6's worker handler) owns one
    `AwsConnector()` instance for the whole unit of work and must pass the *same*
    instance to `enrichment.py::enrich_resources` afterward, since `AwsConnector`
    caches the AWS session `discover()` built for `enrich()` to reuse -- constructing
    a fresh connector here would silently hide that requirement from the caller.
    """
    account = ConnectorAccount(
        aws_account_id=aws_account_id,
        connection_mode=connection_mode,
        role_arn=role_arn,
        external_id=external_id,
    )
    return list(connector.discover(account, region))


__all__ = ["discover_account_region"]
