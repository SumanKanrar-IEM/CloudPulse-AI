"""Three questions R-613a left open, asked from inside an AgentCore Runtime
(spec 006, T061 extension).

Same HTTP contract as `main.py`. `POST /invocations` with `{"test": name}`
runs one of three probes and returns `{"ok": bool, ...}` for it. Each probe
is isolated in its own try/except so a failure names itself rather than
masking the others -- the point of the first spike's one-line failure.

* `model` -- can the execution role call a Bedrock model from here?
* `egress` -- can PUBLIC network mode reach a public HTTPS endpoint? (The
  platform API is an API Gateway HTTP API: the same class of endpoint.)
* `credentials` -- does the execution role's identity reach boto3 inside the
  runtime, and can it read a Secrets Manager secret directly? That is the
  path `_platform_api.py` would use in place of the Lambda Secrets extension.

boto3's presence in the managed runtime is itself a finding: if `import
boto3` fails, `model` and `credentials` both report it, and T065 learns the
zip must vendor dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080
MODEL_ID = os.environ.get(
    "SPIKE_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
SECRET_ID = os.environ.get("SPIKE_SECRET_ID", "")
EGRESS_URL = "https://sts.us-east-1.amazonaws.com/"


def probe_model() -> dict:  # type: ignore[type-arg]
    import boto3

    client = boto3.client(
        "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
    )
    response = client.converse(
        modelId=MODEL_ID,
        messages=[
            {"role": "user", "content": [{"text": "Reply with the single word: pong"}]}
        ],
        inferenceConfig={"maxTokens": 8, "temperature": 0},
    )
    text = response["output"]["message"]["content"][0]["text"]
    usage = response.get("usage", {})
    return {
        "ok": True,
        "model_id": MODEL_ID,
        "text": text,
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "stop_reason": response.get("stopReason"),
    }


def probe_egress() -> dict:  # type: ignore[type-arg]
    # Any HTTP status proves TCP + TLS + DNS reached a public endpoint. STS
    # unauthenticated returns 403; that is a success here.
    request = urllib.request.Request(EGRESS_URL, method="GET")  # noqa: S310 - fixed https URL
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed https URL
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    return {"ok": True, "url": EGRESS_URL, "http_status": status}


def probe_credentials() -> dict:  # type: ignore[type-arg]
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    identity = boto3.client("sts", region_name=region).get_caller_identity()
    result = {
        "ok": True,
        "caller_arn": identity["Arn"],
        "credential_env": sorted(
            k for k in os.environ if "CREDENTIAL" in k or k.startswith("AWS_CONTAINER")
        ),
    }
    if SECRET_ID:
        secret = boto3.client("secretsmanager", region_name=region).get_secret_value(
            SecretId=SECRET_ID
        )
        result["secret_read"] = json.loads(secret["SecretString"]).get("marker")
    return result


PROBES = {
    "model": probe_model,
    "egress": probe_egress,
    "credentials": probe_credentials,
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:  # type: ignore[type-arg]
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        self._send(200 if self.path == "/ping" else 404, {"status": "Healthy"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        name = str(payload.get("test", ""))
        probe = PROBES.get(name)
        if probe is None:
            self._send(400, {"ok": False, "error": f"unknown test {name!r}"})
            return
        try:
            self._send(200, {"test": name, **probe()})
        except Exception as exc:  # the whole point is to report it
            self._send(
                200,
                {"test": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"},
            )

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104
