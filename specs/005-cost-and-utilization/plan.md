# Implementation Plan: Cost, Utilization, and Notifications

**Branch**: `pods/pod73-005-cost-and-utilization` | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-cost-and-utilization/spec.md`

## Summary

This spec adds the platform's financial-control dimension (daily spend ingestion, a cost
dashboard, auto-created budgets, budget-overrun findings, sandbox utilization, IAM hygiene
flags) and — corrected onto its actual backlog slot per `SPECKIT_PLAYBOOK.md`'s 2026-09-02 fix
(T044) — the notification engine (owner email on a newly-opened finding, day-2/4 reminders,
an escalation flag). The technical approach adds three new daily/weekly-scheduled Lambda workers
following spec 002's own `scan-worker` scheduling pattern exactly (no SQS — research.md R-501),
extends spec 003's `Finding` table to carry a non-resource violation kind (a budget overrun,
R-508), and computes utilization live from data spec 002 already persists (`resource.state`,
R-509) with zero new AWS call. **All three new workers** inherit governance dashboard's own
standing R-407 constraint unconditionally: `cost-ingestion-worker` and `iam-hygiene-worker` call
AWS services (Cost Explorer, IAM) that have no VPC PrivateLink support at all (R-503);
`notification-worker` calls one that does (SES, confirmed live in this account's region), but
funding that single endpoint was presented to the user with real cost figures and declined
(R-504) — so it stays bounded by R-407 identically to the other two, not as an exception.

Twelve decisions dominate the design, settled in [research.md](./research.md): why notification
is one daily-scheduled worker with no SQS (**R-501**), why budget creation is synchronous inside
SDA registration rather than its own worker (**R-502**), which of this spec's own new AWS calls
inherit R-407, confirmed technically or by explicit user decision (**R-503**, **R-504**), why
budget/overrun-checking shares
`cost-ingestion-worker`'s transaction rather than running as a second worker (**R-505**), why
forecast is a simple linear trend over this spec's own data rather than a second Cost Explorer
call (**R-506**), why only actual-100% opens the overrun finding (**R-507**), the `Finding` schema
extension a non-resource finding kind requires (**R-508**), utilization's `resource.state`-based
formula and its honest scope (**R-509**), the cost profile for three new workers (**R-510**), and
the real granularity limit on cost drill-down (**R-512**).

## Technical Context

**Language/Version**: Python 3.12 (backend, AWS Lambda arm64) · TypeScript 5.5 / Angular 18
(frontend) — unchanged from specs 1–4, this spec adds no new language.

**Primary Dependencies**: FastAPI + Mangum, Pydantic v2, SQLAlchemy 2.0, Alembic, AWS Lambda
Powertools, boto3 (all already present, extended not replaced) · Angular Material + `ng2-charts`
(already installed, already used by spec 004's compliance overview — this spec's cost/
utilization charts reuse the same library, no new npm dependency).

**Storage**: Aurora Serverless v2 PostgreSQL 16 (spec 001's cluster). Three new tables
(`spend_record`, `budget`, `notification`), one new small table (`iam_hygiene_flag`), and one
additively-extended existing table (`finding` — nullable `resource_id`/`rule_id`/`rule_version`,
new `kind`/`sda_id`/`escalated_at` — data-model.md, R-508). No new cluster.

**Testing**: pytest + moto (unit — `ce`, `iam`, `ses` clients all have moto support) ·
Testcontainers PostgreSQL (integration, unchanged pattern) · Playwright (the cost dashboard,
utilization, and IAM hygiene P1/P2 screens) — see research.md R-511 for what stays mocked-only
pending R-407 (everything except utilization) versus what's fully live-testable now (utilization,
R-509, makes no AWS call at all).

**Target Platform**: AWS Lambda arm64 on Python 3.12. Existing API Lambda gets five new routers
(`spend.py`, `budgets.py`, `utilization.py`, `iam_hygiene.py`; `findings.py` extended) — no new
API Lambda, no new API Gateway, no new Cognito pool (playbook §0.5.4). **Three new,
purpose-specific Lambda functions** (`notification-worker`, `cost-ingestion-worker`,
`iam-hygiene-worker`), each with its own EventBridge Scheduler rule — the first new compute this
project has added since spec 003's governance workers.

**Project Type**: Web application in the existing monorepo — new backend routers under
`backend/app/api/routers/`, three new `backend/app/governance/` modules (pure logic, mirroring
`scoring.py`/`suggestions.py`'s existing split), three new `backend/handlers/*_worker_handler.py`
entrypoints (mirroring `compliance_validation_worker_handler.py`'s exact shape), `connectors/
aws.py` extended with two new functions (`get_daily_spend`, `iam_unused_analysis` — the
Cost-Explorer/IAM-touching code, confined here per the connector-boundary CI gate, unchanged
rule), a new `infra/modules/cost/` Terraform module, and three new `frontend/src/app/features/`
areas (cost dashboard is P1; utilization and IAM hygiene are P2).

**Performance Goals**: SC-002's cost-dashboard load reuses spec 004's own SC-003 2-second budget
at scale — no new performance target is introduced. SC-001's ±1% spend-reconciliation and SC-006's
"overrun surfaces as a finding within a day" are correctness/freshness targets, not latency ones.

**Constraints**: Zero stored credentials (Principle III, unchanged) — spend/IAM calls reuse the
existing per-account connector session (`_build_session`, same-account ambient identity or
cross-account AssumeRole+ExternalId), no new credential type. Every new table is tenant-scoped
(spec 1 FR-030). The two new IAM permissions this spec's workers need
(`ce:GetCostAndUsage`, `iam:ListRoles`/`GetRole`/`ListUsers`/`ListAccessKeys`/
`GetAccessKeyLastUsed`, all read-only) are scoped to the existing `cloudpulse-scanner` role for
cross-account targets (research.md R-503, no new role) and the workers' own execution roles for
same-account/platform-wide calls (SES send, in-account IAM/Cost Explorer reads).

**Scale/Scope**: Demo-scale, matching specs 1–4's Assumptions. 20 functional requirements plus
FR-002a from the clarify round, 8 success criteria, 7 user stories (3 P1, 4 P2).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against CloudPulse AI Constitution **v2.0.1** — unchanged since spec 004's plan; no
amendment has landed since.

| Principle | Gate | Pre-Phase-0 | Post-Phase-1 | How this plan satisfies it |
|---|---|---|---|---|
| I. Spec-First Delivery | Every artifact traces to a merged spec | PASS | PASS | Plan derives solely from spec.md's FR-001–FR-020 (incl. FR-002a) and its three Clarifications entries; every research.md decision cites the FR or User Story it serves. |
| II. AWS-Native Runtime & GitHub-Native Delivery | AWS runtime only; Bedrock Agents for product GenAI; GitHub-native delivery | PASS | PASS | Every component is an AWS managed service (Lambda, EventBridge Scheduler, Cost Explorer, IAM, SES) reused or newly consumed via the existing connector boundary — no new provider. No GenAI: R-506's forecast is a deterministic linear trend, explicitly not spec 6's AI forecasting feature, and this spec's Assumptions already say so. `dependency-allowlist`/`connector-boundary` CI gates enforce this automatically. |
| III. Zero Stored Credentials | Roles only; OIDC for CI/CD; read-only scanning; immutable audit | PASS | PASS | No new connection mode, no new credential type — SES/Cost Explorer/IAM calls all run under existing execution-role or assumed-scanner-role identities, never a stored key. Notification sends and budget/overrun state changes are read-only-to-AWS, write-only-to-the-platform's-own-store, matching the existing scan/governance workers' shape exactly. |
| IV. Deterministic Core, Agentic Edge | Deterministic core; no model calls on core paths | PASS | PASS | Nothing in this spec calls a model — forecast (R-506), utilization (R-509), and IAM hygiene classification are all plain arithmetic/rule-based logic over already-persisted or freshly-fetched data, unit-testable without mocking any LLM. |
| V. Contract-First Modularity | Typed contracts at every boundary; rules as data | PASS | PASS | New OpenAPI paths are additive-only per spec 1's FR-048a. `connectors/aws.py` remains the sole boundary for `boto3`/`botocore` imports (R-503's new `ce`/`iam` calls land there, not in `app/governance/`). Utilization's active/idle state classification (R-509) is a data dict, not an `if/elif` chain — matching `coverage_definitions.json`'s existing precedent. |
| VI. Test & Quality Gates | Lint, types, unit, integration with mocked AWS; red blocks merge | PASS | PASS | Same `ci.yml` gate specs 1–4 built — no new CI job needed. moto covers `ce`, `iam`, and `ses` clients, so every new worker is fully unit-testable without a live AWS dependency, independent of R-407/R-504's live-verification status. |
| VII. Solo Trunk-Based Delivery with AI Collaboration | `pods/pod73` sole long-lived branch; recorded AI review before merge | PASS | PASS | Same PR ritual as specs 1–4, `pr-task-reference` still enforcing task-ID citation automatically. |
| VIII. Honest Prioritization | P1/P2 tiered; P1 deliverable without any P2 | PASS | PASS | User Stories 4, 5, 6, 7 (auto-budgets, overrun findings, utilization, IAM hygiene) are this spec's only P2 requirements; dropping all four leaves User Stories 1–3 (spend visibility, notification, cadence/escalation) and SC-001–SC-004 fully intact — SC-005–SC-008 are the four success criteria honestly tied to P2 completion, noted not hidden. |

**Result: PASS at both gates.** No principle violations, Complexity Tracking below is not empty —
one real, necessary piece of new infrastructure (three new Lambda workers) is flagged there as
genuine scope, not convenience.

## Project Structure

### Documentation (this feature)

```text
specs/005-cost-and-utilization/
├── plan.md               # This file
├── research.md            # Phase 0 output — 12 decisions, cost profile, R-504 verified+declined
├── data-model.md          # Phase 1 output — 3 new tables, 1 small new table, Finding extended
├── quickstart.md          # Phase 1 output — validation guide mapped to success criteria
├── contracts/
│   └── openapi.yaml       # Phase 1 output — additive-only diff against the trunk contract
├── checklists/
│   └── requirements.md    # Spec quality checklist (16/16)
└── tasks.md               # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/routers/
│   │   ├── spend.py                       # NEW — FR-001–FR-003: GET /spend, GET /spend/summary
│   │   ├── budgets.py                     # NEW — FR-015: GET /budgets
│   │   ├── utilization.py                 # NEW — FR-018: GET /utilization
│   │   ├── iam_hygiene.py                 # NEW — FR-019/FR-020: GET /iam-hygiene
│   │   ├── findings.py                    # EXTENDED — R-508: kind/sda/escalatedAt on the
│   │   │                                     existing Finding response; new GET
│   │   │                                     /findings/{findingId}/notifications (FR-013)
│   │   └── sdas.py                        # EXTENDED — R-502: budget auto-created inside the
│   │                                         existing SDA-registration transaction
│   ├── governance/
│   │   ├── notifications.py               # NEW — FR-004–FR-013: "what's due today" query,
│   │   │                                     cadence/escalation state transitions
│   │   ├── budgets.py                     # NEW — FR-015–FR-017: threshold check, forecast
│   │   │                                     (R-506), overrun finding open/resolve
│   │   └── utilization.py                 # NEW — FR-018: active/idle state classification
│   │                                         (R-509, data-driven) + the live aggregate query
│   └── models/
│       └── (extends `finding` behaviorally + schema; adds `spend_record`, `budget`,
│             `notification`, `iam_hygiene_flag` — see data-model.md)
├── connectors/
│   └── aws.py                             # EXTENDED — R-503: `get_daily_spend()`
│                                             (`ce:GetCostAndUsage`), `iam_unused_analysis()`
│                                             (`iam:ListRoles`/`GetRole`/`ListUsers`/
│                                             `ListAccessKeys`/`GetAccessKeyLastUsed`) — the two
│                                             new AWS-SDK-touching functions this spec needs,
│                                             confined here per the connector-boundary gate
├── handlers/
│   ├── notification_worker_handler.py     # NEW — R-501, daily EventBridge trigger
│   ├── cost_ingestion_worker_handler.py    # NEW — R-503/R-505, daily EventBridge trigger
│   └── iam_hygiene_worker_handler.py       # NEW — R-503/R-510, weekly EventBridge trigger
├── migrations/versions/
│   └── 0012_cost_utilization_and_notifications.py   # NEW — additive migration (data-model.md)
└── tests/
    ├── unit/test_utilization.py                     # NEW
    ├── unit/test_budget_thresholds.py                # NEW
    ├── unit/test_notification_cadence.py             # NEW
    ├── integration/test_spend_api.py                 # NEW
    ├── integration/test_budget_overrun_finding.py     # NEW
    └── integration/test_iam_hygiene.py                # NEW

frontend/src/app/features/
├── cost/                                  # NEW — US1, P1
│   ├── cost-dashboard.component.ts             #   trend chart, per-project table, drill-down
│   └── cost.service.ts
├── utilization/                           # NEW — US6, P2
│   └── utilization.component.ts                #   account → project → resource drill-down
├── iam-hygiene/                           # NEW — US7, P2
│   └── iam-hygiene.component.ts                #   flag list, evidence detail
└── findings/
    └── findings-workbench.component.ts    # EXTENDED — R-508: renders `kind`/`sda`/
                                              `escalatedAt` on an existing finding row

infra/
├── modules/cost/                          # NEW module — mirrors governance/scan's own shape
│   ├── main.tf                                 #   3 Lambda functions, IAM roles/policies,
│   │                                             SES sandbox identity (research.md R-510)
│   ├── scheduler.tf                            #   3 EventBridge Scheduler rules (daily,
│   │                                             daily, weekly — R-510)
│   ├── variables.tf
│   └── outputs.tf
└── envs/{dev,prod}/main.tf                # EXTENDED — wires `module "cost"` in, same pattern
                                              as `module "governance"`/`module "scan"`
```

**Structure Decision**: Same monorepo, same split-by-deployable-concern layout specs 1–4
established. This spec adds one new Terraform module (`infra/modules/cost/`, R-510) and three new
Lambda functions — the first new compute since spec 003's governance workers — because the work
genuinely doesn't fit any existing module's ownership boundary (`governance` is spec 003's
tag-compliance/ownership pipeline; `scan` is spec 002's discovery orchestration; neither owns
spend, budgets, or IAM hygiene). Five new routers rather than folding into existing ones, mirroring
spec 004's own precedent (`resources.py` got its own file rather than joining `accounts.py`) — each
is a distinct top-level concept with its own filter/response shape. `notifications.py`/
`budgets.py`/`utilization.py` in `app/governance/` (not a new top-level package) because they are
governance-domain logic in the same sense spec 003's `scoring.py`/`validation.py` already are —
computing a signal from persisted platform data, not touching AWS directly (that stays confined to
`connectors/aws.py`, unchanged rule).

## Complexity Tracking

> No Constitution Check violations. This table flags necessary new infrastructure, not a
> violation — Complexity Tracking's stated purpose ("fill only if violations must be justified")
> doesn't strictly apply, but the same discipline is worth applying to a genuine new-infrastructure
> decision.

| New complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| Three new Lambda functions + EventBridge schedules (`infra/modules/cost/`) | FR-001–FR-020 need daily spend ingestion, daily/on-open notification sending, and periodic IAM analysis — none of these are request/response API work the existing API Lambda can serve; all three need to run on their own schedule independent of any user request. | Folding this work into the existing API Lambda via a synchronous endpoint a client polls — rejected: spend ingestion and IAM analysis are both genuinely background, scheduled work (FR-001's "daily," FR-019's periodic analysis), not something a request should trigger or wait on; notification's own day-2/4 cadence (FR-006) has no natural request to attach to at all. One combined Lambda for all three concerns — rejected per R-501/R-503's own reasoning: different failure/retry profiles and IAM permission surfaces (SES vs Cost Explorer vs IAM), the same split spec 003's governance workers already established for an analogous reason. |
| `finding.resource_id`/`rule_id`/`rule_version` become nullable (R-508) | FR-016 requires a budget-overrun finding to share spec 003's existing findings pipeline and lifecycle exactly — the alternative (a parallel table) would duplicate dedup, acknowledge, resolve, and this spec's own notification/escalation machinery for a second entity type. | A separate `budget_overrun_finding` table — rejected in research.md R-508 for the duplication reason above; it would also mean User Stories 2/3's "what's due today" notification query needs two independent sources instead of one. |
