"""The agent that runs inside Bedrock AgentCore Runtime (spec 006, T064;
FR-001, FR-003, FR-004, FR-056, R-602, R-613, R-613a, R-613b).

One runtime hosts every capability. `POST /invocations` carries
`{"capability": "digest", "prompt": "...", "session_id": "..."}`; the
capability selects a prompt file, a definition and a tool allowlist, and the
loop below runs Converse with tool use until the model stops or the iteration
bound is reached. The reply is the same shape the classic connector returned
-- `output_text`, `input_tokens`, `output_tokens` -- plus what AgentCore lets
this add: `stop_reason`, and `truncated` when the model hit its token limit,
which the suggester's item-wise accounting can use (T063).

**Why one runtime and not four.** The capabilities differ only in prompt and
allowlist; everything that costs money or carries risk -- the cost cap, the
grounding validator, the run row -- lives in the worker that invokes this and
is per capability there. A runtime per capability would be four copies of
this file with four execution roles and nothing they could do differently.
`agent_run.definition_hash` still hashes each capability's own prompt and
definition, so a change to one is traceable to one (R-608).

**Why a hand-written loop and not a framework.** Converse's tool-use contract
is a few dozen lines, the repository's agent-framework denylist stays intact
(`check_dependencies.py`, and its docstring on why), and a reader can follow
every model round trip in one screen. Principle II v3.0.0 permits a framework
inside AgentCore; nothing here needs one yet. If this loop grows a memory, a
planner or a second model, that is the moment to reach for one, by name, with
a reviewer.

**What this file never does.** It holds no cloud credential for any scanned
account (FR-003): the only AWS calls are Converse under the runtime's own
role and the one Secrets Manager read `_platform_api.py` makes for the agent's
Cognito secret. It never touches the data store (FR-056): every tool call is a
GET to the platform API through `_platform_api.call`, which refuses any path
not in the capability's allowlist before making a request. It does not
validate output -- that is `backend/app/governance/grounding.py`'s job, in
the worker, after this returns (FR-001).

Runtime contract (R-613a): standard library `http.server` on port 8080,
`GET /ping` and `POST /invocations`. boto3 is vendored into the artefact
because the managed runtime does not ship it (R-613b).
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# The deploy packages `agents/definitions`, `agents/prompts` and
# `agents/action-groups` beside this file, so the runtime reads the same
# content-hashed files the worker hashes onto the run row. In the repository
# they are siblings of `runtime/` instead; both layouts resolve.
ROOT = HERE if (HERE / "definitions").is_dir() else HERE.parent
DEFINITIONS = ROOT / "definitions"
PROMPTS = ROOT / "prompts"
sys.path.insert(0, str(ROOT / "action-groups"))

import _platform_api  # noqa: E402 - path set above

PORT = 8080
CAPABILITIES = ("digest", "suggester", "advisor", "narrator")


def load_capability(name: str) -> tuple[dict[str, Any], str, frozenset[str]]:
    if name not in CAPABILITIES:
        raise ValueError(f"unknown capability {name!r}")
    definition = json.loads((DEFINITIONS / f"{name}.json").read_text(encoding="utf-8"))
    prompt = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    allowed = frozenset(importlib.import_module(f"{name}_tools").ALLOWED_PATHS)
    return definition, prompt, allowed


def tool_specs(
    definition: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Converse `toolSpec`s from the definition's OpenAPI paths, and the map
    from tool name back to the path the allowlist knows.

    The OpenAPI schema is kept in the definition rather than replaced with a
    tool-spec list because it is what a human reads to see what the agent may
    call, and one source is one thing to keep honest. Every operation is a GET
    (asserted in `test_agent_action_group_allowlists.py`), so there is no
    method to carry.
    """
    specs: list[dict[str, Any]] = []
    paths: dict[str, str] = {}
    for path, operations in definition["tools"]["apiSchema"]["paths"].items():
        op = operations["get"]
        name = op["operationId"]
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in op.get("parameters", []):
            schema = dict(param.get("schema", {"type": "string"}))
            if param.get("description"):
                schema["description"] = param["description"]
            properties[param["name"]] = schema
            if param.get("required"):
                required.append(param["name"])
        specs.append(
            {
                "toolSpec": {
                    "name": name,
                    "description": " ".join(
                        s for s in (op.get("summary"), op.get("description")) if s
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        }
                    },
                }
            }
        )
        paths[name] = path
    return specs, paths


def run_tool(
    name: str, arguments: dict[str, Any], paths: dict[str, str], allowed: frozenset[str]
) -> dict[str, Any]:
    """One tool call, always answered. A failure is a result the model reads,
    never an exception out of the loop -- see `_platform_api.ToolError`."""
    path = paths.get(name)
    if path is None:
        return {"error": f"no such tool: {name}"}
    try:
        return {"result": _platform_api.call(path, arguments, allowed)}
    except _platform_api.ToolError as exc:
        return {"error": str(exc)}


# A reply wrapped whole in one Markdown code fence: ```json ... ``` or ``` ... ```.
# Anchored at both ends, so a fence *inside* prose is not touched.
_WHOLE_FENCE = re.compile(r"\A```[A-Za-z0-9_-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?```\s*\Z", re.DOTALL)


def unwrap_fence(text: str) -> str:
    """Remove a code fence wrapping the *entire* reply, and nothing else.

    T067 found Nova 2 Lite wraps its JSON in ```json ... ``` on every reply
    (8 of 8) though every prompt says "no code fence" -- and the workers'
    parsers, being fail-closed, rejected all eight before grounding ran. With
    the wrapper removed, 5 of 5 grounded cleanly. So this is transport
    formatting, not content, and it is absorbed here at the model boundary
    rather than in the governance parsers: those stay strict, and a reply
    with prose around the JSON, or a fence inside it, still fails closed.
    """
    match = _WHOLE_FENCE.match(text.strip())
    return match.group("body") if match else text


def converse_loop(capability: str, prompt: str, *, region: str) -> dict[str, Any]:
    import boto3

    definition, instruction, allowed = load_capability(capability)
    specs, paths = tool_specs(definition)
    client = boto3.client("bedrock-runtime", region_name=region)

    kwargs: dict[str, Any] = {
        "modelId": definition["modelId"],
        "system": [{"text": instruction}],
        "inferenceConfig": definition.get("inference", {}),
        "toolConfig": {"tools": specs},
    }
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    if guardrail_id:
        kwargs["guardrailConfig"] = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
        }

    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": prompt}]}]
    input_tokens = output_tokens = 0
    stop_reason = ""
    for _ in range(int(definition.get("maxToolIterations", 8))):
        response = client.converse(messages=messages, **kwargs)
        usage = response.get("usage", {})
        input_tokens += int(usage.get("inputTokens", 0))
        output_tokens += int(usage.get("outputTokens", 0))
        message = response["output"]["message"]
        messages.append(message)
        stop_reason = str(response.get("stopReason", ""))
        if stop_reason != "tool_use":
            break
        results = []
        for block in message.get("content", []):
            use = block.get("toolUse")
            if not use:
                continue
            outcome = run_tool(use["name"], dict(use.get("input") or {}), paths, allowed)
            results.append(
                {
                    "toolResult": {
                        "toolUseId": use["toolUseId"],
                        "content": [{"json": outcome}],
                    }
                }
            )
        messages.append({"role": "user", "content": results})
    else:
        # The loop ran out before the model stopped asking for tools. Reported
        # as its own reason: the test that found this had the bound reported
        # as "tool_use", which reads as "still working" rather than "cut off".
        stop_reason = "max_iterations"

    final = messages[-1] if messages[-1]["role"] == "assistant" else {}
    text = "".join(b.get("text", "") for b in final.get("content", []) if "text" in b)
    return {
        "output_text": unwrap_fence(text),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stop_reason": stop_reason,
        # FR-004a's signal, which Bedrock Agents (classic) never exposed:
        # `max_tokens` means the model was cut off mid-answer; `max_iterations`
        # means it kept asking for tools past the bound. Both are truncation.
        "truncated": stop_reason in ("max_tokens", "max_iterations"),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server's contract
        self._send(200 if self.path == "/ping" else 404, {"status": "Healthy"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/invocations":
            self._send(404, {"error": "no such path"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            capability = str(payload["capability"])
            prompt = str(payload["prompt"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            self._send(400, {"error": f"malformed invocation: {exc}"})
            return
        try:
            result = converse_loop(
                capability, prompt, region=os.environ.get("AWS_REGION", "us-east-1")
            )
        except Exception as exc:  # reported to the worker, which records the run as failed
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send(200, result)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104 - the runtime's contract
