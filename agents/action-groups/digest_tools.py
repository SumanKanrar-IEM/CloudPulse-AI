"""Tool allowlist for the digest agent (spec 006, T016; FR-003, R-602).

The lookups themselves live in `_platform_api`, shared with the suggester's
action group. What is specific to this capability is the allowlist below, and it
is deliberately short: `agents/definitions/README.md` requires every operation to
be backed by an endpoint specs 002-005 already ship, and an agent that can read
more of the platform than its prompt needs is an agent whose blast radius is
larger than its job.
"""

from __future__ import annotations

# Under AgentCore this module is only the allowlist: `agents/runtime/main.py`
# serves the tool calls and consults it (T064).
# Must match `agents/definitions/digest.json`'s tool schema. Listed
# again rather than read from that file: the schema is what the model is told it
# may call, and this is what the function will actually perform. They should
# agree, and a disagreement should fail closed here rather than be impossible to
# express.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {"/findings", "/resources/{resource_id}", "/spend/summary"}
)


__all__ = ["ALLOWED_PATHS"]
