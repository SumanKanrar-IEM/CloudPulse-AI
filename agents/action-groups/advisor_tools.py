"""Action-group Lambda for the coverage advisor agent (spec 006, T035; FR-015,
FR-015a, FR-056, R-602).

Reads the tenant's inventory -- enough to describe a gap in terms of the
resources it actually affects.

**No coverage-proposal endpoint in the allowlist, deliberately.** The advisor
must not read which gaps an admin has already rejected. Deduplication against
decided types is the platform's job and happens before this agent is called
(FR-018); giving the agent that history would only let it argue with a decision
it has no standing to revisit.

**No spend or findings endpoints either.** The advisor's prompt forbids stating
figures it was not handed, so an endpoint returning amounts would offer it only
something it must not use. And no `/rules`: rules apply to every resource, so
they are never the fix for one type's coverage (R-603, class 1 struck), and an
agent that cannot draft one has no reason to read them.
"""

from __future__ import annotations

from typing import Any

import _platform_api

# Must match `agents/definitions/advisor.json`'s action-group schema.
ALLOWED_PATHS: frozenset[str] = frozenset({"/resources"})


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return _platform_api.call(event, ALLOWED_PATHS)


__all__ = ["ALLOWED_PATHS", "handler"]
