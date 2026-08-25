# Implementation Plan: Tag Compliance and Ownership

**Branch**: `pods/pod73-003-tag-compliance-and-ownership` | **Date**: 2026-08-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-tag-compliance-and-ownership/spec.md`

## Summary

This spec turns spec 002's raw inventory into governance signal: tagging rules stored as
admin-editable data, an SDA (internal project) registry resources attach to at scan time,
a validation engine that opens and auto-closes findings against top-level resources only,
compliance scoring per account and per SDA, and audit-trail-based ownership attribution with a
fallback chain and configurable email resolution. The technical approach: rules and SDAs reuse
spec 1's already-reserved `Rule`/`Sda` tables (versioned JSONB definitions, no new schema); a scan's
governance pipeline runs as two new SQS-queued Lambda workers — one for validation/SDA-matching/
scoring, one for ownership attribution — enqueued when `finalize_scan` completes rather than
embedded in that same Lambda invocation, because ownership attribution's CloudTrail sweep does not
fit a scan's existing per-unit timeout budget at demo-scale resource counts. Ownership attribution
reads AWS CloudTrail's always-on, zero-setup Event History via one bulk, time-windowed sweep per
scan — never a per-resource lookup — correlating each creation/modification event's response
elements against the account's current inventory.

Three decisions dominate the design, settled in [research.md](./research.md): how a finding stays
tied to a rule across edits without a new column, given `Finding.rule_id` is a foreign key to one
specific versioned `Rule` row (**re-pointing the FK to the newest enabled version on re-evaluation,
found by joining through `Rule.key` rather than `rule_id` directly** — R-301); how ownership
attribution avoids one CloudTrail call per resource at tens-of-thousands-of-resources scale
(**one bulk, paginated `LookupEvents` sweep per scan, not N per-resource lookups** — R-302); and
how the governance pipeline plugs into spec 002's existing scan lifecycle without spec 003 inventing
a second orchestration mechanism, while still following the platform-wide "SQS + Lambda workers for
validation and ownership" direction (**`finalize_scan` enqueues one SQS message per finalized scan;
the workers are event-driven consumers of the scan lifecycle, not a competing orchestrator** —
R-303).

## Technical Context

**Language/Version**: Python 3.12 (backend, AWS Lambda arm64) · TypeScript 5.5 / Angular 18
(frontend, P2 only — the SDA admin UI, S18b) — unchanged from specs 1–2, this spec adds no new
language.

**Primary Dependencies**: FastAPI + Mangum, Pydantic v2, SQLAlchemy 2.0, Alembic, AWS Lambda
Powertools, boto3 (all already present) · AWS SQS (new: two queues driving the validation and
ownership-attribution workers) · Angular Material (P2 SDA admin screen only, reusing spec 002's
accounts-admin patterns).

**Storage**: Aurora Serverless v2 PostgreSQL 16 (spec 1's cluster; this spec's migrations extend
`resource` behaviorally via the already-existing `parent_resource_id` column, and add one new P2
table — `owner_identity_override` — plus one new nullable P2 column on `tenant` — no new cluster,
no new table for `Rule`/`Finding`/`Sda`/`ResourceOwner`, all four already exist with the right
shape from spec 1).

**Testing**: pytest + moto (unit, no credentials — CloudTrail's `lookup_events` mocked) ·
Testcontainers PostgreSQL (integration, unchanged pattern from specs 1–2) · Playwright (the SDA
admin screen journey, P2, extending spec 002's e2e harness) — see research.md R-307 for moto's
CloudTrail fidelity, unverified before this plan, same VERIFY discipline as spec 002's R-209.

**Target Platform**: AWS Lambda arm64 on Python 3.12 (existing API Lambda gets new routes; two new
SQS-triggered Lambda workers: `compliance-validation-worker`, `ownership-attribution-worker`) — no
new Step Functions state machine, no new API Gateway, no new Cognito pool (playbook §0.5.4).

**Project Type**: Web application in the existing monorepo — this spec adds to
`backend/app/governance/` (new package: validation, scoring, SDA matching, ownership attribution),
`backend/connectors/aws.py` (one new read-only method: CloudTrail event sweep, still behind the
FR-054 connector boundary), `infra/modules/governance/` (new Terraform module: two SQS queues +
two Lambda workers), and route groups in `backend/app/api/routers/` (rules, SDAs, findings,
compliance scores, ownership).

**Performance Goals**: SC-003's "matches a hand count" accuracy target (correctness, not speed) is
the binding one; no spec-level latency SC exists (deferred to this plan per `/speckit-clarify`'s
Outstanding note). Working target: the compliance-validation worker completes within one SQS
visibility timeout (30s, matching the existing scan-worker Lambda's demo-scale sizing) for a
demo-scale account's resource count; the ownership-attribution worker's CloudTrail sweep is bounded
by `LookupEvents`' own pagination, not resource count, so it scales independently (R-302).

**Constraints**: Zero stored credentials (Principle III, unchanged) — the CloudTrail sweep uses the
same scanner-role session spec 002's discovery already establishes per scan unit, extended with one
additional read-only IAM action (`cloudtrail:LookupEvents`), never a new trust relationship or
connection mode. No write, modify, or delete permission against any scanned account, ever
(unchanged from spec 002's FR-005 precedent). Every table this spec touches or adds is
tenant-scoped (spec 1 FR-030, unchanged).

**Scale/Scope**: Demo-scale, matching specs 1–2's Assumptions — a handful of connected accounts,
tens of thousands of resources in the largest one, 2 environments. 30 functional requirements (all
numbered in spec.md), 8 success criteria, 5 P1 user stories, 3 P2 user stories.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against CloudPulse AI Constitution **v2.0.1** — unchanged since spec 002's plan; no
amendment landed between specs 2 and 3.

| Principle | Gate | Pre-Phase-0 | Post-Phase-1 | How this plan satisfies it |
|---|---|---|---|---|
| I. Spec-First Delivery | Every artifact traces to a merged spec | PASS | PASS | Plan derives solely from spec.md's FR-001–FR-030 and its one Clarifications entry; every research.md decision cites the FR it serves. |
| II. AWS-Native Runtime & GitHub-Native Delivery | AWS runtime only; Bedrock Agents for product GenAI; GitHub-native delivery | PASS | PASS | Every new component (SQS, Lambda, CloudTrail Event History reads) is an AWS managed service or AWS SDK call. No GenAI in this spec — spec 6 is the only spec that touches Bedrock. `dependency-allowlist` and `connector-boundary` CI gates enforce this automatically; nothing new to wire. |
| III. Zero Stored Credentials | Roles only; OIDC for CI/CD; read-only scanning; immutable audit | PASS | PASS | No new connection mode, no new credential type — the one new IAM action (`cloudtrail:LookupEvents`) is read-only, added to the same scanner role spec 002 already established. Every rule/SDA/override management action writes an `audit_event` per spec 1's FR-040, unchanged mechanism. |
| IV. Deterministic Core, Agentic Edge | Deterministic core; no model calls on core paths | PASS | PASS | Validation, SDA matching, scoring, and attribution are pure SQLAlchemy/boto3 logic — no model call anywhere in this spec. This spec's findings and ownership data are exactly what spec 6's future coverage/remediation advisor will eventually read, but this spec contains no agent code itself. |
| V. Contract-First Modularity | Typed contracts at every boundary; rules as data | PASS | PASS | Tagging rules (`Rule.definition`) and SDA mappings (`Sda.tag_values`) are both already-JSONB, admin-editable data — FR-001/FR-007 make this a spec requirement, not just a nice-to-have. The CloudTrail sweep stays behind `connectors/aws.py`'s existing boundary (FR-054), never leaking a boto3 CloudTrail type past it. New OpenAPI paths are additive-only per spec 1's FR-048a, generated the same way spec 002's were. |
| VI. Test & Quality Gates | Lint, types, unit, integration with mocked AWS; red blocks merge | PASS | PASS | Same `ci.yml` gate specs 1–2 built — no new CI job needed. moto's CloudTrail fidelity is a VERIFY marker (R-307), confirmed empirically before the test file that depends on it is written, same discipline as spec 002's R-209. |
| VII. Solo Trunk-Based Delivery with AI Collaboration | `pods/pod73` sole long-lived branch; recorded AI review before merge | PASS | PASS | Same PR ritual as specs 1–2, `pr-task-reference` still enforcing task-ID citation automatically. |
| VIII. Honest Prioritization | P1/P2 tiered; P1 deliverable without any P2 | PASS | PASS | FR-011/FR-012 (SDA admin UI), FR-024–FR-026 (attribution fallback), and FR-027/FR-028 (identity resolution) are this spec's only P2 requirements; dropping all three leaves every P1 user story and SC-001–SC-004, SC-006–SC-008 intact. SC-005 needs P2's fallback chain to be exercised, so it is the one success criterion honestly tied to P2 completion — noted, not hidden. |

**Result: PASS at both gates.** No principle violations, so Complexity Tracking is empty. One design
tension is resolved in research.md rather than by exception — see R-302 (CloudTrail sweep strategy
at scale) and R-303 (governance pipeline's orchestration boundary, reconciling this spec's own
Dependencies-section wording with the platform-wide SQS+Lambda-workers direction given at plan
time).

## Project Structure

### Documentation (this feature)

```text
specs/003-tag-compliance-and-ownership/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions, cost profile, VERIFY markers
├── data-model.md         # Phase 1 output — Rule/Finding/Sda/ResourceOwner behavior, two P2 additions
├── quickstart.md         # Phase 1 output — validation guide mapped to success criteria
├── contracts/
│   └── openapi.yaml      # Phase 1 output — additive-only diff against the trunk contract
├── checklists/
│   └── requirements.md         # Spec quality checklist (16/16)
└── tasks.md              # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
infra/                                     # Terraform — this spec adds one module, extends none
├── modules/
│   ├── governance/                        # NEW — two SQS queues (+ DLQs), two Lambda workers,
│   │   └── main.tf                        #   IAM scoped to sqs:*/lambda invoke plus the one new
│   │                                         cloudtrail:LookupEvents grant on spec 002's scanner
│   │                                         role IAM policy (extended, not a new role)
│   └── scan/                              # UNCHANGED except one addition: finalize_scan enqueues
│                                             to the two new queues (T-level detail, not a module
│                                             change — the enqueue call lives in application code)
└── envs/{dev,prod}/                       # Wires the new governance module in alongside existing ones

backend/
├── app/
│   ├── api/routers/
│   │   ├── rules.py                       # NEW — FR-001–FR-006a rule CRUD (admin write, all-role read)
│   │   ├── sdas.py                        # NEW — FR-007–FR-010b SDA registry incl. removal (admin write, all-role read)
│   │   ├── findings.py                    # NEW — FR-014–FR-017 findings list (all-role read, no write route)
│   │   ├── compliance.py                  # NEW — FR-018–FR-019a score endpoints (all-role read)
│   │   ├── ownership.py                   # NEW — FR-020–FR-028 ownership read + P2 override management
│   │   └── (existing spec 002 routers unchanged)
│   ├── governance/                        # NEW package — mirrors app/scan/'s shape
│   │   ├── validation.py                  #   rule evaluation, finding open/auto-close (FR-013–FR-017)
│   │   ├── sda_matching.py                #   tag-value mapping match + overlap rejection (FR-008–FR-010a)
│   │   ├── scoring.py                     #   compliance score computation (FR-018–FR-019a)
│   │   └── ownership.py                   #   attribution + fallback + identity resolution (FR-020–FR-028)
│   ├── core/
│   │   └── (unchanged — reuses spec 1's require_role, audit, logging, db modules directly)
│   └── models/
│       └── (extends spec 1's Rule/Finding/Sda/ResourceOwner behaviorally; adds one P2 table + one
│             P2 tenant column — see data-model.md)
├── connectors/
│   └── aws.py                             # EXTENDED — one new method: bulk CloudTrail Event History
│                                             sweep for a (account, region, 90-day window), still
│                                             behind FR-054's boundary
├── migrations/versions/
│   └── 0010_owner_identity_override.py   # NEW — P2-only additive migration (see data-model.md)
└── handlers/
    ├── compliance_validation_worker_handler.py   # NEW — SQS-triggered, FR-013–FR-019a
    └── ownership_attribution_worker_handler.py    # NEW — SQS-triggered, FR-020–FR-028

frontend/src/app/features/
└── sdas/                                  # NEW — P2 only (S18b)
    ├── sdas-list.component.ts             # FR-011 — admin CRUD
    └── no-sda-triage.component.ts         # FR-012 — triage list
```

**Structure Decision**: Same monorepo, same split-by-deployable-concern layout specs 1–2
established. `backend/app/governance/` is a new package (mirroring `app/scan/`'s existing shape)
rather than folding into `app/scan/` itself, because this spec's steps are triggered by a scan's
completion but are not themselves scan orchestration — keeping them separate matches Principle V's
"a new capability is a new module, not a widened existing one" spirit, and keeps `app/scan/`'s own
FR-054 boundary exemption (`orchestrator.py`'s one allowlisted boto3 call) from needing to grow to
cover a second, unrelated concern. `infra/modules/governance/` is the one genuinely new piece of
infrastructure; everything else extends an existing module, Lambda, or table.

## Complexity Tracking

> No Constitution Check violations. This table is intentionally empty.

One decision adds real complexity but is required by a real, plan-time-discovered constraint
rather than chosen for convenience, documented with its rejected alternative in research.md: the
CloudTrail bulk-sweep pattern (R-302), required because a naive per-resource `LookupEvents` call
does not scale to spec 002's own documented "tens of thousands of resources" Edge Case within a
single Lambda invocation's timeout — not a hypothetical, a demo-scale-relevant Constraints
consequence.
