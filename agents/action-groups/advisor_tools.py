"""Action-group Lambda for the coverage advisor agent (spec 006, T035; FR-015,
FR-015a, FR-056, R-602).

Reads the tenant's inventory and its existing tagging rules -- enough to
describe a gap in terms of the resources it actually affects, and to draft a
rule extension that does not restate one already in force.

**No coverage-proposal endpoint in the allowlist, deliberately.** The advisor
must not read which gaps an admin has already rejected. Deduplication against
decided types is the platform's job and happens before this agent is called
(FR-018); giving the agent that history would only let it argue with a decision
it has no standing to revisit.

**No spend or findings endpoints either.** The advisor's prompt forbids stating
figures it was not handed, so an endpoint returning amounts would offer it only
something it must not use.
"""

from __future__ import annotations

from typing import Any

import _platform_api

# Must match `agents/definitions/advisor.json`'s action-group schema.
ALLOWED_PATHS: frozenset[str] = frozenset({"/resources", "/rules"})


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return _platform_api.call(event, ALLOWED_PATHS)


__all__ = ["ALLOWED_PATHS", "handler"]
