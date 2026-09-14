"""The platform-API client every agent tool call shares (spec 006, T016,
T024, T024a, T064; FR-003, FR-056, R-602, R-613b).

**This calls the platform HTTP API and nothing else.** No database session,
no cloud credential for any scanned account, no provider SDK on the request
path -- `urllib` is the whole client. Reaching the data store directly would
bypass the tenant scoping and the read-only method filter that
`backend/app/core/agent_access.py` exists to provide, and FR-056 forbids it.

Shared rather than copied. The capabilities differ only in which paths they
expose; duplicating the auth exchange, the HTTPS check and the response
handling into each would mean a fix to one silently not reaching the others
-- and these are the parts where a mistake is a security mistake rather than
a wrong answer.

Under AgentCore (T064)
----------------------
Bedrock Agents (classic) called tools by invoking a Lambda with a fixed event
envelope; AgentCore hosts the agent's own code, so a tool call is an ordinary
function call inside `agents/runtime/main.py`. This module lost the envelope
(`respond`, the `apiPath`/`httpMethod` event fields) and kept everything
that mattered: HTTPS only, GET only, a fail-closed path allowlist, a token
requested per call. R-602 is unchanged -- the data store was forbidden
because of what going around the API bypasses, not because of how the tool
was hosted.

Credentials
-----------
The agent authenticates as its own Cognito machine principal. Its client
secret is read from Secrets Manager under the runtime's execution role --
R-613b verified the role reaches boto3 inside the runtime with no credential
environment variables, and that a direct `GetSecretValue` works. This is the
one provider-SDK call in the agent code, and it is the same class of exception
`backend/app/core/db.py` holds for the platform's own database credential:
it operates the platform's own infrastructure, never a scanned account. The
Lambda Parameters-and-Secrets extension the classic version used is Lambda-
only and is gone.

The token this obtains carries `custom:agent_id`, so the API builds an
`AgentPrincipal` for it: viewer role, tenant fixed by the token, every
state-changing method refused. Each capability's allowlist is defence in depth
over that enforcement, not a replacement for it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_TIMEOUT_SECONDS = 10


class ToolError(RuntimeError):
    """A lookup that could not be performed. Returned to the model as an
    error result rather than raised out of the loop: a tool that throws gives
    the model no way to say "I could not read that", and it invents an answer."""


def http_json(url: str, headers: dict[str, str], *, data: bytes | None = None) -> Any:
    # Checked before the request is built, not after: these calls carry a
    # bearer token.
    if not url.startswith("https://"):
        raise ToolError(f"refusing a non-HTTPS request to {url}")
    request = urllib.request.Request(url, headers=headers, data=data)  # noqa: S310 - scheme checked above
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ToolError(f"platform API returned {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ToolError(f"platform API unreachable: {exc}") from exc


def client_secret() -> str:
    """The agent's Cognito client secret, from Secrets Manager under the
    runtime's own role. Never logged and never returned to the model."""
    secret_id = os.environ.get("AGENT_CLIENT_SECRET_ID")
    if not secret_id:
        raise ToolError("agent credential configuration is missing")
    try:
        import boto3

        payload = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
        return str(json.loads(payload["SecretString"])["client_secret"])
    except Exception as exc:  # the caller reports, never guesses
        raise ToolError("agent credential could not be read") from exc


def access_token() -> str:
    """A client-credentials token for the agent principal.

    Requested per invocation rather than cached: a cached token outliving a
    revoked client is the failure mode worth avoiding, and there is no request
    volume to optimise for.
    """
    domain = os.environ.get("COGNITO_TOKEN_ENDPOINT")
    client_id = os.environ.get("AGENT_CLIENT_ID")
    if not domain or not client_id:
        raise ToolError("agent credential configuration is missing")
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret(),
        }
    ).encode("utf-8")
    payload = http_json(domain, {"Content-Type": "application/x-www-form-urlencoded"}, data=body)
    token = payload.get("access_token")
    if not token:
        raise ToolError("no access token was issued")
    return str(token)


def resolve_path(api_path: str, parameters: dict[str, Any]) -> str:
    """Substitute path parameters, URL-encoding each value.

    Encoding matters: a path parameter reaches here from model output, and an
    unencoded one would let a generated id change which endpoint is called.
    """
    resolved = api_path
    for name, value in parameters.items():
        placeholder = "{" + name + "}"
        if placeholder in resolved:
            resolved = resolved.replace(placeholder, urllib.parse.quote(str(value), safe=""))
    if "{" in resolved:
        raise ToolError(f"missing a path parameter for {api_path}")
    return resolved


def query_string(api_path: str, parameters: dict[str, Any]) -> str:
    query = {
        name: str(value)
        for name, value in parameters.items()
        if "{" + name + "}" not in api_path and value is not None
    }
    return f"?{urllib.parse.urlencode(query)}" if query else ""


def call(api_path: str, parameters: dict[str, Any], allowed_paths: frozenset[str]) -> Any:
    """One governance lookup, performed as the read-only agent principal.

    Fail-closed on the path: an `api_path` not in the caller's allowlist is
    refused before any network call, so a definition edit that outran its
    allowlist cannot reach the API. Every operation is a GET -- there is no
    method parameter to get wrong, which is how the read-only rule is kept in
    the code's shape rather than in a check (FR-056).

    Raises `ToolError`; the runtime turns it into a tool result the model can
    read, so a lookup that failed is a topic to leave out, not one to fill in.
    """
    if api_path not in allowed_paths:
        raise ToolError(f"no such operation: {api_path}")
    base_url = os.environ.get("PLATFORM_API_BASE_URL")
    if not base_url:
        raise ToolError("platform API endpoint is not configured")
    url = (
        base_url.rstrip("/")
        + resolve_path(api_path, parameters)
        + query_string(api_path, parameters)
    )
    return http_json(url, {"Authorization": f"Bearer {access_token()}"})


__all__ = ["ToolError", "access_token", "call", "query_string", "resolve_path"]
