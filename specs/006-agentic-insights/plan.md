# Implementation Plan: Agentic Insights

**Branch**: `pods/pod73-006-spec` | **Date**: 2026-09-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-agentic-insights/spec.md`

## Summary

Build the platform's intelligence layer as Amazon Bedrock Agents that observe the governance data
specs 002–005 already produce, explain it, and propose improvements — never executing changes and
never holding a cloud credential.

Two P1 capabilities carry the feature: a **nightly insight digest** rendered as a dashboard card,
and a **per-finding remediation suggester** that finally writes the `ai_generated` suggestion
source spec 003 defined and spec 004 rendered but nothing has ever produced. Five P2 capabilities
follow: a coverage advisor, metrics collection, deterministic forecasting, rightsizing, and
narratives.

The technical shape is settled by constraints rather than chosen: Principle II fixes Bedrock
Agents; spec 001's `app/core/agent_access.py` fixes how action groups reach data; Principle IV
fixes that agents observe and propose but never decide. What this plan adds is the grounding
validator (deterministic, never a second model call), the run/cost-cap accounting that makes
FR-004 real, and a honest split of what the coverage advisor can actually apply as data.

## Technical Context

**Language/Version**: Python 3.12 (backend, action groups), TypeScript 5.x / Angular 18 (frontend)

**Primary Dependencies**: FastAPI + Mangum, Pydantic v2, SQLAlchemy 2 + Alembic, AWS Lambda
Powertools, boto3 (`bedrock-agent-runtime`, `cloudwatch`) confined to `connectors/`; Angular
Material + ng2-charts. **No new AI/agent SDK** — Bedrock Agents is a service, not a library, so
`dependency-allowlist` sees nothing new.

**Storage**: Aurora Serverless v2 PostgreSQL. Seven new tenant-scoped tables (data-model.md); no
existing table's shape changes.

**Testing**: pytest + moto (unit), testcontainers PostgreSQL + LocalStack (integration),
Playwright (P1 dashboard journeys), plus `agents/evals/` run in CI against recorded fixtures
(research.md R-609).

**Target Platform**: AWS Lambda arm64 behind the existing API Gateway HTTP API; Bedrock Agents in
`us-east-1`.

**Project Type**: Web service + SPA, monorepo.

**Performance Goals**: Digest and suggester are daily batch — no latency target. Read endpoints
match the platform's existing dashboard expectation (sub-2s at demo scale).

**Constraints**: Agent runs enforce a cost cap (FR-004). Every displayed output passes
deterministic grounding validation (FR-001). No mutating endpoint except the proposal decision.
**The model is expected to be unreachable at runtime** in the current environment — a specified,
testable state (FR-007a, SC-009), not an outage.

**Scale/Scope**: Demo scale — single tenant, a few accounts, a few thousand resources, low
hundreds of open findings. That last number is what makes per-finding suggestion cost the one
figure worth watching (research.md R-606).

## Constitution Check

*GATE: evaluated before Phase 0, re-evaluated after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
| --- | --- | --- |
| **I. Spec-Driven & Documented** | PASS | Full lifecycle followed; `agents/README.md` already reserves this tree and states the constraints; T050-style README updates are in scope. |
| **II. AWS-Native Runtime, GitHub-Native Delivery** (NON-NEGOTIABLE) | PASS | Bedrock Agents exclusively (R-601). No non-AWS inference or agent SDK enters any manifest — `dependency-allowlist` sees no new dependency at all, since Bedrock is a service. Delivery stays GitHub Actions on the `pods/pod73` trunk. |
| **III. Zero Stored Credentials** (NON-NEGOTIABLE) | PASS | Action groups hold no cloud credential and reach data only through the platform API as `AgentPrincipal` (R-602). No new secret is introduced. |
| **IV. Deterministic Core, Agentic Edge** | PASS | FR-007 keeps discovery/validation/scoring/ingestion free of model calls; forecasting is a deterministic calculation the agent narrates (Clarifications); the grounding validator is ordinary code (R-607); proposals require human acceptance. |
| **V. Contract-First Modularity** | PASS | Design-time contract written; the generated document stays binding. `boto3` stays inside `connectors/` — `connector-boundary` enforces it. |
| **VI. Honest Prioritization** | PASS | P1 (digest, suggester) is deliverable with zero P2 items; the P2 tier is droppable without touching SC-001–SC-005. |
| **VII. Solo Trunk-Based Delivery** | PASS | Branch → PR → green CI → recorded AI review → merge, per phase, as specs 002–005 ran. |
| **VIII. Honest Prioritization / no P2 destabilises P1** | PASS | The five P2 stories add tables and endpoints; none alters a P1 code path. |

**No violations. No complexity deviations to justify.**

Two things this gate deliberately records rather than waves through:

- **FR-056's agent principal is spec 001's, not this spec's to redefine.** `agent_access.py`
  already refuses every mutating method and forces viewer role. This plan consumes it. If a
  capability here ever appears to need a write, that is a signal to stop, not to widen the
  principal.
- **Principle IV's testable clause demands a grounding validator that rejects absent ARNs.** That
  is why R-607 makes it deterministic: a model-based validator could not satisfy its own test.

## Project Structure

### Documentation (this feature)

```text
specs/006-agentic-insights/
├── plan.md              # This file
├── research.md          # Phase 0 — R-601..R-610
├── data-model.md        # Phase 1 — seven new tables
├── quickstart.md        # Phase 1 — V1..V7 validation scenarios
├── contracts/
│   └── openapi.yaml     # Phase 1 — design-time reference
├── checklists/
│   └── requirements.md  # from /speckit-specify, re-validated by /speckit-clarify
└── tasks.md             # NOT created here — /speckit-tasks
```

### Source Code (repository root)

```text
agents/                          # THIS SPEC OWNS THIS TREE (reserved empty by spec 001)
├── definitions/                 # agent + action-group schemas, per capability
├── action-groups/               # Lambda handlers; call the platform API, never the DB
├── prompts/                     # versioned sources; content-hashed (R-608)
└── evals/                       # CI cases against recorded fixtures (R-609)

backend/
├── app/governance/
│   ├── grounding.py             # deterministic validator (R-607)
│   ├── digest.py                # assemble inputs, persist result
│   ├── suggestions.py           # EXTENDED: gains the ai_generated writer
│   ├── coverage_advisor.py      # P2 — proposal detection + acceptance
│   ├── metrics.py               # P2 — collection
│   ├── forecasting.py           # P2 — deterministic calculation
│   └── rightsizing.py           # P2
├── app/api/routers/
│   ├── insights.py              # digest, runs, rejections
│   ├── coverage_proposals.py    # P2 — list + decision
│   ├── forecasts.py             # P2
│   └── rightsizing.py           # P2
├── handlers/
│   ├── digest_worker_handler.py
│   ├── suggester_worker_handler.py
│   └── metrics_collector_handler.py   # P2
├── connectors/aws.py            # EXTENDED: invoke_agent, get_metric_data
└── migrations/versions/0015_*.py

frontend/src/app/features/
├── overview/                    # EXTENDED: the digest card
├── findings/                    # EXTENDED: ai_generated rendering already exists
├── coverage-proposals/          # P2
└── insights/                    # P2 — run history, rejection rate

infra/modules/agents/            # THIS SPEC'S module: agents, aliases, guardrails,
                                 # action-group Lambdas, schedules
```

**Structure decision**: `agents/` is populated as spec 001 reserved it. Backend logic follows the
established split — `app/governance/` holds rules with no Lambda-runtime concerns, `handlers/`
holds entrypoints, `connectors/` is the only place a provider SDK appears. A new
`infra/modules/agents/` rather than extending `infra/modules/cost/`, because that module is
already a three-task shared lineage (T009/T016/T047) and this spec's resources are a different
concern.

## Phasing

P1 first and complete, per Principle VI:

| Phase | Scope | Delivers |
| --- | --- | --- |
| 1 | Setup + migration 0015 | Seven tables, enums, the `agents/` scaffold |
| 2 | Grounding validator + agent-run accounting | The two things every capability depends on |
| 3 | **US1 — insight digest (P1)** | SC-001, SC-004 |
| 4 | **US2 — remediation suggester (P1)** | SC-002, SC-005 |
| 5 | P1 completion: role matrix, live verification, teardown | 🏁 P1 demoable |
| 6 | US3 — coverage advisor (P2) | SC-003 |
| 7 | US4 — metrics collection (P2) | feeds 8 and 9 |
| 8 | US5 — forecasting (P2) | SC-006 |
| 9 | US6 — rightsizing (P2) | — |
| 10 | US7 — narratives (P2) | SC-007 |
| Final | READMEs, live-verify/teardown pair, `/speckit-analyze` | — |

Phase 2 exists as its own phase deliberately: the grounding validator and the run/cost-cap
accounting are shared by all seven stories, and building them inside the digest phase would make
the suggester's own compliance an accident of ordering rather than a property of the design.

## Complexity Tracking

No constitution violations require justification.

**R-603's limitation is now resolved in the requirements, not merely noted.** A resource type
with no existing enrichment function cannot be closed by an accepted proposal, because
`coverage_definitions.json` maps a type to a Python function name. The checklist review
(CHK034/CHK035) caught that FR-015 as originally written promised otherwise. FR-015 is now
narrowed to the two kinds that apply as configuration, and FR-015a makes the third read-only
advisory content that is never offered for acceptance — so FR-017 and SC-003 hold absolutely
rather than carrying an exception.

Building a declarative enrichment DSL would make class 3 data-only. That is real unplanned scope
— a DSL, its evaluator, its validation, and its own security review — rejected for a P2 story and
named in research.md as the thing to build if class-3 coverage is ever wanted.
