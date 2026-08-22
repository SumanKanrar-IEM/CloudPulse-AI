# `agents/` — reserved scaffold

**This tree is deliberately empty. Spec 001 does not define its contents.**

Owned by **spec 006 (ai-insights-agent)**:

| Directory | Holds |
| --- | --- |
| `definitions/` | Amazon Bedrock Agent definitions and action-group schemas |
| `action-groups/` | Lambda handlers backing each action group |
| `prompts/` | Versioned prompt sources |
| `evals/` | Evaluation cases run against the agents |

## Constraints spec 001 fixes (spec 006 implements against these, and may not bypass them)

**FR-056 — agents reach data only through the platform API.** Action groups authenticate as a
read-only, tenant-scoped principal. An agent MUST NOT hold a cloud credential, MUST NOT reach the
data store directly, and MUST be refused on every state-changing operation. This is constitution
Principle IV (*Deterministic Core, Agentic Edge*) enforced at the foundation rather than
re-derived by each later spec.

**Principle II (NON-NEGOTIABLE) — the product GenAI layer is Amazon Bedrock Agents, exclusively.**
No non-AWS inference, model-hosting, or agent-framework SDK may enter any dependency manifest.
The **`dependency-allowlist`** job in CI enforces this (FR-013a, SC-016).

Claude Code drives the *development* lifecycle and is a development-time tool only — it is never
a runtime dependency of the deployed platform. An authoring tool may be Anthropic's; a running
component may not be.

**Principle IV — grounding.** Every agent output shown to a user must be validated against
platform data: real ARNs, real numbers, no invented identifiers or figures.
