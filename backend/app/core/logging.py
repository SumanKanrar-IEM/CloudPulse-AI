"""Structured logging with redaction (FR-045, FR-046, research.md R-012).

FR-045 requires structured, machine-parsable logs for every request. FR-046 forbids
credentials, secrets, session tokens, and raw customer tag values in them.

Redaction happens in the *formatter*, not at the call site. A call-site convention
holds only until the next developer forgets it, and a leaked credential in a log is
discovered long after it matters. Doing it here means a careless
``logger.info("...", extra={"password": pw})`` is still safe.

Raw customer tag values are redacted too, which is easy to overlook: tags are customer
data that routinely carry emails, project codenames, and cost-centre identifiers. FR-046
names them explicitly for that reason.
"""

from __future__ import annotations

import re
from typing import Any, Final

from aws_lambda_powertools import Logger
from aws_lambda_powertools.logging.formatter import LambdaPowertoolsFormatter

REDACTED: Final[str] = "[redacted]"

# Key names whose values never appear in a log record.
SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password", "passwd", "pwd", "secret", "token", "access_token", "id_token",
        "refresh_token", "session_token", "authorization", "auth", "api_key",
        "apikey", "access_key", "secret_key", "secret_access_key", "private_key",
        "credential", "credentials", "client_secret", "cookie", "set-cookie",
        # FR-046 names raw customer tag values explicitly. `tags` is the normalised
        # resource tag map -- customer data, not platform data.
        "tags", "tag_values",
    }
)

# Value-shaped secrets that can appear inside a free-text message, where a key-based
# denylist cannot see them.
_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                    # AWS access key id
    re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),                   # GitHub token
)


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively strip sensitive values.

    Depth-limited: a self-referential structure would otherwise recurse forever, and a
    logger that hangs is an outage.
    """
    if _depth > 12:
        return "[max-depth]"

    if isinstance(value, dict):
        return {
            k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str):
        for pattern in _VALUE_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    return value


class RedactingFormatter(LambdaPowertoolsFormatter):
    """Powertools JSON formatter with FR-046 redaction applied to every record."""

    def serialize(self, log: dict[str, Any]) -> str:
        return super().serialize(redact(log))


def build_logger(service: str = "cloudpulse-api", level: str = "INFO") -> Logger:
    """A structured logger that cannot leak a value on the denylist."""
    return Logger(
        service=service,
        level=level,
        logger_formatter=RedactingFormatter(),
    )


logger: Logger = build_logger()

__all__ = ["logger", "build_logger", "redact", "RedactingFormatter", "SENSITIVE_KEYS", "REDACTED"]
