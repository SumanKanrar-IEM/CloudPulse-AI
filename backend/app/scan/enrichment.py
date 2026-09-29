"""Targeted enrichment orchestration for governance-critical resource types
(FR-019 P1, FR-020 P2, research.md R-202).

No AWS SDK import here either (same boundary as discovery.py) -- every describe
call lives in `connectors/aws.py`, dispatched by resource type through
`app/scan/coverage.py`'s data-driven registry (FR-021, T036). This module just runs
that dispatch over a batch of discovered resources, and needed no change at all to
pick up T056's four new P2 types -- exactly the extensibility SC-005 claims.
"""

from __future__ import annotations

from app.core.logging import logger
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
    enriched = [connector.enrich(resource) for resource in resources]
    failed = [r for r in enriched if "enrichment_error" in r.detail]
    if failed:
        # FR-021a: a failed enrichment no longer fails the unit, so it must not
        # vanish either -- one line per unit, with what failed and why.
        logger.warning(
            "enrichment failed for some resources; recorded without enrichment",
            extra={
                "failed_count": len(failed),
                "failures": sorted(
                    {f"{r.resource_type}: {r.detail['enrichment_error']}" for r in failed}
                ),
            },
        )
    return enriched


__all__ = ["enrich_resources"]
