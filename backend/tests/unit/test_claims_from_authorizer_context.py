"""`_claims_from` reads the Lambda authorizer's context, not raw claims (FR-034, FR-043).

The authorizer (handlers/authorizer_handler.py) never denies at the gateway -- it always
returns `isAuthorized: true`, carrying the verification result as `context.valid`. These
tests are what proves an unverified request actually ends up unauthenticated rather than
silently trusted: an app that read `sub` out of unverified context would defeat the whole
point of moving the 401 into the app.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.security import GROUPS_CLAIM, _claims_from


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()

    @app.get("/_t/claims")
    async def _probe(request: Request) -> dict[str, Any]:
        return _claims_from(request)

    return app


def _client_with_event(app: FastAPI, authorizer_context: dict[str, str] | None) -> TestClient:
    class _EventStager:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] == "http":
                scope["aws.event"] = {
                    "requestContext": {
                        "authorizer": {"lambda": authorizer_context} if authorizer_context else {}
                    }
                }
            await self.inner(scope, receive, send)

    return TestClient(_EventStager(app))  # type: ignore[arg-type]


def test_valid_context_yields_full_claims(app: FastAPI) -> None:
    client = _client_with_event(
        app,
        {
            "valid": "true",
            "sub": "abc-123",
            "email": "maintainer@example.com",
            "groups_present": "true",
            "groups": "cloudpulse-admins",
        },
    )
    body = client.get("/_t/claims").json()

    assert body["sub"] == "abc-123"
    assert body["email"] == "maintainer@example.com"
    assert body[GROUPS_CLAIM] == "cloudpulse-admins"


def test_unverified_context_yields_no_claims_at_all(app: FastAPI) -> None:
    """This is the load-bearing assertion: an invalid token must not leak a subject."""
    client = _client_with_event(app, {"valid": "false"})
    assert client.get("/_t/claims").json() == {}


def test_missing_authorizer_context_yields_no_claims(app: FastAPI) -> None:
    client = _client_with_event(app, None)
    assert client.get("/_t/claims").json() == {}


def test_groups_absent_claim_is_not_present_in_output(app: FastAPI) -> None:
    """`groups_present: "false"` must not synthesise an empty-list claim (FR-032a)."""
    client = _client_with_event(app, {"valid": "true", "sub": "abc-123", "groups_present": "false"})
    body = client.get("/_t/claims").json()

    assert GROUPS_CLAIM not in body
