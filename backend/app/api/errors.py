"""The uniform error envelope (FR-043).

Every error response from every endpoint — including those specs 002–006 add later —
uses this shape. Registering handlers centrally rather than returning error bodies from
route code is what makes SC-009's "100% of error responses conform" achievable: a route
cannot accidentally invent its own shape, because routes do not build error bodies at
all.

FR-035 is enforced here too: a 404 to an unentitled caller must be indistinguishable
from a 404 for a genuinely missing record, so the message is fixed rather than
describing what was looked for.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import logger


class ErrorCode(StrEnum):
    """Stable, machine-readable codes. SCREAMING_SNAKE_CASE per the contract.

    These are part of the API contract: renaming one is a breaking change under
    FR-048b, the same as renaming a field.
    """

    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_FAILED,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_FAILED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}

# FR-035: fixed text, so a caller cannot distinguish "does not exist" from "exists but
# is not yours" by reading the message.
_SAFE_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_FAILED: "The request could not be validated.",
    ErrorCode.UNAUTHORIZED: "Authentication is required.",
    ErrorCode.FORBIDDEN: "You do not have permission to perform this action.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.CONFLICT: "The request conflicts with the current state.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred.",
    ErrorCode.SERVICE_UNAVAILABLE: "The service is temporarily unavailable.",
}


class ErrorDetail(BaseModel):
    """One field-level validation problem."""

    field: str
    issue: str


class ErrorBody(BaseModel):
    code: str = Field(description="Stable and machine-readable. SCREAMING_SNAKE_CASE.")
    message: str = Field(
        description=(
            "Human-readable and safe to display. Never reveals whether a given record "
            "exists to a caller not entitled to know (FR-035)."
        )
    )
    correlation_id: str = Field(
        alias="correlationId",
        description="Matches the id in the structured logs for this request (FR-044).",
    )
    details: list[ErrorDetail] | None = Field(
        default=None, description="Field-level detail. Present for validation failures only."
    )

    model_config = {"populate_by_name": True}


class ErrorEnvelope(BaseModel):
    """The uniform error envelope (FR-043).

    Declared as a model, not just built as a dict, so it appears in the **generated**
    OpenAPI document -- which FR-048 makes the binding contract. An envelope that only
    exists at runtime would be invisible to the generated client, leaving every
    consumer to hand-roll the error type.
    """

    error: ErrorBody


# Reusable response declarations, so every route added by specs 002-006 documents the
# same shapes without restating them.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorEnvelope, "description": "No valid identity presented."},
    403: {
        "model": ErrorEnvelope,
        "description": (
            "Valid identity, but the caller's role does not permit the action -- or the "
            "caller maps to zero or multiple directory groups and therefore has no "
            "resolvable role (FR-032a, FR-034)."
        ),
    },
    404: {
        "model": ErrorEnvelope,
        "description": (
            "Target record does not exist, or the caller is not entitled to know that "
            "it does."
        ),
    },
    422: {"model": ErrorEnvelope, "description": "Request body or parameters failed validation."},
    500: {"model": ErrorEnvelope, "description": "Unexpected server error."},
}


class AppError(Exception):
    """Raise this rather than returning an error body from a route."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        status_code: int,
        message: str | None = None,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.message = message or _SAFE_MESSAGES[code]
        self.details = details
        super().__init__(self.message)


def correlation_id_of(request: Request) -> uuid.UUID:
    """The id assigned by the middleware (FR-044).

    Falls back to a fresh id so an error response is never emitted without one — an
    error the caller cannot correlate to a log line is barely better than no error.
    """
    existing = getattr(request.state, "correlation_id", None)
    return existing if isinstance(existing, uuid.UUID) else uuid.uuid4()


def build_envelope(
    code: ErrorCode,
    message: str,
    correlation_id: uuid.UUID,
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """The one envelope shape. Matches contracts/openapi.yaml exactly."""
    error: dict[str, Any] = {
        "code": code.value,
        "message": message,
        "correlationId": str(correlation_id),
    }
    if details:
        error["details"] = details
    return {"error": error}


def _respond(
    request: Request,
    code: ErrorCode,
    status_code: int,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    correlation_id = correlation_id_of(request)
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(code, message, correlation_id, details),
        headers={"X-Correlation-Id": str(correlation_id)},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Route every failure through the single envelope path."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _respond(request, exc.code, exc.status_code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Strip the location kind (body/query/path/header/cookie) so the field name
        # is what a client developer actually needs to fix, not where FastAPI found it.
        location_kinds = {"body", "query", "path", "header", "cookie"}
        details = [
            {
                "field": ".".join(
                    str(part) for part in err.get("loc", ()) if part not in location_kinds
                )
                or "body",
                "issue": err.get("msg", "invalid"),
            }
            for err in exc.errors()
        ]
        return _respond(
            request,
            ErrorCode.VALIDATION_FAILED,
            422,  # UNPROCESSABLE_CONTENT; the starlette constant was renamed,
            _SAFE_MESSAGES[ErrorCode.VALIDATION_FAILED],
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        # Deliberately ignores exc.detail for 401/403/404: FastAPI's defaults describe
        # what was looked for, which is exactly the existence leak FR-035 forbids.
        message = _SAFE_MESSAGES[code]
        return _respond(request, code, exc.status_code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = correlation_id_of(request)
        # The detail goes to the logs, never to the caller: a stack trace or driver
        # message in a response body is an information leak.
        logger.exception(
            "unhandled exception",
            extra={"correlation_id": str(correlation_id), "path": request.url.path},
        )
        return _respond(
            request,
            ErrorCode.INTERNAL_ERROR,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            _SAFE_MESSAGES[ErrorCode.INTERNAL_ERROR],
        )


__all__ = [
    "AppError", "ErrorCode", "register_exception_handlers",
    "build_envelope", "correlation_id_of",
    "ErrorEnvelope", "ErrorBody", "ErrorDetail", "ERROR_RESPONSES",
]
