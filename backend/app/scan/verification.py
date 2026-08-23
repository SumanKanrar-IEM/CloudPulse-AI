"""Registration-time role verification (FR-007).

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


__all__ = ["VerificationError", "verify_registration"]
