"""Action-group Lambda for the forecast narrator agent (spec 006, T053;
FR-024, FR-056, R-602).

One path. The narrator is handed every figure it may state in its prompt; the
forecast endpoint is here so it can read the projection's shape, and nothing
else is, because nothing else could be stated. A spend or metrics endpoint
would offer numbers the prompt never declared, and under FR-024 an undeclared
number discards the whole narrative -- so the narrowest surface is also the
one least likely to produce nothing.
"""

from __future__ import annotations

from typing import Any

import _platform_api

# Must match `agents/definitions/narrator.json`'s action-group schema.
ALLOWED_PATHS: frozenset[str] = frozenset({"/forecasts"})


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return _platform_api.call(event, ALLOWED_PATHS)


__all__ = ["ALLOWED_PATHS", "handler"]
