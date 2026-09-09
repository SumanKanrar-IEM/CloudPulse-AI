# `agents/` — Amazon Bedrock AgentCore Runtime

> **Re-pointed 2026-09-09 (constitution v3.0.0, research R-613).** This tree was built for Bedrock
> Agents (classic). AWS placed that service in maintenance mode and closed new agent creation to
> accounts without prior usage, so the definitions and action groups here describe a runtime this
> account cannot create. The constraints below are unchanged and still binding; what changes is
> which Bedrock service hosts the orchestration. See T061-T067.

**Owned by spec 006 (agentic insights).** Spec 001 reserved this tree and left it empty; spec 006
populates it. The constraints below are spec 001's and this spec implements against them — it does
not get to relax them.

| Directory | Holds |
| --- | --- |
| `definitions/` | Agent definitions and tool schemas, one per capability |
| `action-groups/` | Platform-API tool code. Named for Bedrock Agents' action groups; under AgentCore these are the agent's own tool calls, and `_platform_api.py`'s rules are unchanged |
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

## Runtime limitation, stated rather than discovered

Every capability here calls Bedrock from a VPC-attached Lambda. The dev VPC has no NAT gateway and
only S3 and Secrets Manager interface endpoints. Whether Bedrock publishes an interface endpoint is
**unverified** — see R-604, and run its check rather than assuming either answer. Plan for the
model being unreachable: that is a specified, testable state here (FR-007a, SC-009), not an outage.
