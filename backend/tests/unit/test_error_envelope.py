"""The uniform error envelope is frozen (FR-043).

Every endpoint added by specs 002-006 returns errors in this shape. Changing it is a
breaking change to every consumer at once, so these assertions are deliberately
strict -- they are the fixture the `oasdiff` contract check diffs against, and a
failure here means the contract moved, not that the test is brittle.

The implementation lives in `app/api/errors.py` (task T068, Phase 6). These tests
assert against the contract itself so the shape is pinned before any code can drift
from it.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def envelope(openapi_contract: dict[str, Any]) -> dict[str, Any]:
    schemas = openapi_contract["components"]["schemas"]
    assert "ErrorEnvelope" in schemas, "FR-043 requires a single uniform error envelope"
    return dict(schemas["ErrorEnvelope"])


def test_envelope_wraps_a_single_error_object(envelope: dict[str, Any]) -> None:
    assert envelope["type"] == "object"
    assert envelope["required"] == ["error"]
    assert "error" in envelope["properties"]


def test_envelope_requires_code_message_and_correlation_id(envelope: dict[str, Any]) -> None:
    """FR-043 names exactly three mandatory members."""
    error = envelope["properties"]["error"]
    assert set(error["required"]) == {"code", "message", "correlationId"}


def test_correlation_id_is_a_uuid(envelope: dict[str, Any]) -> None:
    """FR-044: the id in the response must match the one in the logs.

    Declaring the format keeps a caller-supplied string from being echoed back
    unvalidated -- see the 'correlation identifier absent' edge case.
    """
    corr = envelope["properties"]["error"]["properties"]["correlationId"]
    assert corr["type"] == "string"
    assert corr["format"] == "uuid"


def test_code_is_machine_readable(envelope: dict[str, Any]) -> None:
    code = envelope["properties"]["error"]["properties"]["code"]
    assert code["type"] == "string"
    assert "SCREAMING_SNAKE_CASE" in code["description"]


def test_validation_details_are_optional_and_field_scoped(envelope: dict[str, Any]) -> None:
    """`details` must stay optional -- making it required would break every
    non-validation error response at once (FR-048b)."""
    error = envelope["properties"]["error"]
    assert "details" not in error["required"]
    item = error["properties"]["details"]["items"]
    assert set(item["required"]) == {"field", "issue"}


@pytest.mark.parametrize(
    "response_name",
    ["Unauthorized", "Forbidden", "NotFound", "ValidationFailed", "InternalError"],
)
def test_every_failure_kind_uses_the_same_envelope(
    openapi_contract: dict[str, Any], response_name: str
) -> None:
    """SC-009: 100% of error responses conform to the single envelope.

    Parametrised per failure kind so a regression names which one broke rather than
    reporting a single opaque failure.
    """
    responses = openapi_contract["components"]["responses"]
    assert response_name in responses, f"{response_name} missing -- FR-043 covers all failure kinds"
    schema = responses[response_name]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/ErrorEnvelope"


def test_not_found_does_not_leak_existence(openapi_contract: dict[str, Any]) -> None:
    """FR-035: a 404 to an unentitled caller must be indistinguishable from a 404
    for a genuinely missing record."""
    description = openapi_contract["components"]["responses"]["NotFound"]["description"]
    assert "not entitled to know" in description


def test_health_is_the_only_unauthenticated_operation(openapi_contract: dict[str, Any]) -> None:
    """FR-033a: `/health` is public; everything else requires a resolved role.

    A new endpoint that forgets its security requirement inherits the global default,
    so this asserts the *explicit* public opt-out is used exactly once.
    """
    public = [
        (path, method)
        for path, ops in openapi_contract["paths"].items()
        for method, op in ops.items()
        if isinstance(op, dict) and op.get("security") == []
    ]
    assert public == [("/health", "get")], f"unexpected unauthenticated operations: {public}"
