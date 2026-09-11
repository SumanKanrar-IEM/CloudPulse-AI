"""Coverage-as-data loader (FR-021, FR-022, research.md R-203).

Which resource types receive deep enrichment, and what they capture, is data -- a
versioned JSON file in the repository, deployed through the normal CI/CD pipeline
(research.md R-203) -- never a hardcoded Python dict (FR-021) and never a live
admin-editable table.

**Deliberately uncached, unlike `app.core.config.get_settings`.** FR-022 requires a
coverage change to take effect starting with the *next* scan that begins after the
change, and never alter a scan already in progress. A process-lifetime cache (as
Settings uses, since Settings genuinely cannot change without a redeploy) would risk
serving stale data across scans within one warm Lambda execution context if this file
were ever hot-reloaded -- it currently is not, since it ships in the deployment
package, but reading fresh on every scan-orchestration call keeps that guarantee true
regardless of how the file reaches disk, and the read itself is cheap (a few KB).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DEFINITIONS_PATH = Path(__file__).with_name("coverage_definitions.json")
DEFAULT_CANDIDATES_PATH = Path(__file__).with_name("enricher_candidates.json")


@dataclass(frozen=True, slots=True)
class CoverageDefinition:
    """One resource type's enrichment configuration."""

    resource_type: str
    enrichment_function: str
    fields: tuple[str, ...]


def load_coverage_definitions(
    path: Path = DEFAULT_DEFINITIONS_PATH,
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, CoverageDefinition]:
    """Read the coverage-definition file fresh (FR-021, FR-022), then lay a
    tenant's accepted coverage proposals over it (spec 006, FR-017).

    Raises ``ValueError`` on a malformed entry rather than skipping it silently -- a
    scan that silently drops enrichment for a resource type is worse than one that
    fails loudly at orchestration time, before any AWS call is made.

    `overrides` maps resource type to enrichment-function name, from
    `governance.coverage_advisor.accepted_coverage_overrides`. Merged at read time
    rather than written into the file: the file ships in the deployment package and
    is the same for every tenant, and an accepted proposal is one tenant's decision.
    The file wins on conflict -- an override for a type already covered would be a
    proposal the advisor should never have raised, and the shipped definition is the
    one with a reviewer attached.
    """
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    definitions: dict[str, CoverageDefinition] = {}
    for resource_type, entry in raw.items():
        if "enrichment_function" not in entry or "fields" not in entry:
            raise ValueError(
                f"coverage definition for {resource_type!r} is missing "
                f"'enrichment_function' or 'fields'"
            )
        definitions[resource_type] = CoverageDefinition(
            resource_type=resource_type,
            enrichment_function=entry["enrichment_function"],
            fields=tuple(entry["fields"]),
        )
    for resource_type, function_name in (overrides or {}).items():
        # `fields` is what the shipped definition documents about its enricher;
        # an accepted proposal names only the function. Empty is honest here --
        # nothing reads `fields` at enrichment time, and inventing a list would
        # document coverage nobody reviewed.
        definitions.setdefault(
            resource_type,
            CoverageDefinition(
                resource_type=resource_type, enrichment_function=function_name, fields=()
            ),
        )
    return definitions


def load_enricher_candidates(path: Path = DEFAULT_CANDIDATES_PATH) -> dict[str, str]:
    """Resource types an *existing* enricher would suit but that are not yet in
    `coverage_definitions.json` (spec 006, FR-015, R-603 class 2).

    This is the coverage advisor's only source of proposable gaps: a type here
    whose function is in the registry becomes a proposal an admin can accept,
    and acceptance lands as an override on the next scan (FR-017). Coverage as
    data, same as the definitions file -- an entry is a reviewed statement that
    "this routine fits this type", not something inferred from a function name.

    Empty today, and honestly so: `connectors/aws.py`'s enrichers are tied 1:1
    to the types the definitions file already covers. An entry appears here the
    day someone adds an enricher without mapping it, which is the normal way a
    proposable gap comes to exist.
    """
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for resource_type, function_name in raw.items():
        if not isinstance(function_name, str) or not function_name:
            raise ValueError(f"enricher candidate for {resource_type!r} must name a function")
    return {str(k): str(v) for k, v in raw.items()}


def resolve_enrichment_function(
    resource_type: str,
    definitions: dict[str, CoverageDefinition],
    registry: dict[str, Callable[..., dict[str, Any]]],
) -> Callable[..., dict[str, Any]] | None:
    """Look up the enrichment callable for one resource type, or None if uncovered.

    The data-driven seam FR-021 requires: adding a resource type to
    `coverage_definitions.json` plus one new function in `enrichment.py`'s registry
    is a data change, not an if/elif rewrite (research.md R-202).
    """
    definition = definitions.get(resource_type)
    if definition is None:
        return None
    return registry.get(definition.enrichment_function)


__all__ = [
    "CoverageDefinition",
    "load_coverage_definitions",
    "load_enricher_candidates",
    "resolve_enrichment_function",
    "DEFAULT_DEFINITIONS_PATH",
]
