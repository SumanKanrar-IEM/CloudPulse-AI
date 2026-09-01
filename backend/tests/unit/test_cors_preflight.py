"""CORS preflight handling (FR-047, found live in spec 004's T032c).

API Gateway's own `cors_configuration` decorates every response with CORS
headers, but the `$default` route's custom authorizer sends the OPTIONS
preflight itself through to the Lambda -- and with no CORS handling in the
app, Starlette 405s it (no route registers OPTIONS), which fails the
browser's preflight check regardless of what headers are attached to that
405. `create_app()` adds `CORSMiddleware` when `CLOUDPULSE_FRONTEND_URL` is
set, answering the preflight directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app

FRONTEND_URL = "https://dashboard.example.com"


def test_preflight_succeeds_when_frontend_url_is_configured(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLOUDPULSE_FRONTEND_URL", FRONTEND_URL)
    client = TestClient(create_app())

    response = client.options(
        "/me",
        headers={
            "Origin": FRONTEND_URL,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == FRONTEND_URL


def test_preflight_from_an_unconfigured_origin_is_refused(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLOUDPULSE_FRONTEND_URL", FRONTEND_URL)
    client = TestClient(create_app())

    response = client.options(
        "/me",
        headers={
            "Origin": "https://not-the-real-dashboard.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_no_cors_middleware_added_when_frontend_url_is_unset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Documents the pre-fix baseline: with nothing configured (every non-API
    Lambda's own environment, and most unit tests), the app adds no CORS
    handling at all -- unrelated to whether a caller happens to set an Origin
    header, since no browser-facing origin exists to allow in that context."""
    monkeypatch.delenv("CLOUDPULSE_FRONTEND_URL", raising=False)
    client = TestClient(create_app())

    response = client.options(
        "/me",
        headers={
            "Origin": FRONTEND_URL,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert "access-control-allow-origin" not in response.headers
