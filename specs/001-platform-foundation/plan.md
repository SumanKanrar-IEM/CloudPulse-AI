# Implementation Plan: Platform Foundation

**Branch**: `pods/pod73-001-platform-foundation` | **Date**: 2026-08-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-platform-foundation/spec.md`

## Summary

This spec builds the ground every other CloudPulse AI spec stands on: the monorepo scaffold, the
Terraform baseline for two environments, the GitHub Actions pipelines that gate and deliver them,
the Aurora-backed governance schema, Cognito identity with three roles, and the FastAPI skeleton
whose OpenAPI document is the binding contract for specs 2–6.

The technical approach is a single Python 3.12 API Lambda (FastAPI + Mangum on arm64) behind an
API Gateway HTTP API with a Cognito JWT authorizer, talking to Aurora Serverless v2 PostgreSQL
through SQLAlchemy 2 with Alembic migrations applied during deployment. An Angular 18 SPA on
S3 + CloudFront consumes a client generated from the published OpenAPI schema. Everything is
Terraform, everything is deployed by GitHub Actions authenticating through OIDC, and nothing
stores a credential.

Three decisions dominate the design and are settled in [research.md](./research.md): how migrations
reach a VPC-private Aurora cluster from a runner that lives outside the VPC (**a migration Lambda
invoked by the pipeline**), how Cognito's multi-valued group claim is reconciled with FR-032a's
"exactly one role" rule (**a pre-token-generation Lambda plus a defence-in-depth API check**), and
how integration tests get a credible AWS in CI when LocalStack's free tier covers neither Cognito
nor Aurora (**Testcontainers PostgreSQL for the database, moto for AWS APIs, a locally-signed JWT
for the authorizer, and LocalStack only for the services it genuinely supports**).

## Technical Context

**Language/Version**: Python 3.12 (backend, AWS Lambda arm64) · TypeScript 5.5 / Angular 18
(frontend) · HCL with Terraform >= 1.9 (infrastructure)

**Primary Dependencies**: FastAPI + Mangum, Pydantic v2, SQLAlchemy 2.0, Alembic, AWS Lambda
Powertools for Python (logging, tracing, metrics), boto3 · Angular Material, ng2-charts,
`@openapitools/openapi-generator-cli` · Terraform AWS provider ~> 5.x

**Storage**: Aurora Serverless v2 PostgreSQL 16 (governance record, every table tenant-scoped) ·
S3 for immutable raw scan snapshots (consumed by spec 2; this spec provisions the bucket and its
lifecycle policy only)

**Testing**: pytest + moto (unit, no credentials) · Testcontainers PostgreSQL + LocalStack
(integration in CI) · Playwright (P1 dashboard journeys) · `oasdiff` (contract compatibility gate)
· `@angular-eslint` template accessibility rules + axe-core via Playwright (accessibility gate)

**Target Platform**: AWS Lambda arm64 on the Python 3.12 runtime; API Gateway HTTP API;
CloudFront + S3 for the SPA; evergreen browsers (Chrome, Firefox, Safari, Edge — current and
previous major)

**Project Type**: Web application in a monorepo — `infra/`, `backend/`, `frontend/`, `agents/`,
`ops/`, `.github/`, `.claude/`

**Performance Goals**: Demo-scale. ~10 concurrent users, 1 tenant, 2 environments. API p95 under
800 ms for warm skeleton endpoints; cold start under 3 s. CI check suite reports in under 10 min
(SC-004); a trunk merge is live in dev within 15 min (SC-005); a fresh account reaches a working
dev environment in under 60 min (SC-001), inclusive of the single FR-001a bootstrap step.

**Constraints**: Zero stored credentials anywhere (Principle III) — GitHub OIDC for CI/CD, IAM
roles for cloud access. Retention is fixed by clarification: audit events indefinite, structured
logs 30 days, prod backups 7 days. The OpenAPI document is additive-only and gated by CI.
Prod's data store carries deletion protection and the routine teardown path must refuse prod.

**Scale/Scope**: 1 seeded tenant with a tenant-aware schema throughout · 2 environments (dev,
prod) · 3 roles · 10 governance entities · ~8 skeleton endpoints · 5 downstream specs consuming
this foundation · 73 functional requirements, 17 success criteria

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against CloudPulse AI Constitution **v2.0.0** (amended 2026-08-22: solo delivery with AI collaboration; Claude Code named as the permitted development-time engine).

| Principle | Gate | Pre-Phase-0 | Post-Phase-1 | How this plan satisfies it |
|---|---|---|---|---|
| I. Spec-First Delivery | Every artifact traces to a merged spec | PASS | PASS | Plan derives solely from spec.md's FR-001–FR-053; every design decision in research.md cites the FR it serves. No capability is introduced that the spec does not require. |
| II. AWS-Native Runtime & GitHub-Native Delivery | AWS runtime only; Bedrock Agents for product GenAI; GitHub-native delivery; Claude Code permitted development-time | PASS | PASS | Every runtime component is an AWS managed service (Lambda, API Gateway, Aurora Serverless v2, Cognito, S3, CloudFront, CloudWatch). No GenAI in this spec — the connector and agent packages are scaffolded empty for specs 2 and 6. Delivery is GitHub Actions, Issues/Projects, Spec Kit; Claude Code drives the lifecycle as a development-time engine only. **FR-013a now enforces this with a CI dependency-allowlist gate** rather than a README statement. Test-time containers are developer tooling, not runtime components. |
| III. Zero Stored Credentials | Roles only; OIDC for CI/CD; read-only scanning; immutable audit | PASS | PASS | CI/CD assumes a role via GitHub OIDC with no static keys. Aurora credentials live in Secrets Manager and are fetched by the Lambda execution role at runtime — never in source, never in Terraform state as plaintext, never in a GitHub secret. `audit_event` is append-only and never expires (FR-029a). Bootstrap is the one manual step and is documented as such. |
| IV. Deterministic Core, Agentic Edge | Deterministic core; no model calls on core paths | PASS | PASS | This spec contains no model calls at all. Provisioning is idempotent Terraform, migrations are ordered and versioned. Nothing here is non-deterministic. |
| V. Contract-First Modularity | Typed contracts at every boundary; rules as data | PASS | PASS | OpenAPI is generated from FastAPI's Pydantic v2 models and published as the binding contract (FR-048); the Angular client is generated from it and drift fails CI. `connectors/` ships the provider-agnostic interface with no provider SDK types crossing it. Group-to-role mapping is Terraform data, not code (FR-039a). |
| VI. Test & Quality Gates | Lint, types, unit, integration with mocked AWS; red blocks merge | PASS | PASS | `ci.yml` runs ruff, mypy, pytest+moto, Angular build, `terraform validate`/`plan`, `oasdiff`, and accessibility lint — the seven categories of FR-009. Branch protection on `pods/pod73` makes them required with no override (FR-011). |
| VII. Solo Trunk-Based Delivery with AI Collaboration | `pods/pod73` sole long-lived branch; small PRs; recorded AI review before merge | PASS | PASS | All workflow triggers target `pods/pod73`; no workflow references `main` or `master`. Work is sequenced into nine milestones sized for same-day PRs by one maintainer. Self-merge is permitted only behind green CI plus a recorded AI review; specs are authored sequentially 001→006 rather than owned in parallel. |
| VIII. Honest Prioritization | P1/P2 tiered; P1 deliverable without any P2 | PASS | PASS | Milestones M0–M7 are P1 and complete the demo path. M8 (observability, S7) is the only P2 milestone and is last; removing it entirely leaves every P1 success criterion still met. |

**Result: PASS at both gates.** No principle violations, so Complexity Tracking is empty. Three
design tensions were resolved in research.md rather than by exception — see R-002 (migrations into
a private subnet), R-004 (Cognito multi-group claim), and R-007 (integration testing without
LocalStack Cognito/RDS).

## Project Structure

### Documentation (this feature)

```text
specs/001-platform-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 output — 12 decisions with alternatives
├── data-model.md        # Phase 1 output — 10 entities, constraints, migration order
├── quickstart.md        # Phase 1 output — validation guide mapped to success criteria
├── contracts/
│   └── openapi.yaml     # Phase 1 output — the skeleton contract specs 2-6 extend
├── checklists/
│   └── requirements.md  # Spec quality checklist (20/20)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
infra/                              # Terraform — owned by this spec
├── bootstrap/                      # One-time, run by a human: state backend + OIDC role
│   ├── main.tf                     #   S3 state bucket, DynamoDB lock table
│   └── oidc.tf                     #   GitHub OIDC provider + deploy role (trust scoped to pods/pod73)
├── modules/
│   ├── network/                    # VPC, private subnets, endpoints (no NAT gateway)
│   ├── database/                   # Aurora Serverless v2, Secrets Manager, deletion protection
│   ├── identity/                   # Cognito user pool, 3 groups, pre-token-generation Lambda
│   ├── api/                        # HTTP API, JWT authorizer, API Lambda, migration Lambda
│   ├── frontend/                   # S3 origin, CloudFront, OAC
│   └── observability/              # [P2] dashboard, alarms, SNS email topic
└── envs/
    ├── dev/                        # terraform.tfvars + backend config
    └── prod/                       # terraform.tfvars + backend config (deletion protection on)

backend/
├── app/
│   ├── api/
│   │   ├── main.py                 # FastAPI app + Mangum handler
│   │   ├── deps.py                 # Auth/tenant/session dependencies
│   │   ├── errors.py               # Uniform error envelope (FR-043)
│   │   ├── middleware.py           # Correlation id, Powertools logging (FR-044, FR-045)
│   │   └── routers/
│   │       ├── health.py           # FR-041, FR-042
│   │       └── me.py               # Current identity + resolved role
│   ├── workers/                    # Empty package — specs 2, 3, 5 add SQS workers here
│   ├── scan/                       # Empty package — spec 2 adds the discovery engine
│   ├── core/
│   │   ├── config.py               # Pydantic Settings
│   │   ├── db.py                   # SQLAlchemy engine/session, Secrets Manager fetch
│   │   ├── security.py             # Role resolution, require_role dependency (FR-034)
│   │   ├── audit.py                # write_audit_event helper (FR-040)
│   │   └── logging.py              # Powertools logger with redaction (FR-046)
│   └── models/                     # SQLAlchemy 2 declarative models (10 entities)
├── connectors/
│   ├── base.py                     # Provider-agnostic connector protocol (Principle V)
│   └── normalized.py               # Normalized resource model — spec 2 implements against it
├── migrations/                     # Alembic; versions/ ordered, each declaring reversibility
│   ├── env.py
│   └── versions/
├── handlers/
│   ├── api_handler.py              # Lambda entrypoint -> Mangum
│   ├── migrate_handler.py          # Migration Lambda (R-002)
│   └── pre_token_handler.py        # Cognito pre-token-generation (R-004)
└── tests/
    ├── unit/                       # pytest + moto, no credentials (FR-010)
    ├── integration/                # Testcontainers PostgreSQL + LocalStack (R-007)
    └── conftest.py

frontend/
├── src/app/
│   ├── core/                       # Auth guard, HTTP interceptors, error handling
│   ├── shared/                     # Layout shell, nav, a11y-checked components
│   ├── features/                   # Empty — specs 2-5 add feature routes here
│   └── api/                        # GENERATED from contracts/openapi.yaml — never hand-edited
├── e2e/                            # Playwright, includes axe-core a11y assertions
└── angular.json

agents/                             # Scaffold only — spec 6 owns the contents
├── definitions/
├── action-groups/
├── prompts/
└── evals/

ops/
├── runbooks/                       # Provisioning runbook (FR-006), first-admin procedure (FR-039)
└── erd/                            # ERD source + rendered diagram (FR-028)

.github/workflows/
├── ci.yml                          # PR gate — 7 check categories (FR-009)
├── deploy-dev.yml                  # On merge to pods/pod73 (FR-015)
└── deploy-prod.yml                 # Environment approval gate (FR-017)
```

**Structure Decision**: Monorepo, as directed. The split is by deployable concern rather than by
layer, which keeps each spec's ownership boundary obvious in the tree: spec 2 fills `app/scan/`
and `connectors/`, spec 3 and 5 fill `app/workers/`, spec 4 fills `frontend/src/app/features/`,
and spec 6 fills `agents/`. This spec creates every one of those directories with its boundary
constraint in place and leaves the implementations empty (FR-054 to FR-057), so each later spec
begins against a settled seam rather than negotiating one mid-build. Specs are authored
sequentially 001→006 by a single maintainer, so the value is settled contracts over time rather
than parallel non-collision. `frontend/src/app/api/` is generated output and is regenerated in CI —
a hand-edit there is a merge-blocking drift failure (FR-048).

## Implementation Sequence

P1 milestones M0–M7 complete the demo path. M8 is the only P2 work and is strictly last; deleting
it leaves every P1 success criterion satisfied (Principle VIII).

| # | Milestone | Tier | Delivers | Proves |
|---|---|---|---|---|
| M0 | Monorepo scaffold + CI gate | P1 | Directory tree, tooling config, `ci.yml` with all 7 checks, branch protection | SC-003, SC-004 |
| M1 | Terraform bootstrap + baseline | P1 | State backend, GitHub OIDC role, network, S3 buckets | SC-001 (partial), SC-012 |
| M2 | Aurora + schema + migrations | P1 | Cluster, Secrets Manager, 10-entity schema, migration Lambda, ERD | SC-007 |
| M3 | API skeleton | P1 | Health, error envelope, correlation ids, structured logs, published OpenAPI | SC-009, SC-010 |
| M4 | CD to dev | P1 | `deploy-dev.yml` incl. migration invocation, deployment records | SC-005 |
| M5 | Cognito identity + role enforcement | P1 | User pool, 3 groups, pre-token Lambda, JWT authorizer, `require_role` | SC-008, SC-013 |
| M6 | Frontend shell + generated client | P1 | Angular shell, auth flow, CloudFront, generated API client, a11y gate | SC-015 |
| M7 | Prod environment + approval gate | P1 | Prod stack, deletion protection, backups, `deploy-prod.yml`, retention | SC-002, SC-006, SC-014 |
| M7a | Architectural boundaries | P1 | Dependency-allowlist gate, connector-package boundary check, agent read-only access path, breaking-change procedure | SC-016, SC-017 |
| M8 | Observability | **P2** | Dashboard, alarms, SNS email | SC-011 |

**Dependency notes**: M7a's gates land inside M0's `ci.yml` where possible and are listed
separately only because the requirements they enforce (FR-013a, FR-054 to FR-057) were added after
the first analyze pass. M0 needs no AWS account and can start immediately. M2 blocks M3 (models),
M3 blocks M4 (something to deploy) and M6 (contract to generate from). M5 can proceed in parallel
with M3 once M1 lands. M7 repeats M1–M6 against the prod workspace and adds only the gate,
protection, and retention settings.

## Complexity Tracking

> No Constitution Check violations. This table is intentionally empty.

Three decisions add real complexity but are each required by a spec requirement rather than chosen
for convenience, and are documented with their rejected alternatives in research.md: the migration
Lambda (R-002, required by FR-016 given a VPC-private cluster), the pre-token-generation Lambda
(R-004, required by FR-032a's single-role rule against Cognito's multi-valued group claim), and the
split integration-test strategy (R-007, required by FR-010 and Principle VI given LocalStack's
coverage gaps).
