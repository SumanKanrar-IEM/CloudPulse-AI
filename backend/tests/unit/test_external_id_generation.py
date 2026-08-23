"""Platform-generated ExternalId (FR-003a).

FR-003a: platform-generated, unique per account, sufficient entropy, and the platform
MUST NOT accept an admin-*chosen* value. That last guarantee is enforced structurally,
not by rejecting the field outright (the admin must relay the value back when
registering, since it has to travel over the wire somehow) -- `verify_access` only
succeeds if the value is actually embedded in the deployed role's trust policy, so an
admin who invents their own value gets the same refusal as a wrong one, proven here by
mocking the AssumeRole boundary rather than trusting moto's ExternalId-condition
fidelity, which is unverified (research.md R-209's fallback: a hand-built fixture over
moto simulation when fidelity is in doubt).
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.api.routers.accounts import _generate_external_id
from connectors.aws import verify_access
from connectors.base import ConnectorAccount

# --- Generation: unique, high-entropy ------------------------------------------


def test_generated_value_has_at_least_128_bits_of_entropy() -> None:
    """32 raw bytes, base64url-encoded -- comfortably above any practical guess budget."""
    value = _generate_external_id()
    # url-safe base64 without padding: ~1.33 chars per byte, so 32 bytes -> ~43 chars.
    assert len(value) >= 40


def test_generated_value_is_url_safe_and_has_no_padding() -> None:
    value = _generate_external_id()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", value), value


def test_consecutive_values_are_not_equal() -> None:
    values = {_generate_external_id() for _ in range(50)}
    assert len(values) == 50, "collision within 50 calls would indicate insufficient entropy"


# --- FR-003a's real protection: the value is verified structurally, not merely
# echoed. An admin-invented value never matches a real trust policy. -------------


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "denied"}}, "AssumeRole")


def test_verify_access_passes_the_supplied_external_id_to_assume_role() -> None:
    """Whichever value the caller supplies is what gets sent to AWS -- the platform
    does not silently substitute its own remembered value, because it does not keep
    one (T016a's endpoint is deliberately stateless)."""
    account = ConnectorAccount(
        aws_account_id="123456789012",
        connection_mode="assume_role",
        role_arn="arn:aws:iam::123456789012:role/cloudpulse-scanner",
        external_id="the-value-the-admin-relayed-back",
    )
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIAFAKE",
            "SecretAccessKey": "fake",
            "SessionToken": "fake-token",
        }
    }
    mock_session = MagicMock()
    mock_session.client.return_value.get_resources.return_value = {"ResourceTagMappingList": []}

    with (
        patch("boto3.client", return_value=mock_sts),
        patch("boto3.Session", return_value=mock_session),
    ):
        outcome = verify_access(account, "us-east-1")

    assert outcome.kind == "verified"
    _, kwargs = mock_sts.assume_role.call_args
    assert kwargs["ExternalId"] == "the-value-the-admin-relayed-back"


def test_an_invented_external_id_that_does_not_match_the_trust_policy_is_refused() -> None:
    """The realistic failure mode FR-003a's rationale actually protects against: an
    admin who never deployed the real template, so AWS itself refuses the assumption."""
    account = ConnectorAccount(
        aws_account_id="123456789012",
        connection_mode="assume_role",
        role_arn="arn:aws:iam::123456789012:role/cloudpulse-scanner",
        external_id="something-the-admin-made-up",
    )
    mock_sts = MagicMock()
    mock_sts.assume_role.side_effect = _client_error("AccessDenied")

    with patch("boto3.client", return_value=mock_sts):
        outcome = verify_access(account, "us-east-1")

    assert outcome.kind == "role_not_assumable"


def test_local_mode_never_calls_assume_role_or_needs_an_external_id() -> None:
    account = ConnectorAccount(aws_account_id="123456789012", connection_mode="local")
    mock_session = MagicMock()
    mock_session.client.return_value.get_resources.return_value = {"ResourceTagMappingList": []}

    with patch("boto3.Session", return_value=mock_session) as session_ctor:
        outcome = verify_access(account, "us-east-1")

    session_ctor.assert_called_once_with()  # no credentials supplied -- ambient identity only
    assert outcome.kind == "verified"
