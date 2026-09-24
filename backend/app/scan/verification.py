"""Role verification: at registration (FR-007), and the reason an admin sees when a
later scan finds the role gone bad (US1 scenario 6, FR-012).

Verifies a supplied role with a real, read-only action before an account is accepted,
distinguishing "role not found or cannot be assumed" from "assumed, but grants no
usable read access" wherever the underlying AWS error allows.
"""

from __future__ import annotations

from connectors.aws import VerificationOutcome, verify_access
from connectors.base import ConnectorAccount


class VerificationError(Exception):
    """Registration must be refused (FR-007). `kind` distinguishes the two failure cases."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}" if detail else kind)


def verify_registration(account: ConnectorAccount, region: str) -> None:
    """Raise `VerificationError` on any failure; return normally on success."""
    outcome: VerificationOutcome = verify_access(account, region)
    if outcome.kind != "verified":
        raise VerificationError(outcome.kind, outcome.detail)


def role_failure_reason(*, role_arn: str | None, aws_account_id: str, code: str) -> str:
    """FR-012: what `failureReason` says when a scan cannot assume the account's role.

    STS answers a deleted role, a changed trust policy, and an ExternalId mismatch
    with the same `AccessDenied`, so the reason names all three and the one fix that
    covers them, rather than guessing which one happened.
    """
    return (
        f"CloudPulse could not assume the role {role_arn} (AWS error: {code}). The role "
        "may have been deleted, or its trust policy changed so it no longer trusts "
        "CloudPulse with this account's ExternalId. Re-deploy the CloudPulse "
        f"cross-account template in AWS account {aws_account_id} with the ExternalId "
        "used at registration, then trigger a scan of this account to re-verify it."
    )


__all__ = ["VerificationError", "role_failure_reason", "verify_registration"]
