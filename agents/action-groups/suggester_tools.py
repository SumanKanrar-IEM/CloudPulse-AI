"""Action-group Lambda for the suggester agent (spec 006, T024; FR-003, R-602).

Reads the one finding this invocation is about, its resource, and the rule it
failed -- the detail that makes a suggestion specific to the resource rather
than generic to its rule (FR-011).

**No spend endpoint here, unlike the digest's allowlist.** The suggester has no
platform-computed figures and its prompt forbids stating numbers, so an endpoint
returning amounts would only offer it something it must not use. Narrowing the
surface to what the prompt permits is cheaper than relying on the prompt alone.
"""

from __future__ import annotations

from typing import Any

import _platform_api

# Must match `agents/definitions/suggester.json`'s action-group schema.
ALLOWED_PATHS: frozenset[str] = frozenset({"/findings", "/resources/{resource_id}", "/rules"})


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return _platform_api.call(event, ALLOWED_PATHS)


__all__ = ["ALLOWED_PATHS", "handler"]
