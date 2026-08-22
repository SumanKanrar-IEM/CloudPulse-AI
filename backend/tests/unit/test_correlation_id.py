"""Correlation identifiers (FR-044, and the "correlation identifier absent" edge case).

The edge case requires that a caller-supplied identifier is never logged unchecked. That
is a security property, not tidiness: the header is caller-controlled, and writing it
into a structured log unvalidated is a log-injection vector — a caller could forge log
lines or poison correlation for someone else's request.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.middleware import CORRELATION_HEADER, parse_correlation_id
from app.api.routers import health


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        health, "_check_database_sync",
        lambda: health.DependencyCheck(name="database", status="healthy"),
    )
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def test_every_response_carries_a_correlation_id(client: TestClient) -> None:
    """FR-044: present in the response, always."""
    value = client.get("/health").headers[CORRELATION_HEADER]
    uuid.UUID(value)


def test_a_valid_inbound_id_is_honoured(client: TestClient) -> None:
    """Tracing across services only works if a well-formed id is preserved."""
    supplied = str(uuid.uuid4())
    response = client.get("/health", headers={CORRELATION_HEADER: supplied})
    assert response.headers[CORRELATION_HEADER] == supplied


@pytest.mark.parametrize(
    "malformed",
    [
        "not-a-uuid",
        "../../etc/passwd",
        '"; DROP TABLE audit_event; --',
        "\n[CRITICAL] forged log line",
        "%0d%0aInjected: header",
        "x" * 5000,
        "",
        "550e8400-e29b-41d4-a716",          # truncated UUID
        "<script>alert(1)</script>",
    ],
)
def test_a_malformed_inbound_id_is_discarded_and_replaced(
    client: TestClient, malformed: str
) -> None:
    """The edge case, exhaustively.

    Each of these is a plausible injection payload. None may survive into the response
    or the logs — the service generates a trustworthy id instead.
    """
    response = client.get("/health", headers={CORRELATION_HEADER: malformed})
    returned = response.headers[CORRELATION_HEADER]

    uuid.UUID(returned)                     # a real UUID was generated
    assert returned != malformed
    assert malformed not in response.text or not malformed


def test_parse_reports_whether_the_id_was_inherited() -> None:
    """The distinction matters for tracing: a fresh id starts a new trace."""
    _, inherited = parse_correlation_id(str(uuid.uuid4()))
    assert inherited is True

    generated, inherited = parse_correlation_id("garbage")
    assert inherited is False
    assert isinstance(generated, uuid.UUID)

    generated, inherited = parse_correlation_id(None)
    assert inherited is False
    assert isinstance(generated, uuid.UUID)


def test_the_id_in_the_body_matches_the_header(client: TestClient) -> None:
    """SC-010: one id ties the response to its log records."""
    response = client.get("/health")
    assert response.json()["correlationId"] == response.headers[CORRELATION_HEADER]


def test_each_request_gets_a_distinct_id(client: TestClient) -> None:
    """Reusing one id across requests would make traces unfollowable."""
    ids = {client.get("/health").headers[CORRELATION_HEADER] for _ in range(5)}
    assert len(ids) == 5


def test_error_responses_also_carry_the_id(client: TestClient) -> None:
    """An error a caller cannot correlate to a log line is barely better than none."""
    response = client.get("/no-such-route")
    assert response.status_code == 404
    assert response.json()["error"]["correlationId"] == response.headers[CORRELATION_HEADER]
