"""The FastAPI application (FR-047, FR-048).

The OpenAPI document generated from this app is the **binding contract** between
frontend and backend (Principle V). It is generated in CI, never hand-written — that
is what stops it drifting from the Pydantic models and makes it a contract rather than
documentation.

Contract rules enforced elsewhere but worth stating here, because they constrain what
may be added to this app:

* **FR-048a** -- one unversioned document, additive changes only.
* **FR-048b** -- CI fails on a removed/renamed field, a removed endpoint, a
  newly-required parameter, or a narrowed type.
* **FR-048c / FR-057** -- a genuinely necessary break ships as add-new then
  remove-old, per ``ops/runbooks/contract-changes.md``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import health, me

DESCRIPTION = """\
Serverless cloud governance, cost, and compliance platform for AWS.

Every endpoint except `/health` requires a Cognito-issued bearer token. The caller's
role is derived from directory group membership on every request and is never stored by
the platform (FR-031a). A token whose group claim contains zero or more than one mapped
group is refused (FR-032a).
"""


def create_app() -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton, so tests can construct an isolated
    instance without inheriting state from an earlier one.
    """
    app = FastAPI(
        title="CloudPulse AI API",
        version="0.1.0",
        description=DESCRIPTION,
        # No version prefix: FR-048a specifies one evolving, unversioned document.
        # A /v1 prefix would be theatre in a build with a single consumer.
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )

    # Order matters. Correlation runs outermost so the id exists before any handler
    # can need it -- including the exception handlers, which put it in the envelope.
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    _apply_security_scheme(app)

    app.include_router(health.router)
    app.include_router(me.router)
    # Routers added by later specs: accounts (002), findings/rules/sda (003),
    # dashboard reads (004), cost (005), agent-facing reads (006, FR-056).

    return app


def _apply_security_scheme(app: FastAPI) -> None:
    """Declare Cognito bearer auth globally, with /health opting out.

    Declared in the contract now even though enforcement arrives in Phase 7 (T089).
    The generated document is what specs 002-006 build clients against, so getting the
    security model into it early means a later endpoint inherits the requirement by
    default rather than having to remember it -- there is no default-permit (FR-033a).
    """
    base_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = base_openapi()
        schema.setdefault("components", {})["securitySchemes"] = {
            "cognitoJwt": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Cognito-issued access token. Validated by the API Gateway JWT "
                    "authorizer, then re-validated for role cardinality by the "
                    "application (research.md R-004)."
                ),
            }
        }
        # Every operation requires auth unless it explicitly opts out.
        schema["security"] = [{"cognitoJwt": []}]
        for path, operations in schema.get("paths", {}).items():
            for operation in operations.values():
                if isinstance(operation, dict) and path in PUBLIC_PATHS:
                    operation["security"] = []
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


# FR-033a: /health is reachable without authentication; nothing else is.
PUBLIC_PATHS = frozenset({"/health"})

app = create_app()


def openapi_document() -> dict[str, Any]:
    """The contract, for CI generation and the oasdiff gate (FR-048, R-008)."""
    return app.openapi()


__all__ = ["app", "create_app", "openapi_document"]
