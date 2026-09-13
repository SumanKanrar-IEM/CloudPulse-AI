"""The smallest possible AgentCore Runtime agent (spec 006, T061 spike).

Standard library only. Serves the runtime's HTTP contract -- `GET /ping` for
health, `POST /invocations` for a request -- and echoes the payload back with
the Python version and the environment's view of itself. It calls no model:
the question T061 asks is "does a runtime deploy and answer", and a model call
is a second question with its own IAM answer. Keeping them apart is what makes
a failure diagnosable.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:  # type: ignore[type-arg]
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server's contract
        if self.path == "/ping":
            self._send(200, {"status": "Healthy"})
        else:
            self._send(404, {"error": "no such path"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/invocations":
            self._send(404, {"error": "no such path"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {"unparsed": raw.decode("utf-8", errors="replace")}
        self._send(
            200,
            {
                "echo": payload,
                "python": sys.version.split()[0],
                "runtime_env_keys": sorted(k for k in os.environ if k.startswith("AWS_")),
            },
        )

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104 - the runtime's contract
