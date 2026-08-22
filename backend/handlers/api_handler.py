"""Lambda entrypoint for the API (FR-047).

Mangum adapts the ASGI app to API Gateway's HTTP API payload format. The handler is
kept trivial on purpose: everything testable lives in ``app.api``, so the Lambda
boundary itself has nothing worth mocking.
"""

from __future__ import annotations

from mangum import Mangum

from app.api.main import app

# api_gateway_base_path is unset: the HTTP API is mounted at the stage root, so paths
# reach the app unmodified.
handler = Mangum(app, lifespan="off")

__all__ = ["handler"]
