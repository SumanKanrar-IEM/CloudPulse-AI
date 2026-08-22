"""Health endpoint behaviour (FR-041, FR-042).

FR-042 is the requirement these tests really pin down: when a dependency is unreachable
the endpoint must report **unhealthy**, rather than reporting healthy or failing to
respond. Both alternatives are worse than an honest 503 — a health check that lies is
more dangerous than one that is merely down.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.routers import health


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def healthy_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        health, "_check_database_sync",
        lambda: health.DependencyCheck(name="database", status="healthy"),
    )


@pytest.fixture
def broken_db(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise ConnectionRefusedError("could not connect to server at db.internal:5432")

    monkeypatch.setattr(health, "_check_database_sync", _boom)


def test_health_is_public(client: TestClient, healthy_db: None) -> None:
    """FR-033a: `/health` is the one unauthenticated operation."""
    assert client.get("/health").status_code == 200


def test_healthy_response_shape(client: TestClient, healthy_db: None) -> None:
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert {"status", "checks", "correlationId"} <= set(body)
    assert any(c["name"] == "database" for c in body["checks"])


def test_unhealthy_dependency_returns_503_not_200(
    client: TestClient, broken_db: None
) -> None:
    """FR-042: never report healthy while a dependency is down."""
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_unhealthy_dependency_still_answers(client: TestClient, broken_db: None) -> None:
    """FR-042: 'fails to respond' is explicitly not acceptable.

    A timeout is indistinguishable from a dead service, so the endpoint must always
    produce a body.
    """
    body = client.get("/health").json()
    assert body["checks"][0]["status"] == "unhealthy"
    assert body["checks"][0]["detailMessage"]


def test_health_detail_leaks_no_connection_string(
    client: TestClient, broken_db: None
) -> None:
    """FR-046: the driver error carries a host and port. Neither may surface."""
    raw = client.get("/health").text
    for leak in ("db.internal", "5432", "could not connect to server"):
        assert leak not in raw, f"health response leaked {leak!r}"


def test_health_carries_a_correlation_id(client: TestClient, healthy_db: None) -> None:
    """FR-044: traceable even on the public endpoint."""
    response = client.get("/health")
    assert response.headers["X-Correlation-Id"]
    assert response.json()["correlationId"] == response.headers["X-Correlation-Id"]


def test_slow_dependency_is_reported_unhealthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hang must become a bounded 503, not an unanswered request (FR-042)."""
    import time

    monkeypatch.setattr(health, "DEPENDENCY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(health, "_check_database_sync", lambda: (time.sleep(1), None)[1])

    response = client.get("/health")
    assert response.status_code == 503
    assert "timed out" in response.json()["checks"][0]["detailMessage"]
