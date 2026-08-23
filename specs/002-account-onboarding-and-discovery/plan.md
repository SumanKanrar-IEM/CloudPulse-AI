# Implementation Plan: Account Onboarding and Discovery

**Branch**: `pods/pod73-002-account-onboarding-and-discovery` | **Date**: 2026-08-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-account-onboarding-and-discovery/spec.md`

## Summary

This spec connects CloudPulse AI to AWS accounts using roles only and builds the discovery engine
that keeps a complete, continuously refreshed inventory of every resource in them — not a
hand-picked service list. The technical approach: a Step Functions state machine fans a scan out
per account × region × service group, driven by a Resource Groups Tagging API sweep plus AWS Cloud
Control API's generic `ListResources` for whole-account enumeration, with targeted boto3 describes
layered on for the six governance-critical resource types P1 enrichment requires. Everything reuses
spec 1's existing API Lambda, Cognito pool, and Aurora cluster — this spec adds routes, tables, and
one new orchestration surface, not a second copy of any of them.

Three decisions dominate the design, settled in [research.md](./research.md): how "every resource
type, not a curated list" is achieved without a per-service connector for each one (**Cloud Control
API's generic resource-type registry, with the normalized connector interface FR-014 requires
sitting in front of both it and the targeted-enrichment describes**); how a scan's lifecycle
survives partial failure without corrupting the deleted-marker diff (**a scan-level status machine
with `partial` as a first-class outcome, diffing gated on `succeeded`/`partial`, never `failed`**);
and how role authorization for the new admin/operator split (spec 2's Clarifications session
2026-08-23) is enforced without inventing a second mechanism (**spec 1's existing `require_role`
dependency, called with different role sets per route — no new auth code**).

## Technical Context

**Language/Version**: Python 3.12 (backend, AWS Lambda arm64) · TypeScript 5.5 / Angular 18
(frontend) · HCL with Terraform >= 1.15 (infrastructure) — unchanged from spec 1, this spec adds no
new language.

**Primary Dependencies**: FastAPI + Mangum, Pydantic v2, SQLAlchemy 2.0, Alembic, AWS Lambda
Powertools, boto3 (all already present from spec 1) · AWS Step Functions (new: Map-state fan-out
orchestration) · Angular Material, ng2-charts (already present, this spec's frontend surface is one
new admin page).

**Storage**: Aurora Serverless v2 PostgreSQL 16 (spec 1's cluster; this spec's migrations extend
`cloud_account` and `resource`, and add columns to `scan` — no new cluster) · S3 (spec 1's raw scan
snapshot bucket, provisioned but empty until this spec writes to it — FR-028's immutable raw
snapshot per scan).

**Testing**: pytest + moto (unit, no credentials — Cloud Control API and Tagging API calls mocked)
· Testcontainers PostgreSQL + LocalStack (integration in CI, unchanged pattern from spec 1) ·
Playwright (accounts-view P1 journey, extending spec 1's e2e harness).

**Target Platform**: AWS Lambda arm64 on Python 3.12 (API Lambda, unchanged; new: scan-orchestration
Lambdas invoked from Step Functions) · AWS Step Functions Standard workflow (scan fan-out; Standard,
not Express — a scan can legitimately run longer than Express's 5-minute cap on a large account,
and Standard's per-state execution history is exactly what FR-023's independent-unit-of-work
success/fail/retry record needs).

**Project Type**: Web application in the existing monorepo — this spec adds to `backend/app/scan/`
and `backend/connectors/` (both reserved empty by spec 1's FR-054/FR-008), `infra/modules/scan/`
(new Terraform module), and one route group in `backend/app/api/routers/`.

**Performance Goals**: SC-001's 5-minute onboarding-to-verified budget; SC-002's >95% resource
discovery rate; a single scan unit of work (one account × region × service group) sized so the
whole fan-out completes well inside FR-023/FR-024's bounded-retry budget at demo scale (see
research.md R-201 for the concrete unit-of-work sizing).

**Constraints**: Zero stored credentials (Principle III, unchanged) — cross-account access is
AssumeRole + platform-generated ExternalId only (FR-003a), never an access key, and the ExternalId
itself is a Secrets Manager reference the same way spec 1's DB credential is, never a plaintext
column (data-model.md). Every table this spec touches is tenant-scoped (spec 1 FR-030,
unchanged). No write, modify, or delete permission against any scanned account, ever (FR-005).

**Scale/Scope**: Demo-scale, matching spec 1's Assumptions — a handful of connected accounts, tens
of thousands of resources in the largest one (Edge Cases), 2 environments. 40 functional
requirements (33 numbered, 7 added during clarification), 9 success criteria, 4 P1 user stories
(this spec has no P2 user story — S17's scan history is P2 but attaches to an existing P1 story
rather than standing alone).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against CloudPulse AI Constitution **v2.0.1** (amended 2026-08-23: PATCH, wording only —
see spec 1's journal; no principle redefined since v2.0.0's solo-delivery model this plan is
already written against).

| Principle | Gate | Pre-Phase-0 | Post-Phase-1 | How this plan satisfies it |
|---|---|---|---|---|
| I. Spec-First Delivery | Every artifact traces to a merged spec | PASS | PASS | Plan derives solely from spec.md's FR-001–FR-033 and its Clarifications; every research.md decision cites the FR it serves. |
| II. AWS-Native Runtime & GitHub-Native Delivery | AWS runtime only; Bedrock Agents for product GenAI; GitHub-native delivery | PASS | PASS | Every new component (Step Functions, Cloud Control API, Resource Groups Tagging API, boto3 describes) is an AWS managed service or AWS SDK call. No GenAI in this spec — spec 6 is the only spec that touches Bedrock. `dependency-allowlist` and `connector-boundary` CI gates (already live, playbook §0.5) enforce this automatically; nothing new to wire. |
| III. Zero Stored Credentials | Roles only; OIDC for CI/CD; read-only scanning; immutable audit | PASS | PASS | FR-001–FR-005 are this principle's product-facing requirements: role-only connection, platform-generated ExternalId stored as a Secrets Manager reference, read-only permissions exclusively. Every account-management action (register/deactivate/reactivate) writes an `audit_event` per spec 1's FR-040, unchanged mechanism. |
| IV. Deterministic Core, Agentic Edge | Deterministic core; no model calls on core paths | PASS | PASS | Discovery, enrichment, and diffing are pure boto3/SQLAlchemy — no model call anywhere in this spec. The connector interface (FR-014) is what spec 6's coverage advisor will eventually read from, but this spec contains no agent code itself. |
| V. Contract-First Modularity | Typed contracts at every boundary; rules as data | PASS | PASS | FR-014 defines the connector protocol spec 1's FR-054 reserved the package for. Coverage-as-data (FR-021/FR-022) is data, not code, matching Principle V's "adding a rule/coverage entry must be possible without modifying core code" test directly. New OpenAPI paths are additive-only per spec 1's FR-048a, generated the same way. |
| VI. Test & Quality Gates | Lint, types, unit, integration with mocked AWS; red blocks merge | PASS | PASS | Same `ci.yml` gate spec 1 built — no new CI job needed. moto covers Cloud Control API and Tagging API mocking (research.md confirms moto's coverage before this is assumed, not asserted). |
| VII. Solo Trunk-Based Delivery with AI Collaboration | `pods/pod73` sole long-lived branch; recorded AI review before merge | PASS | PASS | Same PR ritual as spec 1, now with `pr-task-reference` enforcing the task-ID citation automatically (playbook §0.5, added mid-spec-1). |
| VIII. Honest Prioritization | P1/P2 tiered; P1 deliverable without any P2 | PASS | PASS | FR-020 (extended enrichment) and FR-033 (scan history) are this spec's only P2 requirements; dropping both leaves every P1 user story and SC-001–SC-004, SC-006–SC-009 intact (SC-005's coverage-as-data mechanism is P1 foundation, not P2, since P1 enrichment itself depends on it existing). |

**Result: PASS at both gates.** No principle violations, so Complexity Tracking is empty. Two
design tensions are resolved in research.md rather than by exception — see R-201 (Cloud Control API
coverage gaps for some resource types) and R-207 (Step Functions Standard vs Express cost/duration
tradeoff).

## Project Structure

### Documentation (this feature)

```text
specs/002-account-onboarding-and-discovery/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions, cost profile, VERIFY markers
├── data-model.md         # Phase 1 output — cloud_account/resource/scan extensions, connector shape
├── quickstart.md         # Phase 1 output — validation guide mapped to success criteria
├── contracts/
│   └── openapi.yaml      # Phase 1 output — additive-only diff against spec 1's trunk contract
├── checklists/
│   ├── requirements.md         # Spec quality checklist (16/16)
│   └── scope-and-contracts.md  # Requirements-quality checklist (28 items, reviewer-owned)
└── tasks.md              # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
infra/                                     # Terraform — this spec adds one module, extends none
├── modules/
│   ├── scan/                              # NEW — Step Functions state machine, EventBridge
│   │   ├── main.tf                        #   Scheduler rule, scan-worker Lambdas, IAM roles scoped
│   │   │                                     to sts:AssumeRole on cross-account scanner roles only
│   │   └── scan_workflow.asl.json         #   The state machine's ASL definition, its own file
│   │                                         (never inlined) so check_stepfunctions_asl.py (T042a,
│   │                                         research.md R-211) can validate it offline pre-apply
│   └── api/                               # UNCHANGED — this spec adds routes to the existing
│                                             API Lambda, not a new one
└── envs/{dev,prod}/                       # Wires the new scan module in alongside spec 1's modules

backend/
├── app/
│   ├── api/routers/
│   │   └── accounts.py                    # NEW — FR-006–FR-012 registration/admin-surface routes
│   ├── scan/                              # FILLED — was an empty package reserved by spec 1
│   │   ├── orchestrator.py                #   Step Functions state-machine input builder
│   │   ├── discovery.py                   #   Cloud Control API + Tagging API sweep (FR-016/017)
│   │   ├── enrichment.py                  #   targeted boto3 describes for FR-019's six types
│   │   └── coverage.py                    #   coverage-as-data loader (FR-021/022)
│   ├── core/
│   │   └── (unchanged — reuses spec 1's require_role, audit, logging, db modules directly)
│   └── models/
│       └── (extends spec 1's CloudAccount, Resource, Scan declarative models — no new files)
├── connectors/
│   ├── base.py                            # FILLED — the provider-agnostic protocol FR-014
│   │                                         defines and spec 1's FR-054 reserved the package for
│   └── aws.py                             # NEW — the one connector implementation this spec ships
├── migrations/versions/
│   └── 0009_resource_lifecycle_and_detail.py   # NEW — additive migration (see data-model.md).
│                                                  Smaller than it first looks: `account_status`
│                                                  already has `disabled` and `scan_status`
│                                                  already has `partial` from spec 1's original
│                                                  enum definitions — this migration only touches
│                                                  `resource` (state, deleted_at, detail columns).
└── handlers/
    └── scan_worker_handler.py             # NEW — Lambda entrypoint Step Functions invokes per unit

frontend/src/app/features/
└── accounts/                              # FILLED — was an empty package reserved by spec 1
    ├── accounts-list.component.ts         # FR-010/FR-010a — visible to all three roles
    ├── account-form.component.ts          # FR-006/FR-011a — admin-only, disabled for other roles
    └── accounts.service.ts                # Generated-client wrapper, no hand-written API calls
```

**Structure Decision**: Same monorepo, same split-by-deployable-concern layout spec 1 established.
This spec fills three directories spec 1 deliberately left empty (`backend/app/scan/`,
`backend/connectors/`, `frontend/src/app/features/`) rather than inventing new top-level
directories — that emptiness was FR-054/FR-055's whole point. The one genuinely new piece of
infrastructure is `infra/modules/scan/`; everything else extends an existing module or Lambda.

## Complexity Tracking

> No Constitution Check violations. This table is intentionally empty.

Two decisions add real complexity but are each required by a spec requirement rather than chosen
for convenience, documented with their rejected alternatives in research.md: the Step Functions
Map fan-out (R-211, required by FR-023's independent-unit-of-work requirement given a single Lambda
invocation cannot both stay inside its own timeout on a large account and retry only the failed
portion), and the connector protocol's isolation from both discovery paths — generic Cloud Control
sweep and targeted enrichment describes — behind one interface (R-201, required by FR-014 and
Principle V, not by convenience — a naive implementation would let the enrichment describes bypass
the connector boundary entirely).
