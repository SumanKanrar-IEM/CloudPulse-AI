# Implementation Plan: Governance Dashboard

**Branch**: `pods/pod73-004-governance-dashboard` | **Date**: 2026-08-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-governance-dashboard/spec.md`

## Summary

This spec gives every role a single Angular dashboard over what specs 001–003 already built:
authenticated navigation, a compliance overview, a full inventory explorer, and a findings
workbench with acknowledgment and (real-or-seeded) AI suggestions — plus, as P2, on-demand scan
operations. The technical approach splits cleanly by how much backend already exists: compliance
overview and scan operations are pure frontend consuming APIs specs 002–003 already shipped;
the authenticated shell needs new sign-in/callback frontend work plus a small deploy-pipeline fix
(the runtime-config injection seam spec 002 built but never wired up); the inventory explorer
needs a genuinely new backend surface (`GET /resources`, paged and filtered — no general resource
listing endpoint exists yet, confirmed directly against the router directory, not assumed); and
the findings workbench needs two small additive schema pieces (finding acknowledgment metadata,
a remediation-suggestion entity) plus the admin-seed capability the spec's own Clarifications
round added (FR-020a).

Four decisions dominate the design, settled in [research.md](./research.md): how the frontend
learns its own API and Cognito configuration after a static build but before deploy, given the
seam for this was built in spec 002 and never finished (**R-401**); the Authorization Code + PKCE
flow needed for a public SPA client, and how to test it without a real Cognito dependency in CI
(**R-402**); why "missing owner tag" filtering and acknowledgment both stay clear of two things
that look similar but aren't — a tag-compliance Finding is not the same fact as an unattributed
`ResourceOwner`, and acknowledgment is not the same fact as the schema's already-reserved-but-unused
`suppressed` finding status (**R-403**, **R-404**); and how scan history reports resource deltas
with zero new persisted state (**R-405**).

## Technical Context

**Language/Version**: Python 3.12 (backend, AWS Lambda arm64) · TypeScript 5.5 / Angular 18
(frontend) — unchanged from specs 1–3, this spec adds no new language.

**Primary Dependencies**: FastAPI + Mangum, Pydantic v2, SQLAlchemy 2.0, Alembic, AWS Lambda
Powertools, boto3 (all already present, extended not replaced) · Angular Material + `ng2-charts`/
`chart.js` (**already installed** — `frontend/package.json` has carried both since spec 001's
scaffold; this spec is the first to actually render a chart with them) · `@axe-core/playwright`
(already present, spec 002's a11y suite) — this spec adds no new npm dependency.

**Storage**: Aurora Serverless v2 PostgreSQL 16 (spec 001's cluster). Two small additive pieces:
acknowledgment metadata on the existing `finding` table, and one new table,
`finding_remediation_suggestion` — see data-model.md. No new cluster, no new Lambda-hosted
database.

**Testing**: pytest + moto (unit) · Testcontainers PostgreSQL (integration, unchanged pattern) ·
Playwright + `@axe-core/playwright` (P1 dashboard journeys, extending spec 002's e2e harness) —
see research.md R-402 for how the sign-in/callback flow is tested without a live Cognito
dependency in CI.

**Target Platform**: AWS Lambda arm64 on Python 3.12 (existing API Lambda gets new routes; no new
Lambda function) · S3 + CloudFront (existing frontend hosting, unchanged) — no new Step Functions
state machine, no new SQS queue, no new Cognito pool, no new API Gateway (playbook §0.5.4).

**Project Type**: Web application in the existing monorepo — this spec adds to
`backend/app/api/routers/` (one new router, `resources.py`; extensions to `findings.py`),
`backend/app/models/` (additive schema), and almost entirely to `frontend/src/app/features/`
(four new feature areas) plus `frontend/src/app/core/` (the sign-in/callback auth flow) and
`.github/workflows/deploy-{dev,prod}.yml` (the runtime-config injection fix, R-401).

**Performance Goals**: SC-003's 2-second compliance-overview load at up to 5,000 resources is the
binding target; SC-006's "acknowledge reflected in the same interaction" is a UI-responsiveness
target, not a backend latency one (an optimistic UI update, confirmed by the API response, not a
blocking round-trip before any visual change). No other spec-level latency target exists — the
inventory explorer's and findings workbench's own page sizes are bounded by FR-011's server-side
paging regardless of the exact page size chosen (research.md does not set one; a reasonable
default, matching this project's established page-size conventions, belongs in `tasks.md`/
implementation, not this plan).

**Constraints**: Zero stored credentials (Principle III, unchanged) — the new sign-in flow stores
tokens in memory only (an Angular service, not `localStorage`), consistent with `AuthService`'s
existing signal-based, session-only design; nothing new persists a credential anywhere. Every
table this spec touches or adds is tenant-scoped (spec 1 FR-030, unchanged). No new IAM permission
on the scanner role — this spec adds no new AWS-account-scanning capability.

**Scale/Scope**: Demo-scale, matching specs 1–3's Assumptions. 28 functional requirements (all
numbered in spec.md, plus FR-020a/FR-028a from the clarify round), 8 success criteria, 5 user
stories (4 P1, 1 P2).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against CloudPulse AI Constitution **v2.0.1** — unchanged since spec 003's plan; no
amendment landed between specs 3 and 4.

| Principle | Gate | Pre-Phase-0 | Post-Phase-1 | How this plan satisfies it |
|---|---|---|---|---|
| I. Spec-First Delivery | Every artifact traces to a merged spec | PASS | PASS | Plan derives solely from spec.md's FR-001–FR-030 (incl. FR-020a/FR-028a) and its one Clarifications entry; every research.md decision cites the FR it serves. |
| II. AWS-Native Runtime & GitHub-Native Delivery | AWS runtime only; Bedrock Agents for product GenAI; GitHub-native delivery | PASS | PASS | Every component is an existing AWS managed service (Lambda, API Gateway, Cognito, Aurora, S3, CloudFront) reused, not a new one. No GenAI in this spec — spec 6 is the only spec that touches Bedrock; FR-020a's admin-seeded suggestion is explicitly test data, never a model call. `dependency-allowlist` and `connector-boundary` CI gates enforce this automatically; nothing new to wire. |
| III. Zero Stored Credentials | Roles only; OIDC for CI/CD; read-only scanning; immutable audit | PASS | PASS | No new connection mode, no new credential type. The sign-in flow (R-402) stores tokens in memory only, mirroring the platform's zero-persistence discipline at the frontend layer. Acknowledgment (FR-016) and suggestion-seeding (FR-020a) both write an `audit_event` per spec 1's FR-040, unchanged mechanism. |
| IV. Deterministic Core, Agentic Edge | Deterministic core; no model calls on core paths | PASS | PASS | Nothing in this spec calls a model. FR-020a's suggestion is explicitly non-AI test data, visibly marked as such — it does not simulate or stand in for spec 6's eventual agent output in a way that could be mistaken for it. Scan-history deltas (R-405) are computed deterministically from existing timestamp columns, not estimated. |
| V. Contract-First Modularity | Typed contracts at every boundary; rules as data | PASS | PASS | New OpenAPI paths are additive-only per spec 1's FR-048a, generated the same way specs 002–003's were. No provider SDK type leaks past `connectors/` — this spec makes no new AWS API call at all, only new reads/writes against the platform's own database. |
| VI. Test & Quality Gates | Lint, types, unit, integration with mocked AWS; red blocks merge | PASS | PASS | Same `ci.yml` gate specs 1–3 built — no new CI job needed. The sign-in/callback flow's Cognito interaction is tested via Playwright route interception (R-402), not a live IdP dependency, matching this project's own precedent for hard-to-mock external interactions. |
| VII. Solo Trunk-Based Delivery with AI Collaboration | `pods/pod73` sole long-lived branch; recorded AI review before merge | PASS | PASS | Same PR ritual as specs 1–3, `pr-task-reference` still enforcing task-ID citation automatically. |
| VIII. Honest Prioritization | P1/P2 tiered; P1 deliverable without any P2 | PASS | PASS | FR-021–FR-023 (scan operations) are this spec's only P2 requirements; dropping them leaves every P1 user story and SC-001, SC-002 (minus the scan-trigger half), SC-004–SC-007 intact. SC-008 is the one success criterion honestly tied to P2 completion — noted, not hidden. |

**Result: PASS at both gates.** No principle violations, Complexity Tracking is empty. This spec is
notably lighter than specs 2–3 on new AWS infrastructure — see research.md R-406 for why it adds
zero new billable resources, a genuine first for this project.

## Project Structure

### Documentation (this feature)

```text
specs/004-governance-dashboard/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions, cost profile, VERIFY markers
├── data-model.md         # Phase 1 output — new schema pieces, reused entities
├── quickstart.md         # Phase 1 output — validation guide mapped to success criteria
├── contracts/
│   └── openapi.yaml      # Phase 1 output — additive-only diff against the trunk contract
├── checklists/
│   └── requirements.md         # Spec quality checklist (16/16)
└── tasks.md              # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/routers/
│   │   ├── resources.py                   # NEW — FR-010–FR-013: GET /resources (paged,
│   │   │                                     filtered), GET /resources/{resourceId} (detail:
│   │   │                                     tags, owner+evidence, findings, enrichment)
│   │   ├── findings.py                    # EXTENDED — FR-015–FR-017, FR-020a: POST
│   │   │                                     /findings/{findingId}/acknowledge; GET/PUT
│   │   │                                     /findings/{findingId}/suggestion (admin write)
│   │   └── accounts.py                    # EXTENDED — FR-021: scan-history response gains
│   │                                         computed delta counts (R-405), no new route
│   ├── governance/
│   │   └── suggestions.py                 # NEW — thin read/write around
│   │                                         finding_remediation_suggestion, no logic beyond
│   │                                         the guarded "admin-seed only until spec 6 exists"
│   │                                         framing (FR-020a)
│   └── models/
│       └── (extends `finding` behaviorally; adds `finding_remediation_suggestion` — see
│             data-model.md)
├── migrations/versions/
│   └── 0011_finding_acknowledgment_and_suggestion.py   # NEW — additive migration
└── tests/
    ├── unit/test_resource_filters.py                  # NEW
    ├── integration/test_resources_api.py               # NEW
    ├── integration/test_finding_acknowledgment.py       # NEW
    └── integration/test_remediation_suggestion.py       # NEW

frontend/src/app/
├── core/
│   ├── auth.callback.component.ts         # NEW — R-402: exchanges the Cognito authorization
│   │                                         code (+ PKCE verifier) for tokens, calls GET /me,
│   │                                         populates AuthService, redirects to `returnTo`
│   ├── sign-in.component.ts               # NEW — redirects to Cognito Hosted UI's
│   │                                         `/oauth2/authorize` with a generated PKCE
│   │                                         challenge and state
│   ├── auth.service.ts                    # EXTENDED — token storage (memory-only) added
│   │                                         alongside the existing user-signal state
│   └── api-config.ts                      # EXTENDED — R-401: `cognitoDomain`/`cognitoClientId`/
│                                             `cognitoRedirectUri` added to
│                                             `window.__CLOUDPULSE_CONFIG__`, alongside the
│                                             already-present `apiBaseUrl`
├── shared/
│   └── shell.component.ts                 # EXTENDED — FR-003: real per-role nav items
│                                             replace the "Overview" placeholder; sign-out
│                                             control wired to `AuthService.signOut()`
└── features/
    ├── overview/                          # NEW — US2: score cards, findings-by-type/severity
    │   └── compliance-overview.component.ts   #   charts (ng2-charts), per-account table
    ├── inventory/                         # NEW — US3
    │   ├── inventory-explorer.component.ts     #   server-side paged/filtered table
    │   └── resource-detail.component.ts        #   tags, owner+evidence, findings, enrichment
    ├── findings/                          # NEW — US4
    │   └── findings-workbench.component.ts     #   list/filter, acknowledge, suggestion display
    │                                              (+ admin-only seed control, FR-020a)
    └── scans/                             # NEW — US5, P2
        └── scan-operations.component.ts        #   history + on-demand trigger with polled
                                                    live status (R-405)

.github/workflows/
├── deploy-dev.yml                         # EXTENDED — R-401: new step between "Terraform
│                                             apply" and "Publish the frontend" that injects
│                                             `window.__CLOUDPULSE_CONFIG__` into the already-
│                                             built `index.html`
└── deploy-prod.yml                        # EXTENDED — same fix, mirrored

infra/
├── envs/{dev,prod}/outputs.tf             # EXTENDED — re-exports `cognito_client_id` and
│                                             `cognito_hosted_ui_domain` from the identity
│                                             module (already computed there, never surfaced
│                                             at the env level until now)
└── modules/identity/main.tf               # EXTENDED — the app client's `callback_urls`
                                              already points at `/auth/callback` (spec 001);
                                              no change needed there, confirmed not assumed
```

**Structure Decision**: Same monorepo, same split-by-deployable-concern layout specs 1–3
established. Unlike specs 2–3, this spec adds no new Terraform module and no new Lambda function
— its only infrastructure change is two new Terraform outputs (re-exporting values the identity
module already computes) and a CI workflow step, not a new deployable unit. `resources.py` is a
new router (mirroring `rules.py`/`sdas.py`'s existing shape) rather than folding resource-listing
into `accounts.py`, because a resource is a distinct top-level concept from an account (one
account has many resources) and every other entity already gets its own router file. The four new
`frontend/src/app/features/` directories mirror `accounts/`/`sdas/`'s existing standalone-component
pattern exactly.

## Complexity Tracking

> No Constitution Check violations. This table is intentionally empty.

One decision is worth flagging as real, necessary scope rather than convenience, documented with
its reasoning in research.md: the sign-in/callback Authorization Code + PKCE flow (R-402) is
genuinely new frontend complexity with no simpler alternative — spec 001 provisioned the Cognito
app client for exactly this flow (`allowed_oauth_flows = ["code"]`, no client secret, meaning PKCE
is not optional for a public SPA client) and built the `callback_urls` routing for it, but no spec
before this one has ever built the frontend half. This is P1-blocking, demo-critical work, not
scope creep — nothing else in this spec is reachable without it (User Story 1 is every other
story's prerequisite).
