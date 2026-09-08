"""Action-group Lambda for the digest agent (spec 006, T016; FR-003, R-601, R-602).

**This calls the platform HTTP API and nothing else.** No database session, no
cloud credential, no provider SDK -- `urllib` is the whole client. Reaching the
data store directly would bypass the tenant scoping and the read-only method
filter that `backend/app/core/agent_access.py` exists to provide, and FR-056
forbids it.

Credentials
-----------
The agent authenticates as its own Cognito machine principal, whose client
secret is read at runtime from the AWS Parameters and Secrets Lambda Extension
over `localhost` -- an HTTP call, not an SDK one, which is why this module can
respect `agents/action-groups/README.md`'s no-provider-SDK rule and still hold
no secret in code or configuration (Principle III). The extension layer and the
secret itself are infra's to provision (T020).

The token this obtains carries `custom:agent_id`, so the API builds an
`AgentPrincipal` for it: viewer role, tenant fixed by the token, every
state-changing method refused. The allowlist below is defence in depth over that
enforcement, not a replacement for it -- the API refuses regardless, and a
version of this file that forgot to check would still be safe.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Every operation this action group may perform, keyed by the path the agent
# schema declares. Fail-closed: an apiPath not listed here is refused before any
# network call, so a schema edit that outran this file cannot reach the API.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {"/findings", "/resources/{resource_id}", "/spend/summary"}
)

# The Secrets Manager extension's fixed local port. Documented by AWS; not
# configurable per function.
_SECRETS_EXTENSION_URL = "http://localhost:2773/secretsmanager/get"

_TIMEOUT_SECONDS = 10


class ToolError(RuntimeError):
    """A lookup that could not be performed. Returned to the agent as an error
    body rather than raised out of the handler: a Lambda that throws gives the
    agent no way to say "I could not read that", and it invents an answer."""


def _http_json(url: str, headers: dict[str, str], *, data: bytes | None = None) -> Any:
    # Checked before the request is built, not after. These calls carry a bearer
    # token, and the one non-TLS exception is the Secrets extension on loopback.
    if not url.startswith(("https://", "http://localhost:")):
        raise ToolError(f"refusing a non-HTTPS request to {url}")
    request = urllib.request.Request(url, headers=headers, data=data)  # noqa: S310 - scheme checked above
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ToolError(f"platform API returned {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ToolError(f"platform API unreachable: {exc}") from exc


def _client_secret() -> str:
    """The agent's Cognito client secret, via the Lambda extension.

    Never logged and never returned. The extension caches it, so this is a
    loopback call on all but the first invocation of a warm function.
    """
    secret_id = os.environ.get("AGENT_CLIENT_SECRET_ID")
    session_token = os.environ.get("AWS_SESSION_TOKEN")
    if not secret_id or not session_token:
        raise ToolError("agent credential configuration is missing")
    url = f"{_SECRETS_EXTENSION_URL}?{urllib.parse.urlencode({'secretId': secret_id})}"
    payload = _http_json(url, {"X-Aws-Parameters-Secrets-Token": session_token})
    try:
        return str(json.loads(payload["SecretString"])["client_secret"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ToolError("agent credential is not in the expected shape") from exc


def _access_token() -> str:
    """A client-credentials token for the agent principal.

    Requested per invocation rather than cached across them. A cached token
    outliving a revoked client is the failure mode worth avoiding here, and the
    digest runs once a day -- there is no request volume to optimise for.
    """
    domain = os.environ.get("COGNITO_TOKEN_ENDPOINT")
    client_id = os.environ.get("AGENT_CLIENT_ID")
    if not domain or not client_id:
        raise ToolError("agent credential configuration is missing")
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": _client_secret(),
        }
    ).encode("utf-8")
    payload = _http_json(
        domain,
        {"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    token = payload.get("access_token")
    if not token:
        raise ToolError("no access token was issued")
    return str(token)


def _resolve_path(api_path: str, parameters: list[dict[str, Any]]) -> str:
    """Substitute path parameters, URL-encoding each value.

    Encoding matters: a path parameter reaches here from model output, and an
    unencoded one would let a generated id change which endpoint is called.
    """
    resolved = api_path
    for parameter in parameters:
        placeholder = "{" + str(parameter.get("name", "")) + "}"
        if placeholder in resolved:
            resolved = resolved.replace(
                placeholder, urllib.parse.quote(str(parameter.get("value", "")), safe="")
            )
    if "{" in resolved:
        raise ToolError(f"missing a path parameter for {api_path}")
    return resolved


def _query_string(api_path: str, parameters: list[dict[str, Any]]) -> str:
    query = {
        str(p["name"]): str(p.get("value", ""))
        for p in parameters
        if "{" + str(p.get("name", "")) + "}" not in api_path and p.get("value") is not None
    }
    return f"?{urllib.parse.urlencode(query)}" if query else ""


def _respond(event: dict[str, Any], status_code: int, body: Any) -> dict[str, Any]:
    """The response envelope Bedrock Agents expect."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", ""),
            "apiPath": event.get("apiPath", ""),
            "httpMethod": event.get("httpMethod", ""),
            "httpStatusCode": status_code,
            "responseBody": {"application/json": {"body": json.dumps(body)}},
        },
    }


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """One governance lookup, performed as the read-only agent principal."""
    api_path = str(event.get("apiPath", ""))
    method = str(event.get("httpMethod", "")).upper()
    parameters = list(event.get("parameters") or [])

    if api_path not in ALLOWED_PATHS:
        return _respond(event, 404, {"error": f"no such operation: {api_path}"})
    if method != "GET":
        # The API refuses this too (FR-056). Refusing here as well means the
        # attempt never leaves the function, and the agent is told plainly
        # rather than reading a 403 it might narrate as a platform fault.
        return _respond(event, 403, {"error": "this action group is read-only"})

    base_url = os.environ.get("PLATFORM_API_BASE_URL")
    if not base_url:
        return _respond(event, 500, {"error": "platform API endpoint is not configured"})

    try:
        url = (
            base_url.rstrip("/")
            + _resolve_path(api_path, parameters)
            + _query_string(api_path, parameters)
        )
        body = _http_json(url, {"Authorization": f"Bearer {_access_token()}"})
    except ToolError as exc:
        # Told to the agent, not raised. The prompt's grounding rules stand
        # either way: a lookup that failed is a topic to leave out, not one to
        # fill in from memory.
        return _respond(event, 502, {"error": str(exc)})

    return _respond(event, 200, body)


__all__ = ["ALLOWED_PATHS", "ToolError", "handler"]
