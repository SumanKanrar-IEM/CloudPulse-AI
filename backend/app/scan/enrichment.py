"""Targeted enrichment orchestration for the six P1 governance-critical types
(FR-019, research.md R-202).

No AWS SDK import here either (same boundary as discovery.py) -- the six describe
calls live in `connectors/aws.py`, dispatched by resource type through
`app/scan/coverage.py`'s data-driven registry (FR-021, T036). This module just runs
that dispatch over a batch of discovered resources.
"""

from __future__ import annotations

from connectors.base import Connector, NormalizedResource


def enrich_resources(
    resources: list[NormalizedResource],
    *,
    connector: Connector,
) -> list[NormalizedResource]:
    """Enrich every resource whose type has registered coverage; pass the rest
    through unchanged (FR-020/FR-021: absence of coverage is not an error).

    `connector` must be the same instance `discovery.py` called `discover()` on --
    it caches the AWS session enrichment reuses (connectors/aws.py's
    `AwsConnector` docstring explains why the `Connector` protocol is stateful here).
    """
    return [connector.enrich(resource) for resource in resources]


__all__ = ["enrich_resources"]
