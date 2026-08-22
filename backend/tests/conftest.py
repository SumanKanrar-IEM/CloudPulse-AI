"""Shared pytest fixtures.

Two constraints shape this file:

* **FR-010** -- unit tests covering cloud-provider interactions run against simulated
  responses and must not require *or accept* real credentials. `_no_real_credentials`
  is autouse, so a test cannot accidentally reach AWS even if the developer has a
  populated `~/.aws/credentials`.

* **research.md R-007** -- LocalStack's free tier covers neither Cognito nor RDS, so
  the integration strategy is split by dependency rather than forced through one tool:

  | Dependency          | Approach                                      |
  | ------------------- | --------------------------------------------- |
  | PostgreSQL/Alembic  | Testcontainers PostgreSQL (a real engine)     |
  | S3, SQS, EventBridge| LocalStack (community-supported services)     |
  | Arbitrary AWS APIs  | moto                                          |
  | Cognito JWT         | locally-generated RSA keypair + stub JWKS     |

  Running migrations against a *real* PostgreSQL is strictly better than emulation
  anyway: FR-026 demands they apply cleanly to a populated store, and only a real
  engine proves that.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "specs" / "001-platform-foundation" / "contracts" / "openapi.yaml"

# Fake but well-formed values. Real ones would violate Principle III; malformed ones
# would make Settings fail for the wrong reason and hide real bugs.
FAKE_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:000000000000:secret:cloudpulse/db-AbCdEf"


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make it impossible for a unit test to reach a real AWS account (FR-010).

    Autouse and unconditional. Anything that genuinely needs AWS is an integration
    test and is marked as such.
    """
    for var in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONFIG_FILE",
    ):
        monkeypatch.delenv(var, raising=False)

    # moto's documented sentinel values -- inert, and refused by real AWS.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A complete, valid environment for `Settings` -- references only, no secrets."""
    for key, value in {
        "CLOUDPULSE_ENVIRONMENT": "dev",
        "CLOUDPULSE_AWS_REGION": "us-east-1",
        "CLOUDPULSE_DB_HOST": "localhost",
        "CLOUDPULSE_DB_NAME": "cloudpulse",
        "CLOUDPULSE_DB_USER": "cloudpulse_app",
        "CLOUDPULSE_DB_SECRET_ARN": FAKE_SECRET_ARN,
        "CLOUDPULSE_COGNITO_USER_POOL_ID": "us-east-1_testpool",
        "CLOUDPULSE_COGNITO_CLIENT_ID": "testclientid",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(scope="session")
def openapi_contract() -> dict[str, Any]:
    """The design-time OpenAPI contract.

    The binding artifact is the document generated from the FastAPI app in CI
    (FR-048); this copy is what `oasdiff` compares the first generated document
    against, so tests assert against it to keep the two from diverging.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover
        pytest.skip("pyyaml not installed")
    with CONTRACT_PATH.open(encoding="utf-8") as fh:
        contract: dict[str, Any] = yaml.safe_load(fh)
    return contract


# ---------------------------------------------------------------------------
# Cognito JWT signing (R-007).
#
# We sign our own tokens rather than emulating Cognito. That tests the code we
# actually wrote -- claim extraction and the FR-032a cardinality rule -- instead of
# testing Cognito, which is AWS's to get right.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def jwt_keypair() -> Any:
    """An RSA keypair for signing test tokens."""
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    return crypto.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def make_token(jwt_keypair: Any) -> Any:
    """Build a signed access token with an arbitrary group claim.

    `groups` is passed through verbatim -- including the empty list and the
    two-element list -- because FR-032a requires *both* to be refused rather than
    resolved, and a helper that quietly normalised them would hide the bug the test
    exists to catch.
    """
    jwt = pytest.importorskip("jwt")

    def _make(
        *,
        sub: str = "11111111-1111-1111-1111-111111111111",
        email: str = "maintainer@example.com",
        groups: list[str] | None = None,
        expires_in: int = 3600,
        include_groups_claim: bool = True,
    ) -> str:
        import time

        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": sub,
            "email": email,
            "token_use": "access",
            "iat": now,
            "exp": now + expires_in,
        }
        if include_groups_claim:
            claims["cognito:groups"] = groups if groups is not None else ["admin"]
        return str(jwt.encode(claims, jwt_keypair, algorithm="RS256"))

    return _make


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark everything under tests/integration/ as integration."""
    for item in items:
        if "tests/integration/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(pytest.mark.integration)


__all__ = ["FAKE_SECRET_ARN", "CONTRACT_PATH", "json"]
