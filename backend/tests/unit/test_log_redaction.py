"""No credential, token, or raw customer tag value reaches a log record (FR-046).

Redaction lives in the formatter rather than at the call site, so these tests exercise
the formatter directly as well as through the app. A call-site convention holds only
until the next developer forgets it, and a leaked credential in a log is discovered long
after it matters.
"""

from __future__ import annotations

import json

import pytest

from app.core.logging import REDACTED, SENSITIVE_KEYS, RedactingFormatter, redact


@pytest.mark.parametrize("key", sorted(SENSITIVE_KEYS))
def test_every_denylisted_key_is_redacted(key: str) -> None:
    assert redact({key: "super-secret-value"})[key] == REDACTED


@pytest.mark.parametrize("key", ["PASSWORD", "Secret", "Api_Key", "AUTHORIZATION"])
def test_redaction_is_case_insensitive(key: str) -> None:
    """A key differing only in case must not slip through."""
    assert redact({key: "value"})[key] == REDACTED


def test_nested_structures_are_redacted() -> None:
    payload = {
        "outer": {"inner": {"password": "p"}},
        "list": [{"token": "t"}, {"safe": "keep"}],
    }
    result = redact(payload)
    assert result["outer"]["inner"]["password"] == REDACTED
    assert result["list"][0]["token"] == REDACTED
    assert result["list"][1]["safe"] == "keep"


def test_raw_customer_tag_values_are_redacted() -> None:
    """FR-046 names tags explicitly.

    Easy to overlook, because tags look like ordinary metadata -- but they routinely
    carry emails, project codenames, and cost-centre identifiers. That is customer
    data, not platform data.
    """
    assert redact({"tags": {"owner": "someone@customer.example"}})["tags"] == REDACTED
    assert redact({"tag_values": {"sda": "Payments"}})["tag_values"] == REDACTED


@pytest.mark.parametrize(
    "message",
    [
        "using key AKIAIOSFODNN7EXAMPLE now",
        "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlSGVyZQ",
        "-----BEGIN RSA PRIVATE KEY-----",
        "gh token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    ],
)
def test_secret_shaped_values_in_free_text_are_redacted(message: str) -> None:
    """A key-based denylist cannot see a secret embedded in a message string."""
    assert REDACTED in redact(message)


def test_non_sensitive_values_survive() -> None:
    """Over-redaction makes logs useless, which is its own kind of failure."""
    payload = {"user_id": "u-1", "path": "/health", "duration_ms": 12.5, "count": 3}
    assert redact(payload) == payload


def test_deeply_nested_structures_do_not_hang() -> None:
    """A logger that hangs is an outage."""
    deep: dict[str, object] = {"k": "v"}
    for _ in range(50):
        deep = {"nested": deep}
    assert redact(deep) is not None


def test_formatter_redacts_the_serialized_record() -> None:
    """End to end: what actually reaches stdout carries no secret."""
    formatter = RedactingFormatter()
    output = formatter.serialize(
        {"level": "INFO", "message": "auth", "password": "hunter2", "tags": {"a": "b"}}
    )
    parsed = json.loads(output)
    assert parsed["password"] == REDACTED
    assert parsed["tags"] == REDACTED
    assert parsed["message"] == "auth"


def test_the_denylist_covers_the_categories_fr046_names() -> None:
    """FR-046 names credentials, secrets, session tokens, and raw tag values."""
    for required in ("password", "secret", "session_token", "tags"):
        assert required in SENSITIVE_KEYS
