# `agents/` — Amazon Bedrock AgentCore Runtime

> **Migrated 2026-09-15 (constitution v3.0.0, research R-613, R-613a, R-613b; tasks T061–T066).**
> Built for Bedrock Agents (classic), which AWS placed in maintenance mode and closed to this
> account; now runs on **Bedrock AgentCore Runtime**. The constraints below are unchanged and
> still binding. The model is Amazon Nova 2 Lite (R-613c), and the path is proven live: T067 verified
> the runtime and grounding, and T144 (2026-09-29) ran worker → runtime → Nova → grounding end to end
> on real findings — a non-empty digest and 19 suggestions, none rejected.

**Owned by spec 006 (agentic insights).** Spec 001 reserved this tree and left it empty; spec 006
populates it. The constraints below are spec 001's and this spec implements against them — it does
not get to relax them.

| Directory | Holds |
| --- | --- |
| `runtime/` | `main.py` — the agent AgentCore hosts. One runtime for every capability: the invocation payload names the capability, which selects a prompt, a definition and a tool allowlist; a hand-written Converse tool-use loop does the rest. Its docstring says why one runtime and why no framework |
| `definitions/` | Per capability: the inference-profile model id, inference settings, the tool-loop bound, the guardrail note, and the tool surface as an OpenAPI schema the runtime turns into Converse `toolSpec`s |
| `action-groups/` | The tool allowlists (`ALLOWED_PATHS`) and `_platform_api.py`, the HTTP client every tool call goes through: HTTPS only, GET only, fail-closed on the allowlist, token per call. Named for Bedrock Agents' action groups; the envelope is gone and the rules are not |
| `prompts/` | Versioned prompt sources, content-hashed (research.md R-608) |
| `evals/` | Evaluation cases run against recorded fixtures in CI (R-609) |

## Constraints (spec 001 fixed these; spec 006 may not bypass them)

**FR-056 — agents reach data only through the platform API.** Action groups authenticate as a
read-only, tenant-scoped principal (`backend/app/core/agent_access.py`). An agent MUST NOT hold a
cloud credential, MUST NOT reach the data store directly, and MUST be refused on every
state-changing operation. Constitution Principle IV, enforced at the foundation rather than
re-derived here.

**Principle II (NON-NEGOTIABLE) — the product GenAI layer is Amazon Bedrock, exclusively**, with
AgentCore Runtime for orchestration.
No non-AWS inference, model-hosting, or agent-framework SDK may enter any dependency manifest. The
`dependency-allowlist` CI job enforces it.

Claude Code drives the *development* lifecycle and is never a runtime dependency of the deployed
platform. An authoring tool may be Anthropic's; a running component may not be.

**Principle IV — grounding.** Every agent output shown to a user is validated against the
governance store before display (`backend/app/governance/grounding.py`). A rejected output is
recorded, never displayed. The validator is deterministic code, not a second model call — one that
could hallucinate would defeat its own purpose (R-607).

## Reaching the runtime from the VPC

The workers that invoke these capabilities are VPC-attached Lambdas, and the dev VPC's standing
endpoints are only S3 and Secrets Manager. A deploy opts into one of two paths, both off by default
and billed per hour: `enable_egress` (a single-AZ NAT gateway, T143 — what T144 used) or
`enable_agent_endpoints` (the `bedrock-agentcore` interface endpoint AWS does publish, R-604a).
Without either, the model is unreachable — a specified, testable state here (FR-007a, SC-009), not
an outage. The runtime itself runs in `PUBLIC` network mode and reaches the platform API directly.

## What is here now (spec 006, as of 2026-10-01)

| Capability | Definition | Prompt | Allowlist | Invoked by |
| --- | --- | --- | --- | --- |
| `digest` | `definitions/digest.json` | `prompts/digest.md` | `action-groups/digest_tools.py` (`/findings`, `/resources/{id}`, `/spend/summary`) | `digest_worker_handler`, daily, via `connectors.aws.invoke_agent` |
| `suggester` | `definitions/suggester.json` | `prompts/suggester.md` | `action-groups/suggester_tools.py` (`/findings`, `/resources/{id}`, `/rules`) | `suggester_worker_handler`, daily, one invocation per open finding |
| `advisor` | `definitions/advisor.json` | `prompts/advisor.md` | `action-groups/advisor_tools.py` (`/resources`) | **Not invoked.** `advisor_worker_handler` runs a deterministic detection and hashes these files onto the run row as the capability's contract (T038f). The seam if narration is wanted |
| `narrator` | `definitions/narrator.json` | `prompts/narrator.md` | `action-groups/narrator_tools.py` (`/forecasts`) | **No worker.** US7 was descoped from spec 006 (2026-09-24); these files and the validator's exact-figure mode stay, unused |

All four name `global.amazon.nova-2-lite-v1:0` — an Amazon-owned model through an inference
profile. R-613b found the original Claude id end-of-life and every Anthropic model gated behind
an AWS Marketplace subscription this AISPL-billed account cannot complete; R-613c verified Nova 2
Lite answers from inside the runtime with no Marketplace step. Principle II names Bedrock, not a
vendor.

The runtime returns `extract_json(text)`: the one JSON value in the model's reply, with any code
fence or prose around it dropped (T067d, widened by T071). The dropped text is never parsed or
shown; the governance parsers stay strict on the value itself, and a reply with no JSON value still
reaches them unchanged and fails closed.

`_platform_api.py` is the one HTTP client every tool call shares: Cognito machine principal
(secret read from Secrets Manager under the runtime's own role — R-613b), HTTPS only, GET only,
fail-closed path allowlist. `backend/tests/unit/
test_agent_action_group_allowlists.py` asserts each handler's `ALLOWED_PATHS` equals its
definition's declared paths, that every declared operation is a GET, and that the prompt file
each definition names exists — a comment saying "must match" is not a check.

`evals/` runs sixteen recorded-output cases through the real parsers and validator on every PR
(`agent-evals` job). Never live Bedrock.
