"""A 404 must not reveal whether a record exists (FR-035).

'The requested resource was not found' has to mean the same thing whether the record is
genuinely absent or merely belongs to another tenant. Otherwise a caller enumerates
resource ids by watching which ones return 403 instead of 404 — the message becomes an
oracle.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()

    @app.get("/_t/absent")
    async def _absent() -> None:
        raise HTTPException(status_code=404, detail="resource 8f3c-not-a-real-id does not exist")

    @app.get("/_t/other-tenant")
    async def _other_tenant() -> None:
        raise HTTPException(
            status_code=404, detail="resource 8f3c-not-a-real-id belongs to tenant acme-corp"
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_both_404s_are_byte_identical_apart_from_the_correlation_id() -> None:
    """The core property: an attacker learns nothing from the difference."""
    app = create_app()

    @app.get("/_t/absent")
    async def _absent() -> None:
        raise HTTPException(status_code=404, detail="record 123 does not exist")

    @app.get("/_t/forbidden-but-exists")
    async def _exists() -> None:
        raise HTTPException(status_code=404, detail="record 123 belongs to another tenant")

    with TestClient(app, raise_server_exceptions=False) as client:
        a = client.get("/_t/absent").json()["error"]
        b = client.get("/_t/forbidden-but-exists").json()["error"]

    a.pop("correlationId")
    b.pop("correlationId")
    assert a == b, "the two 404 responses are distinguishable -- FR-035 violation"


@pytest.mark.parametrize("path", ["/_t/absent", "/_t/other-tenant"])
def test_no_route_detail_reaches_the_caller(client: TestClient, path: str) -> None:
    """FastAPI echoes `detail` by default; the handler must discard it."""
    body = client.get(path).text
    for leak in ("8f3c-not-a-real-id", "acme-corp", "belongs to", "does not exist"):
        assert leak not in body, f"404 body leaked {leak!r}"


def test_the_message_is_the_fixed_safe_text(client: TestClient) -> None:
    assert client.get("/_t/absent").json()["error"]["message"] == (
        "The requested resource was not found."
    )


def test_unknown_route_matches_the_same_shape(client: TestClient) -> None:
    """A path that was never registered must look like any other 404."""
    body = client.get("/definitely-not-a-route").json()["error"]
    assert body["code"] == "NOT_FOUND"
    assert body["message"] == "The requested resource was not found."


def test_403_and_404_carry_distinct_codes(client: TestClient) -> None:
    """FR-035 requires 404s to be indistinguishable from each other -- not that 403
    and 404 be merged. Collapsing them would lose real diagnostic value for a caller
    who is legitimately signed in."""
    app = create_app()

    @app.get("/_t/forbidden")
    async def _forbidden() -> None:
        raise HTTPException(status_code=403)

    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/_t/forbidden").json()["error"]["code"] == "FORBIDDEN"
    assert client.get("/_t/absent").json()["error"]["code"] == "NOT_FOUND"
