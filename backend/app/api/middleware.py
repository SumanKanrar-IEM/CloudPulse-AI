"""Correlation identifiers and per-request structured logging (FR-044, FR-045).

An inbound ``X-Correlation-Id`` is accepted **only** if it is a well-formed UUID.
Anything else is discarded and a fresh one generated.

That validation is not tidiness. The header is caller-controlled, and writing it into a
structured log unchecked is a log-injection vector — a caller could forge log lines or
poison correlation for another request. The spec's "correlation identifier absent" edge
case requires exactly this: generate a trustworthy one rather than log a caller-supplied
value unchecked.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import logger

CORRELATION_HEADER = "X-Correlation-Id"


def _api_gateway_request_id(request: Request) -> str | None:
    """The id API Gateway's access log records for this same request (SC-010).

    The access log has no way to read back the app's own correlation id (HTTP APIs
    cannot reference an integration response from `$context`), so it logs its own
    `requestId` instead. Logging that same value here, alongside the app's
    `correlation_id`, is what lets the two log groups be cross-referenced by a shared
    field rather than leaving the access log's id orphaned.
    """
    scope_event = request.scope.get("aws.event") or {}
    request_id = scope_event.get("requestContext", {}).get("requestId")
    return str(request_id) if request_id else None


def parse_correlation_id(raw: str | None) -> tuple[uuid.UUID, bool]:
    """Return ``(id, inherited)``.

    ``inherited`` is True only when the caller supplied a well-formed UUID. A
    malformed or absent header yields a fresh id and False -- never the raw string.
    """
    if raw:
        try:
            return uuid.UUID(raw), True
        except (ValueError, AttributeError, TypeError):
            pass
    return uuid.uuid4(), False


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assign a correlation id, echo it, and log the request (FR-044, FR-045)."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id, inherited = parse_correlation_id(request.headers.get(CORRELATION_HEADER))
        request.state.correlation_id = correlation_id
        api_gateway_request_id = _api_gateway_request_id(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Log and re-raise: building the envelope is the exception handlers' job.
            # Two places constructing error bodies is how shapes diverge.
            logger.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "correlation_id": str(correlation_id),
                    "api_gateway_request_id": api_gateway_request_id,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[CORRELATION_HEADER] = str(correlation_id)

        # FR-045: structured, machine-parsable, with outcome and duration. The
        # formatter redacts (FR-046), so no field here needs sanitising by hand.
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "correlation_id": str(correlation_id),
                "correlation_inherited": inherited,
                "api_gateway_request_id": api_gateway_request_id,
            },
        )
        return response


__all__ = ["CorrelationIdMiddleware", "CORRELATION_HEADER", "parse_correlation_id"]
