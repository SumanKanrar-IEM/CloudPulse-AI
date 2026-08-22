"""The Lambda authorizer never denies at the gateway (FR-034, FR-043).

FR-043's uniform error envelope is the whole point of this handler: a request that
fails verification must still reach the app, carrying `valid: "false"`, so the app --
not API Gateway -- produces the 401. `isAuthorized` is therefore asserted `True` in
every case here, including the ones that would have been a hard denial under the
native JWT authorizer this replaced.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from handlers import authorizer_handler

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test"
CLIENT_ID = "test-client-id"


@pytest.fixture
def signed_token(jwt_keypair: Any):
    jwt = pytest.importorskip("jwt")

    def _make(
        *,
        token_use: str = "access",  # noqa: S107 -- a Cognito claim name, not a secret
        aud: str | None = None,
        client_id: str | None = CLIENT_ID,
        groups: list[str] | None = None,
        include_groups_claim: bool = True,
        expires_in: int = 3600,
        issuer: str = ISSUER,
    ) -> str:
        groups = ["cloudpulse-admins"] if groups is None else groups
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "maintainer@example.com",
            "token_use": token_use,
            "iss": issuer,
            "iat": now,
            "exp": now + expires_in,
        }
        if aud is not None:
            claims["aud"] = aud
        if client_id is not None:
            claims["client_id"] = client_id
        if include_groups_claim:
            claims["cognito:groups"] = groups
        return str(jwt.encode(claims, jwt_keypair, algorithm="RS256"))

    return _make


@pytest.fixture(autouse=True)
def _wire_authorizer(monkeypatch: pytest.MonkeyPatch, jwt_keypair: Any) -> None:
    """Point the handler at the test keypair instead of a real JWKS endpoint."""

    class _FakeSigningKey:
        def __init__(self, key: Any) -> None:
            self.key = key.public_key()

    class _FakeJwkClient:
        def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
            return _FakeSigningKey(jwt_keypair)

    monkeypatch.setattr(authorizer_handler, "_ISSUER", ISSUER)
    monkeypatch.setattr(authorizer_handler, "_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(authorizer_handler, "_jwk_client", _FakeJwkClient())


def _event(auth_header: str | None) -> dict[str, Any]:
    return {"headers": ({"authorization": auth_header} if auth_header else {})}


def test_valid_access_token_is_authorized_with_verified_context(signed_token: Any) -> None:
    token = signed_token(groups=["cloudpulse-admins"])
    result = authorizer_handler.handler(_event(f"Bearer {token}"))

    assert result["isAuthorized"] is True
    assert result["context"]["valid"] == "true"
    assert result["context"]["sub"] == "11111111-1111-1111-1111-111111111111"
    assert result["context"]["groups_present"] == "true"
    assert result["context"]["groups"] == "cloudpulse-admins"


def test_id_token_with_aud_is_authorized(signed_token: Any) -> None:
    token = signed_token(token_use="id", aud=CLIENT_ID, client_id=None)
    result = authorizer_handler.handler(_event(f"Bearer {token}"))

    assert result["isAuthorized"] is True
    assert result["context"]["valid"] == "true"


def test_empty_group_claim_is_distinguished_from_absent(signed_token: Any) -> None:
    """FR-032a: "claim present but empty" must not collapse into "claim absent"."""
    token = signed_token(groups=[])
    result = authorizer_handler.handler(_event(f"Bearer {token}"))

    assert result["context"]["groups_present"] == "true"
    assert result["context"]["groups"] == ""


def test_absent_group_claim_is_not_authorized_as_empty(signed_token: Any) -> None:
    token = signed_token(include_groups_claim=False)
    result = authorizer_handler.handler(_event(f"Bearer {token}"))

    assert result["context"]["groups_present"] == "false"
    assert "groups" not in result["context"]


@pytest.mark.parametrize(
    "make_kwargs",
    [
        {"expires_in": -3600},  # expired
        {"issuer": "https://attacker.example/pool"},  # wrong issuer
        {"client_id": "wrong-client-id"},  # audience mismatch
        {"token_use": "refresh"},  # not a usable token type
    ],
)
def test_invalid_token_is_still_authorized_but_unverified(
    signed_token: Any, make_kwargs: dict[str, Any]
) -> None:
    """The gateway must not deny -- the app produces the 401 envelope instead."""
    token = signed_token(**make_kwargs)
    result = authorizer_handler.handler(_event(f"Bearer {token}"))

    assert result["isAuthorized"] is True
    assert result["context"] == {"valid": "false"}


def test_missing_authorization_header_is_still_authorized_but_unverified() -> None:
    result = authorizer_handler.handler(_event(None))

    assert result["isAuthorized"] is True
    assert result["context"] == {"valid": "false"}


def test_malformed_token_is_still_authorized_but_unverified() -> None:
    result = authorizer_handler.handler(_event("Bearer not-a-real-jwt"))

    assert result["isAuthorized"] is True
    assert result["context"] == {"valid": "false"}
