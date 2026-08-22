"""Every failure kind returns the identical envelope (FR-043, SC-009).

SC-009 requires 100% conformance across all endpoints and all failure kinds. These
tests exercise each kind through the real application rather than calling the builder
directly — a route that bypassed the handlers would still pass a unit test of the
builder, which is exactly the regression worth catching.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException, Query
from fastapi.testclient import TestClient

from app.api.errors import AppError, ErrorCode
from app.api.main import create_app

ENVELOPE_KEYS = {"code", "message", "correlationId"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An app with one route per failure kind, wired through the real handlers."""
    app = create_app()

    @app.get("/_t/validation")
    async def _validation(n: int = Query()) -> dict[str, int]:  # noqa: B008
        return {"n": n}

    @app.get("/_t/{code}")
    async def _http(code: int) -> None:
        raise HTTPException(status_code=code, detail="secret record 12345 does not exist")

    @app.get("/_t/app/forbidden")
    async def _app_error() -> None:
        raise AppError(ErrorCode.FORBIDDEN, status_code=403)

    @app.get("/_t/unhandled/boom")
    async def _boom() -> None:
        raise RuntimeError("psycopg: password authentication failed for user 'admin'")

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/_t/validation", 422, "VALIDATION_FAILED"),
        ("/_t/401", 401, "UNAUTHORIZED"),
        ("/_t/403", 403, "FORBIDDEN"),
        ("/_t/404", 404, "NOT_FOUND"),
        ("/_t/app/forbidden", 403, "FORBIDDEN"),
        ("/_t/unhandled/boom", 500, "INTERNAL_ERROR"),
    ],
)
def test_every_failure_kind_uses_the_same_envelope(
    client: TestClient, path: str, expected_status: int, expected_code: str
) -> None:
    """SC-009: one shape, every kind."""
    response = client.get(path)
    assert response.status_code == expected_status

    body = response.json()
    assert set(body) == {"error"}, f"envelope must wrap a single 'error' object: {body}"
    assert ENVELOPE_KEYS <= set(body["error"])
    assert body["error"]["code"] == expected_code
    uuid.UUID(body["error"]["correlationId"])  # raises if not a UUID


def test_validation_failure_reports_the_offending_field(client: TestClient) -> None:
    """`details` is present for validation failures and field-scoped."""
    body = client.get("/_t/validation").json()
    details = body["error"]["details"]
    assert details and {"field", "issue"} <= set(details[0])
    assert details[0]["field"] == "n"


def test_details_is_absent_for_non_validation_failures(client: TestClient) -> None:
    """FR-048b: `details` must stay optional.

    Making it always present would be a narrowing change to every non-validation
    response at once.
    """
    assert "details" not in client.get("/_t/404").json()["error"]


def test_not_found_does_not_leak_what_was_looked_for(client: TestClient) -> None:
    """FR-035: a 404 must not reveal whether a given record exists.

    The route raises with a detail naming a record id; the handler must discard it.
    """
    raw = client.get("/_t/404").text
    assert "12345" not in raw
    assert "secret record" not in raw


def test_internal_error_leaks_no_driver_detail(client: TestClient) -> None:
    """A stack trace or driver message in a response body is an information leak."""
    raw = client.get("/_t/unhandled/boom").text
    for leak in ("psycopg", "password authentication", "admin", "Traceback"):
        assert leak not in raw, f"500 response leaked {leak!r}"


def test_error_responses_echo_the_correlation_header(client: TestClient) -> None:
    """FR-044: the id in the body matches the header, on errors too."""
    response = client.get("/_t/404")
    assert response.json()["error"]["correlationId"] == response.headers["X-Correlation-Id"]


def test_error_codes_are_screaming_snake_case() -> None:
    """The contract fixes the casing; a rename is a breaking change (FR-048b)."""
    for code in ErrorCode:
        assert code.value.isupper()
        assert " " not in code.value
