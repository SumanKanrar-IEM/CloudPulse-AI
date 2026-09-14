"""Tool allowlist for the forecast narrator agent (spec 006, T053;
FR-024, FR-056, R-602).

One path. The narrator is handed every figure it may state in its prompt; the
forecast endpoint is here so it can read the projection's shape, and nothing
else is, because nothing else could be stated. A spend or metrics endpoint
would offer numbers the prompt never declared, and under FR-024 an undeclared
number discards the whole narrative -- so the narrowest surface is also the
one least likely to produce nothing.
"""

from __future__ import annotations

# Under AgentCore this module is only the allowlist: `agents/runtime/main.py`
# serves the tool calls and consults it (T064).
# Must match `agents/definitions/narrator.json`'s tool schema.
ALLOWED_PATHS: frozenset[str] = frozenset({"/forecasts"})


__all__ = ["ALLOWED_PATHS"]
