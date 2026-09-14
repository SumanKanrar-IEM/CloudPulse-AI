"""Tool allowlist for the suggester agent (spec 006, T024; FR-003, R-602).

Reads the one finding this invocation is about, its resource, and the rule it
failed -- the detail that makes a suggestion specific to the resource rather
than generic to its rule (FR-011).

**No spend endpoint here, unlike the digest's allowlist.** The suggester has no
platform-computed figures and its prompt forbids stating numbers, so an endpoint
returning amounts would only offer it something it must not use. Narrowing the
surface to what the prompt permits is cheaper than relying on the prompt alone.
"""

from __future__ import annotations

# Under AgentCore this module is only the allowlist: `agents/runtime/main.py`
# serves the tool calls and consults it (T064).
# Must match `agents/definitions/suggester.json`'s tool schema.
ALLOWED_PATHS: frozenset[str] = frozenset({"/findings", "/resources/{resource_id}", "/rules"})


__all__ = ["ALLOWED_PATHS"]
