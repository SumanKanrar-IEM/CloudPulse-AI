---

description: "Task list for 001-platform-foundation"
---

# Tasks: Platform Foundation

**Input**: Design documents from `/specs/001-platform-foundation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/openapi.yaml](./contracts/openapi.yaml)

**Tests**: Included. Constitution Principle VI makes lint, type checks, unit tests, and — for
cloud-touching code — integration tests with mocked AWS a merge requirement, so test tasks are not
optional here.

**Constitution**: v2.0.0 — solo delivery with AI collaboration. Every PR merges behind green CI
plus a recorded AI review; there is no second-human gate. Tasks are sized for one maintainer.

**Revision**: regenerated 2026-08-22 after `/speckit-analyze`. Fifteen findings resolved — see
"Analyze remediation" at the foot of this file.

## Format: `[ID] [P?] [Story] Description — S#, FR-###`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1–US7 from spec.md. Setup, Foundational, and Polish tasks carry no story label
- **S#**: Backlog story ID · **FR-###/SC-###**: the spec requirement the task satisfies
- Every task is sized for one short-lived `pods/pod73-XXX` branch and a same-day PR (Principle VII)

## Path Conventions

Monorepo per plan.md: `infra/`, `backend/`, `frontend/`, `agents/`, `ops/`, `.github/`.

## Tier Summary

**P1 (demo-critical, frozen)**: Phases 1–8, T001–T112. Completing these satisfies SC-001 through
SC-010 and SC-012 through SC-017.
**P2 (stretch)**: Phase 9 only, T113–T121. Every P2 task is marked **[P2]** in its description.
Deleting Phase 9 entirely leaves the P1 demo path intact — that is the Principle VIII check.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Monorepo scaffold and tooling. No AWS account needed — this phase can start
immediately and in parallel with account provisioning.

- [X] T001 Create the monorepo directory tree per plan.md (`infra/`, `backend/`, `frontend/`, `agents/`, `ops/`, `.github/workflows/`) with a `.gitkeep` in each empty package — S1, FR-001
- [X] T002 [P] Initialize the Python project in `backend/pyproject.toml` with Python 3.12, FastAPI, Mangum, Pydantic v2, SQLAlchemy 2, Alembic, aws-lambda-powertools, boto3, and dev extras (pytest, moto, testcontainers, ruff, mypy) — S2, FR-013a
- [X] T003 [P] Initialize the Angular 18 project in `frontend/` with standalone components, Angular Material, and ng2-charts — S2, FR-047
- [X] T004 [P] Configure ruff and mypy in `backend/pyproject.toml` with strict settings, and eslint plus `@angular-eslint` template accessibility rules in `frontend/.eslintrc.json` — S2, FR-009, FR-047b
- [X] T005 [P] Create `Makefile` at repo root with a `check` target running the full local gate, mirroring the seven CI categories — S2, FR-009
- [X] T006 [P] Create empty packages with their `__init__.py` for `backend/app/workers/`, `backend/app/scan/`, and `frontend/src/app/features/`, each with a README naming its owning spec — S1, FR-055
- [X] T007 [P] Create the `agents/` scaffold (`definitions/`, `action-groups/`, `prompts/`, `evals/`) with a README stating spec 6 owns the contents, that agents reach data only via the read-only tenant-scoped API path, and that no non-AWS AI runtime may be introduced — S1, FR-056, FR-013a
- [X] T008 [P] Create the reserved `backend/connectors/` package with a README stating that spec 2 (S11) defines the connector protocol and normalized resource model, and that no cloud-provider SDK type may cross out of this package — S1, FR-054
- [X] T009 [P] Add `.gitignore`, `.editorconfig`, and `CODEOWNERS` assigning every path to the sole maintainer, so the review requirement is enforced by the repository rather than by habit — S1, Principle VII
- [X] T010 [P] Write `ops/runbooks/provisioning.md` skeleton with the prerequisite list from quickstart.md — S1, FR-006

**Checkpoint**: The tree exists, tooling runs locally, and five downstream specs have their
landing zones.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Terraform state, OIDC trust, and network. Nothing that touches AWS can proceed until
this is done.

**⚠️ CRITICAL**: T011–T013 are the one manual bootstrap step identified in research.md R-001.
Everything after them runs through OIDC with zero stored credentials.

- [X] T011 Write `infra/bootstrap/main.tf` creating the versioned, encrypted, public-access-blocked S3 state bucket and the DynamoDB lock table — S1, FR-001, R-001
- [X] T012 Write `infra/bootstrap/oidc.tf` creating the GitHub OIDC provider and deploy role, with the trust policy scoped to this repository and the `pods/pod73` trunk only — S1, FR-022, Principle III
- [X] T013 Apply `infra/bootstrap/` to the dev account by hand — the single manual step FR-001a permits — record the deploy role ARN as a repository variable, verify it created no long-lived credential, and document it in `ops/runbooks/provisioning.md` — S1, FR-001a, FR-006, R-001
- [X] T014 [P] Write `infra/modules/network/` — VPC, private subnets, VPC endpoints for Secrets Manager and S3, and no NAT gateway — S1, FR-001
- [X] T015 [P] Write `infra/envs/dev/` and `infra/envs/prod/` root modules with backend config and per-environment `terraform.tfvars`, sharing one module set — S1, FR-002
- [X] T016 [P] Write `backend/app/core/config.py` with Pydantic Settings, sourcing every value from environment or Secrets Manager and none from a committed file — S6, FR-007
- [X] T017 [P] Write `backend/tests/conftest.py` with the shared pytest fixtures: moto mocks, Testcontainers PostgreSQL, and the local RSA keypair JWT signer from research.md R-007 — S2, FR-010

**Checkpoint**: `terraform plan` runs clean against dev via OIDC. User story work can begin.

---

## Phase 3: User Story 2 — Block a bad change before it reaches the trunk (Priority: P1) 🎯 MVP

**Goal**: Every PR is automatically checked across nine categories, and a red check blocks merge —
including for the maintainer, who is also the author of every PR.

**Independent Test**: Open one PR per check category, each breaking exactly one thing, and confirm
each independently turns the PR red and makes merge unavailable.

**Why first**: This phase gates every phase after it. With a single maintainer and no second-human
review, CI plus the automated AI review is the *only* thing between a mistake and the trunk —
which makes landing it before there is much code to check more important here, not less.

### Tests for User Story 2

- [X] T018 [P] [US2] Write `backend/tests/unit/test_error_envelope.py` asserting the uniform envelope shape, as the fixture the contract check will diff against — S2, FR-043
- [X] T019 [P] [US2] Write `backend/tests/unit/test_no_credentials.py` scanning the tree for credential-shaped strings, as a local mirror of the CI secret scan — S2, FR-013, SC-012
- [X] T020 [P] [US2] Write `ops/ci-fixtures/` containing one deliberately-broken sample per check category — including a non-AWS AI SDK dependency and a leaked provider SDK import — used to prove each gate independently fails — S2, SC-003, SC-016

### Implementation for User Story 2

- [X] T021 [US2] Write `.github/workflows/ci.yml` triggered on pull requests targeting `pods/pod73` — never `main` or `master` — S2, FR-008, Principle VII
- [X] T022 [P] [US2] Add the ruff and mypy jobs to `ci.yml`, failing with file and line identified — S2, FR-009, FR-012
- [X] T023 [P] [US2] Add the pytest unit job to `ci.yml`, running with no AWS credentials available in the environment — S2, FR-009, FR-010
- [X] T024 [P] [US2] Add the Angular build and eslint accessibility job to `ci.yml` — S2, FR-009, FR-047b
- [X] T025 [P] [US2] Add the `terraform fmt -check` and `terraform validate` job to `ci.yml` — S2, FR-009
- [X] T026 [P] [US2] Add the secret-scanning job to `ci.yml` — S2, FR-013
- [X] T027 [US2] Add the `oasdiff` contract-compatibility job to `ci.yml`, generating the OpenAPI document from the FastAPI app and diffing against the trunk copy — S2, FR-048b, R-008
- [X] T028 [US2] Add the generated-client drift check: regenerate `frontend/src/app/api/` and fail on any diff — S2, FR-048, Principle V
- [X] T029 [US2] Add the ERD-accompaniment check: fail when a migration under `backend/migrations/versions/` changes without a change under `ops/erd/` — S4, FR-028
- [X] T030 [US2] Add the dependency-allowlist gate to `ci.yml`, failing any PR that introduces a non-AWS inference, model-hosting, or agent-framework SDK into a dependency manifest — S2, FR-013a, SC-016
- [X] T031 [US2] Add the connector-boundary gate to `ci.yml`, failing any PR where a cloud-provider SDK type is imported outside `backend/connectors/` — S2, FR-054, SC-016
- [X] T032 [US2] Extend `ci.yml` failure output to name the failing check plus file path and line number wherever the failure is attributable to a location — S2, FR-012
- [ ] T033 [US2] Configure branch protection on `pods/pod73` making all nine checks required, with no administrative bypass, and requiring a recorded AI review before merge — S2, FR-011, SC-003, Principle VII
- [ ] T034 [US2] Verify each fixture from T020 fails exactly its own check and no other, and that an additive-only contract change passes — S2, SC-003, FR-048a
- [ ] T035 [US2] Measure and record the suite's wall-clock time; tune job parallelism until it reports within 10 minutes — S2, FR-014, SC-004

**Checkpoint**: The trunk is defended. Every later phase merges through this gate.

---

## Phase 4: User Story 1 — Provision a working environment from scratch (Priority: P1)

**Goal**: A fresh cloud account reaches a working dev environment from versioned definitions alone.

**Independent Test**: Provision into an empty account from a clean clone, then tear down and repeat,
confirming the result is identical both times.

### Tests for User Story 1

- [X] T036 [P] [US1] Write `infra/tests/test_plan_idempotent.sh` asserting a second `terraform apply` reports no changes — S1, FR-003, SC-002
- [X] T037 [P] [US1] Write `backend/tests/unit/test_teardown_guard.py` asserting the teardown script refuses a `prod` target before invoking anything — S1, FR-005a

### Implementation for User Story 1

- [X] T038 [P] [US1] Write `infra/modules/database/` provisioning Aurora Serverless v2 PostgreSQL 16, Secrets Manager secret, and RDS Proxy — S4, FR-024, R-003
- [X] T039 [US1] Add `deletion_protection` and `skip_final_snapshot = false` to the prod database — S1, FR-005a, R-010. **Partial by necessity:** `lifecycle { prevent_destroy }` cannot be conditional on environment (Terraform requires a literal), and FR-002 mandates one shared module set for dev and prod. R-010's layers 1 and 3 hold; layer 2 is not implementable as specified. Spec correction needed — see T130
- [X] T040 [US1] Set `backup_retention_period = 7` on the prod cluster — S1, FR-005b, SC-014
- [X] T041 [P] [US1] Write `infra/modules/frontend/` — S3 origin bucket, CloudFront distribution, origin access control — S6, FR-047
- [X] T042 [P] [US1] Provision the raw-snapshot S3 bucket with versioning and no public access, leaving its lifecycle policy to spec 2 — S1, FR-007
- [X] T043 [US1] Write `ops/teardown.sh` reading the target workspace and exiting non-zero on `prod` before invoking anything — S1, FR-005a, R-010
- [X] T044 [US1] Add a shared Terraform local for log retention (30 days) and a module convention requiring every log group to consume it, so modules created in later phases inherit it rather than needing a retroactive sweep — S6, FR-046a, SC-014
- [X] T045 [US1] Complete `ops/runbooks/provisioning.md` end to end, including every prerequisite and supplied value — S1, FR-006
- [ ] T046 [US1] Time a full fresh-account provision against the 60-minute budget and record the per-step breakdown — S1, SC-001
- [ ] T047 [US1] Run the drift check: change a resource by hand, confirm `terraform plan` reports it, and confirm apply restores the defined state — S1, FR-004
- [ ] T048 [US1] Tear down the dev environment completely, re-provision from a clean clone, and assert the result is functionally identical — closing the dev half of SC-002 — S1, FR-005, SC-002
- [ ] T049 [US1] Assert a second `terraform apply` reports **no changes at all**, not merely no unintended ones — S1, FR-003

**Checkpoint**: dev exists and is reproducible. SC-001 and SC-002 are demonstrable.

---

## Phase 5: User Story 4 — Store governance data under a versioned schema (Priority: P1)

**Goal**: One agreed, migratable schema covering all ten governance entities, documented by an ERD.

**Independent Test**: Apply every revision in order to an empty database and confirm the shape
matches the committed ERD; apply the newest to a populated database and confirm zero rows lost.

### Tests for User Story 4

- [X] T050 [P] [US4] Write `backend/tests/integration/test_migrations.py` applying `0001`→head against Testcontainers PostgreSQL and asserting the resulting shape — S4, FR-025, SC-007
- [X] T051 [P] [US4] Extend that test to seed representative rows, apply head, and assert zero rows lost — S4, FR-026, SC-007
- [X] T052 [P] [US4] Write `backend/tests/integration/test_audit_append_only.py` asserting both UPDATE and DELETE against `audit_event` raise — S4, FR-029
- [X] T053 [P] [US4] Write `backend/tests/unit/test_tenant_scoping.py` asserting every tenant-scoped model rejects a query without a tenant filter — S4, FR-030

### Implementation for User Story 4

- [X] T054 [US4] Configure Alembic in `backend/migrations/env.py` with a revision docstring convention declaring reversibility — S4, FR-025, FR-027
- [X] T055 [P] [US4] Write revision `0001_extensions_and_enums` creating `pgcrypto` and all ENUM types — S4, FR-025
- [X] T056 [US4] Write revision `0002_tenant_and_user` creating `tenant` and `app_user`, seeding the single tenant; `app_user` carries no role column — S4, FR-024, FR-031a
- [X] T057 [US4] Write revision `0003_audit_event` creating the table, the BEFORE UPDATE OR DELETE trigger, and the grants that withhold UPDATE/DELETE from the application role; mark irreversible — S4, FR-029, FR-029a
- [X] T058 [US4] Write revision `0004_deployment` with the CHECK constraint requiring an approver for prod rows — S3, FR-017, FR-018
- [X] T059 [P] [US4] Write revisions `0005_accounts_and_resources`, `0006_rules_and_findings`, `0007_sda_and_ownership`, and `0008_scan` creating the downstream tables empty — S4, FR-024
- [X] T060 [P] [US4] Write the SQLAlchemy 2 declarative models in `backend/app/models/` for all ten entities, with no update or delete method exposed on `AuditEvent` — S4, FR-029
- [X] T061 [US4] Write `backend/app/core/db.py` with the engine using `NullPool`, session dependency injecting the caller's tenant, and Secrets Manager credential fetch cached in the execution context — S4, FR-030, R-003
- [X] T062 [US4] Write `backend/app/core/audit.py` exposing an insert-only `write_audit_event` helper — S4, FR-040
- [X] T063 [US4] Create the ERD source and rendered diagram in `ops/erd/` matching the schema at head — S4, FR-028

**Checkpoint**: The schema all six specs build against is settled and proven migratable.

---

## Phase 6: User Story 6 — Reach a healthy, consistently-behaved service (Priority: P1)

**Goal**: One service with a health endpoint, a uniform error envelope, correlation-traceable
structured logs, and a published OpenAPI contract.

**Independent Test**: Call health, force each failure kind, and confirm every failure returns the
identical envelope and appears in the logs under a traceable identifier.

### Tests for User Story 6

- [X] T064 [P] [US6] Write `backend/tests/unit/test_health.py` asserting healthy shape and asserting 503 with `status: unhealthy` when the database dependency is unreachable — S6, FR-041, FR-042
- [X] T065 [P] [US6] Write `backend/tests/unit/test_error_shape.py` asserting all four failure kinds — 422, 401, 403, 404 — return the identical envelope with a correlation id — S6, FR-043, SC-009
- [X] T066 [P] [US6] Write `backend/tests/unit/test_correlation_id.py` asserting a malformed inbound identifier is discarded and regenerated rather than logged — S6, FR-044, Edge Cases
- [X] T067 [P] [US6] Write `backend/tests/unit/test_log_redaction.py` asserting no credential, token, or raw tag value reaches a log record — S6, FR-046

### Implementation for User Story 6

- [X] T068 [US6] Write `backend/app/api/errors.py` implementing the `ErrorEnvelope` from contracts/openapi.yaml as the single exception-handler path for every failure kind — S6, FR-043
- [X] T069 [US6] Write `backend/app/core/logging.py` with the Powertools logger and a redaction denylist formatter — S6, FR-045, FR-046, R-012
- [X] T070 [US6] Write `backend/app/api/middleware.py` assigning a correlation id per request, validating any inbound value against a strict UUID pattern, and echoing it in every response — S6, FR-044, R-012
- [X] T071 [US6] Write `backend/app/api/main.py` — the FastAPI app, Mangum adapter, router registration — and `backend/handlers/api_handler.py` — S6, FR-047
- [X] T072 [US6] Write `backend/app/api/routers/health.py` reporting service and database health, returning 503 on an unreachable dependency — S6, FR-041, FR-042
- [X] T073 [US6] Write `infra/modules/api/` — API Gateway HTTP API, the API Lambda on arm64, execution role, and log group, consuming the shared log-retention local — S6, FR-047, FR-046a
- [X] T074 [US6] Write `backend/handlers/migrate_handler.py`, the migration Lambda, and add it to `infra/modules/api/` in the cluster's private subnets — relocated here from Phase 5 because it depends on the module above — S3, FR-016, R-002
- [X] T075 [US6] Publish the generated OpenAPI document as a CI artifact and commit the trunk baseline that `oasdiff` compares against — S6, FR-048, R-008
- [X] T076 [US6] Write `ops/runbooks/contract-changes.md` documenting the additive-then-remove procedure for a genuinely necessary breaking change, and the rule that two specs adding the same contract path resolve by second-to-merge failing — S6, FR-048c, FR-057
- [X] T077 [US6] Generate the Angular client into `frontend/src/app/api/` and add a header comment marking it generated and never hand-edited — S6, FR-048, Principle V
- [X] T078 [US6] Build the Angular shell in `frontend/src/app/shared/` — layout, navigation, error display — meeting the FR-047a baseline of semantic markup, keyboard operability, and visible focus — S6, FR-047a
- [X] T079 [US6] Write `frontend/e2e/shell.spec.ts` with Playwright plus axe-core assertions on the shell — S6, FR-047b, SC-015
- [ ] T080 [US6] Confirm any correlation id from a response locates the complete request trace in the logs within 2 minutes — S6, SC-010

**Checkpoint**: The API contract specs 2–6 extend is live and enforced.

---

## Phase 7: User Story 5 — Sign in and act only within your role (Priority: P1)

**Goal**: Federated sign-in with exactly one role derived from directory group membership, enforced
on every request.

**Independent Test**: Run the full role matrix — admin, operator, viewer, unauthenticated, no
mapped group, two mapped groups — and confirm every cell gives the expected allow or refuse.

### Tests for User Story 5

- [X] T081 [P] [US5] Write `backend/tests/integration/test_role_matrix.py` covering all six caller kinds against the endpoints this spec ships, and assert the delegated capabilities of FR-033 (manage accounts/rules/SDAs, run scans, work findings) are absent from this spec's API surface — S5, FR-033, FR-033a, FR-034, SC-008
- [X] T082 [P] [US5] Write `backend/tests/unit/test_no_registration_path.py` asserting the generated OpenAPI document exposes no registration, password, or role-assignment operation, and that the Cognito pool has self-service sign-up disabled — S5, FR-031, FR-031a
- [X] T083 [P] [US5] Write `backend/tests/unit/test_role_cardinality.py` asserting zero groups and two groups are both refused rather than resolved — S5, FR-032a
- [X] T084 [P] [US5] Write `backend/tests/unit/test_no_group_claim.py` asserting a token carrying no group claim at all is refused, never treated as an empty list matching a default — S5, FR-032a, Edge Cases
- [X] T085 [P] [US5] Write `backend/tests/unit/test_error_no_existence_leak.py` asserting a 404 to an unentitled caller is indistinguishable from a 404 for a genuinely missing record — S5, FR-035

### Implementation for User Story 5

- [X] T086 [US5] Write `infra/modules/identity/` — Cognito user pool, app client, and the three groups created from a `map` variable in `terraform.tfvars` — S5, FR-032, FR-039a
- [X] T087 [US5] Set access and ID token lifetime to 1 hour and refresh token to 8 hours on the app client — S5, FR-036, FR-038, R-005
- [X] T088 [US5] Write `backend/handlers/pre_token_handler.py`, the Cognito pre-token-generation Lambda, stamping a single role claim only when exactly one mapped group is present — S5, FR-032, R-004
- [X] T089 [US5] Attach the JWT authorizer to the HTTP API in `infra/modules/api/`, leaving `/health` public — S5, FR-034, FR-041
- [X] T090 [US5] Write `backend/app/core/security.py` with a `require_role` dependency that independently re-derives the role from the raw group claim and refuses anything other than exactly one — S5, FR-031a, FR-032a, R-004
- [X] T091 [US5] Write `backend/app/api/routers/me.py` implementing `GET /me` per contracts/openapi.yaml, with just-in-time `app_user` creation on first authenticated request — S5, FR-034
- [X] T092 [US5] Wire `write_audit_event` into every administrative and state-changing path — S5, FR-040
- [X] T093 [US5] Implement the Angular auth guard, token handling, and sign-out in `frontend/src/app/core/` — S5, FR-037
- [X] T094 [US5] Add the first-administrator procedure to `ops/runbooks/provisioning.md`, stating that no in-platform bootstrap path exists — S5, FR-039, R-006
- [ ] T095 [US5] Confirm SC-013: move a user between directory groups and verify the change takes effect within 1 hour with no action inside the platform, and that no endpoint or screen can assign a role — S5, SC-013
- [ ] T096 [US5] Confirm FR-038a: remove a user from all mapped groups and separately disable the user in the directory, and verify access ends within the same 1-hour bound and any held session stops being accepted — S5, FR-038a
- [X] T097 [US5] Implement and test the read-only, tenant-scoped API principal that spec 6's agent action groups will authenticate as: it MUST hold no cloud credential, MUST have no path to the data store except the API, and MUST be refused on every state-changing operation — S5, FR-056, SC-017

**Checkpoint**: Access control is complete and the role matrix passes end to end.

---

## Phase 8: User Story 3 — Ship to dev automatically, to prod deliberately (Priority: P1)

**Goal**: A trunk merge reaches dev unattended; prod requires a recorded human approval.

**Independent Test**: Merge a visible change and confirm it appears in dev with no human action;
then attempt a prod release and confirm it halts until approved.

### Tests for User Story 3

- [X] T098 [P] [US3] Write `backend/tests/unit/test_deployment_record.py` asserting a prod `deployment` row cannot be written without `approved_by` and `approved_at` — S3, FR-017, FR-018
- [X] T099 [P] [US3] Write `backend/tests/integration/test_migration_lambda.py` asserting the migration Lambda returns non-zero on a failing revision and leaves the schema unchanged — S3, FR-016, FR-021

### Implementation for User Story 3

- [X] T100 [US3] Write `.github/workflows/deploy-dev.yml` triggered on merge to `pods/pod73`, authenticating via OIDC with no stored keys — S3, FR-015, FR-022
- [X] T101 [US3] Add the migration-Lambda invocation to `deploy-dev.yml`, failing the deployment on a non-zero result before the API Lambda alias shifts — S3, FR-016, R-002
- [X] T102 [US3] Add concurrency grouping per environment to both deploy workflows so two deployments cannot apply to one environment at once — S3, FR-020, Edge Cases
- [X] T103 [US3] Write the deployment-record step writing git sha, environment, actor, migration revision, and status to the `deployment` table — S3, FR-023
- [X] T104 [US3] Write `.github/workflows/deploy-prod.yml` behind a GitHub Environment approval gate — S3, FR-017, FR-019
- [X] T105 [US3] Record approver identity and time, plus the `self_approved` flag when the approver is the author, as an audit event — S3, FR-018, Assumptions
- [X] T106 [US3] Implement failure handling meeting all three FR-021 conditions — previous version still serving, schema at a revision it supports, deployment status recorded `failed` — and surface the failure to the maintainer — S3, FR-021
- [ ] T107 [US3] Provision the prod environment from the same module set and confirm only documented per-environment differences — S1, FR-002
- [ ] T108 [US3] Confirm SC-005: time a trunk merge to live-in-dev against the 15-minute budget with zero human actions — S3, SC-005
- [ ] T109 [US3] Confirm SC-006: verify a paused prod release leaves prod byte-for-byte unchanged, and that no release proceeds without a recorded approver — S3, SC-006
- [ ] T110 [US3] Confirm SC-002's prod half: run `ops/teardown.sh prod` and verify it refuses having changed nothing — S1, FR-005a, SC-002
- [ ] T111 [US3] Confirm SC-014: inspect log group retention, cluster backup retention, and the absence of any expiry mechanism on `audit_event` — S4, FR-029a, SC-014
- [X] T112 [US3] Confirm SC-012: run a repo-wide credential scan and verify no workflow authenticates with a stored key — S2, SC-012
- [ ] T113 [US3] Walk quickstart.md V1–V8 end to end from the runbook alone, without relying on memory of having written it — S1, FR-006, SC-001

**Checkpoint**: 🏁 **P1 COMPLETE.** SC-001 through SC-010 and SC-012 through SC-015 all pass. The
demo path is walkable. Everything below is optional.

---

## Phase 9: User Story 7 — Find out something is wrong without being told (Priority: **P2**)

**Goal**: One dashboard plus email alerts on error spikes, scan failures, and dead-lettered work.

**Independent Test**: Force each alarm condition in turn and confirm the dashboard reflects it and
an email is delivered.

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII and spec §US7, nothing here may block or destabilise a
P1 path. If Phase 9 is dropped entirely, Phases 1–8 still satisfy every P1 success criterion. Start
this only once T104 is green.

### Tests for User Story 7

- [X] T114 [P] [US7] **[P2]** Write `backend/tests/unit/test_alarm_thresholds.py` asserting each alarm's configured threshold and evaluation window — S7, FR-050
- [X] T115 [P] [US7] **[P2]** Write `infra/tests/test_alarm_wiring.sh` asserting every alarm has an SNS action attached — S7, FR-051

### Implementation for User Story 7

- [X] T116 [US7] **[P2]** Decide and document the concrete alarm threshold values that FR-050 leaves as "agreed threshold", recording them in `infra/envs/*/terraform.tfvars` — S7, FR-050
- [X] T117 [US7] **[P2]** Write `infra/modules/observability/` with the CloudWatch dashboard showing API error rate, scan outcomes, and DLQ depth — S7, FR-049
- [X] T118 [P] [US7] **[P2]** Add the API error-rate alarm — S7, FR-050
- [X] T119 [P] [US7] **[P2]** Add the scan-failure alarm — S7, FR-050
- [X] T120 [P] [US7] **[P2]** Add the dead-letter-queue depth alarm — S7, FR-050
- [X] T121 [US7] **[P2]** Provision the SNS topic with the alert email subscription and confirm alarms return to healthy automatically when the condition clears — S7, FR-051, FR-052
- [X] T122 [US7] **[P2]** Add a heartbeat alarm on the alerting path itself so its failure is visible rather than silent, then confirm SC-011 by forcing each condition — S7, FR-053, SC-011

**Checkpoint**: Operational visibility. Optional for the demo.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T123 [P] Record the four research.md **VERIFY** outcomes — LocalStack tier coverage, RDS Data API viability, Cognito claim behaviour, oasdiff classification — in `AI_WORKFLOW_JOURNAL.md` — Principle I
- [ ] T124 [P] Review `checklists/scope-and-contracts.md` as its reviewer and mark each of the 48 items, now that the analyze remediation has closed CHK011, CHK012, CHK023/024, CHK026, CHK028, CHK030, CHK032, and CHK043 — Principle I
- [X] T125 [P] Verify FR-054 to FR-057 hold in the built system: no provider SDK leak, delegation recorded, agent path read-only, breaking-change runbook present — FR-054, FR-055, FR-056, FR-057, SC-016, SC-017
- [X] T126 [P] Write `backend/README.md`, `frontend/README.md`, and `infra/README.md` describing each area's ownership boundary — Principle I
- [ ] T127 [P] Confirm every merged PR carries a recorded AI review alongside its green CI check, and that no PR merged without one — Principle VII
- [ ] T128 Re-run `/speckit-analyze` after the last P1 task and before spec 002 begins, resolving any new finding — Governance
- [ ] T129 Decide the dev cost profile (RDS Proxy on/off, min_acu 0 vs 0.5) and record it in `infra/envs/dev/terraform.tfvars` with the reasoning — S1, R-003
- [X] T130 Correct R-010 in research.md and the FR-005a note: `prevent_destroy` cannot be made conditional in a module shared by dev and prod, so prod protection is two layers, not three. Principle I — fix the spec, do not work around it — Principle I, FR-005a

---

## Dependencies

```text
Phase 1 (Setup) ──> Phase 2 (Foundational) ──> Phase 3 (US2: CI gate)
                                                      │
                              ┌───────────────────────┴──────────┐
                              ▼                                  │
                    Phase 4 (US1: environments)                  │
                              │                                  │
                              ▼                                  │
                    Phase 5 (US4: data + migrations)             │
                              │                                  │
                              ▼                                  │
                    Phase 6 (US6: API skeleton) ◄────────────────┘
                              │
                              ▼
                    Phase 7 (US5: identity)
                              │
                              ▼
                    Phase 8 (US3: CD + prod gate)  ──> 🏁 P1 COMPLETE
                              │
                              ▼
                    Phase 9 (US7: observability)  [P2 — droppable]
                              │
                              ▼
                    Phase 10 (Polish)
```

**Honest note on story independence**: the template's usual assumption — that each user story is a
vertical slice deliverable on its own — does not hold for a foundation spec. These stories are
layers, not slices: US3 cannot deploy before US6 exists to be deployed, and US6 cannot protect an
endpoint before US5 exists. The phases are therefore ordered by genuine dependency rather than
being claimed as independent. Each phase still has its own checkpoint and its own test criteria.

**Cross-phase dependencies worth watching**:

- T027/T028 (contract checks) cannot pass on real content until T071 exists. Land them
  conditionally skipped, then enable at T075.
- T058 (`deployment` table) is written in Phase 5 but only exercised in Phase 8.
- T074 (migration Lambda) was relocated from Phase 5 to Phase 6 during analyze remediation,
  because it depends on T073's module. Do not move it back.
- T044 establishes the shared log-retention local so every module built in Phases 6, 7, and 9
  inherits it — it is a convention, not a one-time sweep. Confirm at T111.
- T031's connector-boundary gate has nothing to catch until spec 2 writes connector code; it must
  still be green from the day it lands.

## Parallel Opportunities

| Phase | Parallel set | Why safe |
|---|---|---|
| 1 | T002–T010 | Distinct files, no shared state |
| 2 | T014–T017 | Separate modules and packages |
| 3 | T018–T020 · T022–T026 | Separate test files; independent CI jobs |
| 4 | T036, T037 · T038, T041, T042 | Separate test files; separate Terraform modules |
| 5 | T050–T053 · T055, T059, T060 | Separate test files; separate revisions and model files |
| 6 | T064–T067 | Separate test files |
| 7 | T081–T085 | Separate test files |
| 8 | T098, T099 | Separate test files |
| 9 | T114, T115 · T118–T120 | Separate test files; separate alarm resources |
| 10 | T123–T127 | Independent documents |

**Solo sequencing note**: with one maintainer these sets are not worked simultaneously — `[P]`
means "no dependency, so order is free", which matters for batching several small changes into one
same-day PR rather than for concurrency. Phase 1's nine parallel tasks are one morning's work as a
single PR; from Phase 4 onward the critical path is genuinely linear.

## Implementation Strategy

**MVP scope**: Phases 1–3 (T001–T035). That delivers a scaffolded monorepo behind a working
nine-category merge gate — enough to prove SC-003, SC-004, and SC-016, and to make every later
change safe to self-merge. It is the smallest increment with standalone value, and with no
second-human review it is also the highest-leverage.

**Incremental delivery**: each phase ends at a checkpoint that is demonstrable on its own. Phases
4–8 each add one layer of the demo path; Phase 8's checkpoint is the full P1 demo.

**Principle VIII discipline**: T114–T122 are the only P2 tasks and are the last implementation
work scheduled. If the two weeks run short, Phase 9 is what gets cut — not any part of Phases 1–8,
and not the Phase 10 governance tasks T124, T125, and T128.

---

## Analyze remediation (2026-08-22)

Regenerated after `/speckit-analyze`. All fifteen findings resolved:

| Finding | Resolution |
|---|---|
| D1 CRITICAL — journal outcomes unfilled | `AI_WORKFLOW_JOURNAL.md` §0–§3 filled |
| D2 CRITICAL — connector interface had no requirement | FR-054 added; T008 rescoped to a reserved package with a boundary constraint, protocol delegated to spec 2 (S11) |
| F1 HIGH — FR-001 forbade the bootstrap T013 performs | FR-001 amended, FR-001a added for the single permitted manual step |
| E1 HIGH — FR-031 uncovered | T082 added |
| E2 HIGH — FR-038a uncovered | T096 added |
| E3 HIGH — FR-005 uncovered | T048 added; T049 added for the tightened FR-003 |
| E4 MEDIUM — FR-033 uncovered | FR-033a added defining this spec's own role matrix; covered by T081 |
| E5 MEDIUM — FR-048c uncovered | FR-057 added; T076 writes the procedure |
| F2 MEDIUM — T058/T041 ordering | Migration Lambda relocated to T074; log retention became a shared convention at T044 |
| F3 MEDIUM — analyze task placed last | Now T128, rescoped to a re-run before spec 002 |
| D3 MEDIUM — Principle II unenforced | FR-013a added; T030 adds the CI dependency-allowlist gate |
| B1 MEDIUM — "serviceable state" untestable | FR-021 now enumerates three conditions |
| B2 MEDIUM — "precisely enough" untestable | FR-012 now requires check name, file path, line number; T032 implements |
| B3 LOW — "no unintended changes" | FR-003 now requires "no changes at all" |
| F4 LOW — User/app_user/CurrentUser drift | Naming note added to data-model.md |

Also applied: constitution **v2.0.0** (solo delivery with AI collaboration; Claude Code named as
the permitted development-time engine) propagated through spec, plan, and tasks. FR-055 and FR-056
added for the remaining cross-spec gaps flagged by CHK028/030/032.
