"""The agent that runs inside AgentCore, exercised without AgentCore (T064;
spec 006, FR-003, FR-004a, FR-056, R-613).

boto3's `converse` is replaced with a scripted double, so the loop's shape
is asserted directly: tool calls are answered through the allowlist, an
unknown tool is answered with an error the model reads rather than an
exception, a `max_tokens` stop marks the reply truncated, and the iteration
bound is a truncation too. The four definitions are loaded for real, so a
definition that stopped matching its allowlist would fail here as well as in
`test_agent_action_group_allowlists.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from app.governance.definition_hash import AGENTS_ROOT

RUNTIME = AGENTS_ROOT / "runtime" / "main.py"


@pytest.fixture(scope="module")
def runtime():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("agent_runtime", RUNTIME)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Converse:
    """A scripted model: each call pops the next response."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        # Snapshot: the loop mutates its message list after each call, and a
        # test that read the live list would see the end state, not the call.
        self.calls.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return self.responses.pop(0)


def _text(text: str, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": stop,
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }


def _tool_use(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "t1", "name": name, "input": arguments}}],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }


@pytest.fixture
def scripted(runtime, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def install(responses: list[dict[str, Any]]) -> _Converse:
        double = _Converse(responses)
        fake_boto3 = type("boto3", (), {"client": staticmethod(lambda *_a, **_k: double)})
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        return double

    return install


# --- definitions become tool specs ---------------------------------------------


@pytest.mark.parametrize("capability", ["digest", "suggester", "advisor", "narrator"])
def test_every_definition_loads_and_its_tools_match_its_allowlist(runtime, capability: str) -> None:  # type: ignore[no-untyped-def]
    definition, prompt, allowed = runtime.load_capability(capability)
    specs, paths = runtime.tool_specs(definition)

    assert prompt.strip()
    assert definition["modelId"].startswith("global.amazon.")
    assert set(paths.values()) == set(allowed)
    for spec in specs:
        assert spec["toolSpec"]["inputSchema"]["json"]["type"] == "object"


def test_a_path_parameter_becomes_a_required_tool_argument(runtime) -> None:  # type: ignore[no-untyped-def]
    definition, _, _ = runtime.load_capability("digest")
    specs, paths = runtime.tool_specs(definition)
    get_resource = next(s["toolSpec"] for s in specs if s["toolSpec"]["name"] == "getResource")

    assert get_resource["inputSchema"]["json"]["required"] == ["resource_id"]
    assert paths["getResource"] == "/resources/{resource_id}"


# --- the loop --------------------------------------------------------------------


def test_a_plain_answer_returns_text_and_token_totals(runtime, scripted) -> None:  # type: ignore[no-untyped-def]
    scripted([_text('{"sections": []}')])

    result = runtime.converse_loop("digest", "hello", region="us-east-1")

    assert result["output_text"] == '{"sections": []}'
    assert (result["input_tokens"], result["output_tokens"]) == (10, 5)
    assert result["stop_reason"] == "end_turn"
    assert result["truncated"] is False


def test_a_tool_call_is_answered_through_the_allowlist_and_the_loop_continues(
    runtime, scripted, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[str, dict[str, Any], frozenset[str]]] = []

    def fake_call(path: str, params: dict[str, Any], allowed: frozenset[str]) -> Any:
        seen.append((path, params, allowed))
        return {"findings": []}

    monkeypatch.setattr(runtime._platform_api, "call", fake_call)
    double = scripted([_tool_use("listFindings", {"status": "open"}), _text("done")])

    result = runtime.converse_loop("digest", "hello", region="us-east-1")

    assert seen == [
        ("/findings", {"status": "open"}, frozenset(runtime.load_capability("digest")[2]))
    ]
    # The tool result went back to the model as the next user turn.
    second_call_messages = double.calls[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert second_call_messages[-1]["content"][0]["toolResult"]["content"][0]["json"] == {
        "result": {"findings": []}
    }
    assert result["output_text"] == "done"
    assert result["input_tokens"] == 20  # summed across both round trips


def test_an_unknown_tool_is_an_error_result_not_an_exception(runtime, scripted) -> None:  # type: ignore[no-untyped-def]
    double = scripted([_tool_use("deleteEverything", {}), _text("understood")])

    result = runtime.converse_loop("digest", "hello", region="us-east-1")

    tool_result = double.calls[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["json"]
    assert tool_result == {"error": "no such tool: deleteEverything"}
    assert result["output_text"] == "understood"


def test_a_refused_path_is_an_error_result_too(runtime, scripted) -> None:  # type: ignore[no-untyped-def]
    """The advisor's allowlist is `/resources` only. A definition edit that
    added `/rules` back without the allowlist following would surface here as
    the model being told 'no such operation', never as a request."""
    definition, _, allowed = runtime.load_capability("advisor")
    _, paths = runtime.tool_specs(definition)

    outcome = runtime.run_tool("listResources", {}, {**paths, "sneaky": "/rules"}, allowed)
    refused = runtime.run_tool("sneaky", {}, {**paths, "sneaky": "/rules"}, allowed)

    assert "error" in outcome  # no PLATFORM_API_BASE_URL in tests: refused before any request
    assert refused == {"error": "no such operation: /rules"}


def test_max_tokens_marks_the_reply_truncated(runtime, scripted) -> None:  # type: ignore[no-untyped-def]
    scripted([_text("partial", stop="max_tokens")])

    result = runtime.converse_loop("suggester", "hello", region="us-east-1")

    assert result["truncated"] is True
    assert result["stop_reason"] == "max_tokens"


def test_the_iteration_bound_is_a_truncation(runtime, scripted) -> None:  # type: ignore[no-untyped-def]
    """A model that asks for the same tool forever is stopped by the bound,
    and the worker is told so rather than handed an empty success."""
    definition, _, _ = runtime.load_capability("digest")
    bound = int(definition["maxToolIterations"])
    scripted([_tool_use("getSpendSummary", {})] * bound)

    result = runtime.converse_loop("digest", "hello", region="us-east-1")

    assert result["stop_reason"] == "max_iterations"
    assert result["truncated"] is True
    assert result["output_text"] == ""


def test_the_runtime_holds_no_scanned_account_credential_path(runtime) -> None:  # type: ignore[no-untyped-def]
    """FR-003, structurally: nothing in the runtime or the API client can
    assume a scanner role or read an ExternalId."""
    source = (
        Path(RUNTIME).read_text() + (AGENTS_ROOT / "action-groups" / "_platform_api.py").read_text()
    )
    for forbidden in ("assume_role", "AssumeRole", "external_id", "cloudpulse-scanner", '"sts"'):
        assert forbidden not in source, forbidden


# --- T067: the code fence Nova 2 Lite puts around every reply ----------------------

# Verbatim shape of what the deployed runtime returned on 2026-09-23 (ids shortened).
NOVA_REPLY = """```json
{
  "sections": [
    {"heading": "Critical finding escalated", "body": "A critical finding was escalated.",
     "references": [{"kind": "finding", "id": "f1", "label": "S3 bucket"}]}
  ]
}
```"""


def test_a_reply_wrapped_whole_in_a_json_fence_is_unwrapped(runtime) -> None:  # type: ignore[no-untyped-def]
    import json

    unwrapped = runtime.unwrap_fence(NOVA_REPLY)

    assert json.loads(unwrapped)["sections"][0]["heading"] == "Critical finding escalated"


def test_a_bare_fence_without_a_language_is_unwrapped_too(runtime) -> None:  # type: ignore[no-untyped-def]
    assert runtime.unwrap_fence('```\n{"sections": []}\n```') == '{"sections": []}'


def test_prose_around_a_fence_is_left_alone_so_the_parser_still_fails_closed(runtime) -> None:  # type: ignore[no-untyped-def]
    """Only a fence wrapping the *entire* reply is transport formatting. Prose
    before or after it is the model ignoring the output contract, and the
    governance parser must see that and refuse it."""
    chatty = 'Here is your digest:\n```json\n{"sections": []}\n```'

    assert runtime.unwrap_fence(chatty) == chatty


def test_unfenced_json_passes_through_unchanged(runtime) -> None:  # type: ignore[no-untyped-def]
    assert runtime.unwrap_fence('{"sections": []}') == '{"sections": []}'


def test_the_loop_returns_the_unwrapped_text(runtime, scripted) -> None:  # type: ignore[no-untyped-def]
    scripted([_text(NOVA_REPLY)])

    result = runtime.converse_loop("digest", "hello", region="us-east-1")

    assert result["output_text"].startswith("{")


def test_the_real_digest_parser_accepts_the_unwrapped_nova_reply(runtime) -> None:  # type: ignore[no-untyped-def]
    """End to end through production code: the reply that failed 8 of 8
    times on T067 now parses."""
    from app.governance.digest import parse_sections

    sections = parse_sections(runtime.unwrap_fence(NOVA_REPLY))

    assert [s.heading for s in sections] == ["Critical finding escalated"]
