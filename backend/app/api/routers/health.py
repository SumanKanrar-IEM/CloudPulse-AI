"""Health endpoint (FR-041, FR-042).

Public — the only unauthenticated operation in the contract (FR-033a).

FR-042 is the requirement worth reading twice: when a dependency is unreachable the
endpoint MUST report unhealthy, **rather than reporting healthy or failing to respond**.
Both of those are worse than an honest 503. A load balancer that gets a timeout cannot
distinguish "slow" from "dead", and a health check that reports healthy while the
database is down is actively misleading.

So the dependency check is bounded by a timeout and every failure is caught: this
endpoint answers, always, and tells the truth.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.errors import ERROR_RESPONSES
from app.core.config import get_settings
from app.core.logging import logger

router = APIRouter(tags=["system"])

# Bounded so an unreachable dependency produces a fast 503 rather than a hung request.
DEPENDENCY_TIMEOUT_SECONDS = 2.0


class DependencyCheck(BaseModel):
    name: str
    status: Literal["healthy", "unhealthy"]
    detail_message: str | None = Field(
        default=None,
        alias="detailMessage",
        description="Never contains credentials, connection strings, or secrets (FR-046).",
    )

    model_config = {"populate_by_name": True}


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    checks: list[DependencyCheck]
    correlation_id: str = Field(alias="correlationId")
    version: str | None = None

    model_config = {"populate_by_name": True}


def _check_database_sync() -> DependencyCheck:
    """``SELECT 1`` against the governance store."""
    try:
        from app.core.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return DependencyCheck(name="database", status="healthy")
    except Exception as exc:
        # The exception text can carry a host, a username, or a connection string.
        # FR-046 forbids those in logs and the contract forbids them in the response,
        # so only the exception *type* is surfaced.
        logger.warning("database health check failed", extra={"error_type": type(exc).__name__})
        return DependencyCheck(
            name="database",
            status="unhealthy",
            detailMessage=f"unreachable ({type(exc).__name__})",
        )


async def _check_database() -> DependencyCheck:
    """Bounded, and total.

    Catches *every* exception, not just TimeoutError. FR-042 forbids "failing to
    respond" as much as it forbids a false healthy, and an unhandled error inside the
    check itself would surface as a 500 -- which is failing to respond. The health
    endpoint must always answer, and must always tell the truth.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_check_database_sync), timeout=DEPENDENCY_TIMEOUT_SECONDS
        )
    except TimeoutError:
        return DependencyCheck(
            name="database",
            status="unhealthy",
            detailMessage=f"timed out after {DEPENDENCY_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        logger.warning("database health check errored", extra={"error_type": type(exc).__name__})
        return DependencyCheck(
            name="database",
            status="unhealthy",
            detailMessage=f"check failed ({type(exc).__name__})",
        )


@router.get(
    "/health",
    operation_id="getHealth",
    summary="Service and dependency health",
    response_model=HealthResponse,
    response_model_by_alias=True,
    responses={
        503: {
            "model": HealthResponse,
            "description": "At least one dependency is unreachable (FR-042)",
        },
        # Pulls ErrorEnvelope into the generated contract so consumers get a typed
        # error shape (FR-043, FR-048). /health is public, so 401/403 do not apply --
        # only the failure kinds it can actually produce are declared.
        500: ERROR_RESPONSES[500],
    },
)
async def get_health(request: Request, response: Response) -> dict[str, Any]:
    """Report this service's health and that of its dependencies."""
    checks = [await _check_database()]
    healthy = all(c.status == "healthy" for c in checks)

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    settings = None
    try:
        settings = get_settings()
    except Exception:  # configuration itself may be incomplete; still answer
        pass

    return HealthResponse(
        status="healthy" if healthy else "unhealthy",
        checks=checks,
        correlationId=str(getattr(request.state, "correlation_id", "")),
        version=settings.git_sha if settings else None,
    ).model_dump(by_alias=True, exclude_none=True)


__all__ = ["router", "HealthResponse", "DependencyCheck"]
