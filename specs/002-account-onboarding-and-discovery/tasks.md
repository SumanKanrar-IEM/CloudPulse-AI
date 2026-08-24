---

description: "Task list for 002-account-onboarding-and-discovery"
---

# Tasks: Account Onboarding and Discovery

**Input**: Design documents from `/specs/002-account-onboarding-and-discovery/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/openapi.yaml](./contracts/openapi.yaml)

**Tests**: Included. Constitution Principle VI makes lint, type checks, unit tests, and — for
cloud-touching code — integration tests with mocked AWS a merge requirement, so test tasks are not
optional here (same precedent as spec 1's tasks.md).

**Constitution**: v2.0.1 — solo delivery with AI collaboration. Every PR merges behind green CI
plus a recorded AI review; there is no second-human gate. Every task cites its `T\d{3}` ID in the
PR body (`pr-task-reference`, enforced by CI). If implementation surfaces a fix this list didn't
anticipate, a new task is added here *before* opening that fix's PR — playbook §0.5.5.

## Format: `[ID] [P?] [Story] Description — S#, FR-###`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1–US4 from spec.md. Setup, Foundational, and Polish tasks carry no story label
- **S#**: Backlog story ID · **FR-###/SC-###**: the spec requirement the task satisfies
- Every task is sized for one short-lived `pods/pod73-XXX` branch and a same-day PR (Principle VII)

## Path Conventions

Monorepo per plan.md: `infra/modules/scan/`, `backend/app/scan/`, `backend/connectors/`,
`frontend/src/app/features/accounts/` — all filling directories spec 1 reserved empty.

## Tier Summary

**P1 (demo-critical, frozen)**: Phases 1–7, T001–T054. Completing these satisfies SC-001 through
SC-004 and SC-006 through SC-009 at the mocked-test level (CI, 370 backend tests). SC-005
(coverage-as-data takes effect with no code change) is P1 foundation — verified alongside the rest.
**Live proof against a real AWS account is still open**: T053 deployed to dev and surfaced a real
VPC-networking gap (no NAT/Interface endpoints for a Lambda's control-plane API calls) before the
user chose to stop rather than spend on a fix; T054 tore the environment back down cleanly. See
T053/T054's own entries for the full account.
**P2 (stretch)**: Phase 8 only, T055–T058. Every P2 task is marked **[P2]** in its description.
Dropping Phase 8 entirely leaves the P1 demo path intact (FR-020's extended enrichment types and
FR-033's scan history are additive, nothing else depends on them) — that is the Principle VIII
check.

---

## Phase 1: Setup

**Purpose**: Fill the directories spec 1 reserved empty. No new dependency — boto3 (already a
spec 1 dependency) covers Cloud Control API, Tagging API, and Step Functions; no new Angular
package either.

- [X] T001 [P] Create `backend/app/scan/__init__.py` and empty `orchestrator.py`, `discovery.py`, `enrichment.py`, `coverage.py` — S11, FR-014
- [X] T002 [P] Create `backend/connectors/aws.py` as an empty stub (implemented in Phase 5) — S11, FR-014
- [X] T003 [P] Create `frontend/src/app/features/accounts/` with empty `accounts-list.component.ts`, `account-form.component.ts`, `accounts.service.ts` — S10, FR-010
- [X] T004 [P] Create `infra/modules/scan/` with a placeholder `main.tf`, `variables.tf`, `outputs.tf` — S15, FR-023

**Checkpoint**: Directory structure exists; no user story work is blocked waiting for scaffolding.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The connector protocol, the schema extension, and coverage-as-data — every user
story below depends on at least one of these.

**⚠️ CRITICAL**: T005's migration and T006's protocol are load-bearing for every phase after this
one. Land them together in one PR.

- [X] T005 Write migration `0009_resource_lifecycle_and_detail` adding `state`, `deleted_at`, `detail` to `resource` in `backend/migrations/versions/` — data-model.md, FR-013, FR-030
- [X] T006 [P] Write `backend/connectors/base.py` — the `Connector` protocol and `NormalizedResource` shape (data-model.md's FR-014 section) — FR-014, Principle V
- [X] T007 [P] Write `backend/app/scan/coverage.py` loading a coverage-definition file at scan-orchestration time (research.md R-203) — FR-021, FR-022
- [X] T008 [P] Write `backend/app/scan/coverage_definitions.json` seeded with the six P1 governance-critical types (FR-019) mapped to their enrichment function names — FR-019, FR-021
- [X] T009 Extend `backend/app/models/core.py` for `resource`'s three new columns; confirm the existing `cloud_account`/`scan` SQLAlchemy models already expose `disabled`/`partial` (data-model.md — no model change needed there, just confirm) — data-model.md
- [X] T010 [P] Write `backend/tests/unit/test_connector_protocol.py` asserting the protocol shape, and extend `ops/scripts/check_connector_boundary.py`'s existing scope check (no change expected — confirms `connectors/aws.py` doesn't yet violate the boundary with an empty stub) — FR-014, connector-boundary CI

**Checkpoint**: Schema, connector interface, and coverage-as-data are settled. User story work can
begin.

---

## Phase 3: User Story 1 — Connect an account without ever handling a credential (Priority: P1)

**Goal**: Roles-only registration, verified before acceptance, admin-gated.

**Independent Test**: Register the platform's own account (same-account mode) and confirm
verified; separately attempt registration with an access key or an untrusted role and confirm
both refused before storage.

### Tests for User Story 1

- [X] T011 [P] [US1] Write `backend/tests/unit/test_account_registration.py` — role-only input, access-key rejection, connection-mode validation — S8, S9, FR-001, FR-006
- [X] T012 [P] [US1] Write `backend/tests/unit/test_external_id_generation.py` — platform-generated, unique per account, sufficient entropy, admin-supplied value rejected — S8, FR-003a
- [X] T013 [P] [US1] Write `backend/tests/integration/test_cross_account_verification.py` — moto-mocked STS AssumeRole, ExternalId condition required and enforced, dry-run read check — S8, S9, FR-003, FR-007, SC-004. Note: moto's STS mock does not enforce trust-policy/ExternalId validity (verified empirically — it returns usable credentials for a role that was never deployed), so the ExternalId-mismatch-is-refused assertion is proven in `test_external_id_generation.py` by mocking the AssumeRole boundary directly instead (R-209-style fallback), not through moto here.

### Implementation for User Story 1

- [X] T014 [US1] Write `backend/app/scan/verification.py` — dry-run role assumption plus a real read-only action, distinguishing "role not found" from "assumed but no usable access" — S9, FR-005, FR-007
- [X] T015 [US1] Write `POST /accounts` in `backend/app/api/routers/accounts.py`, gated `require_role(Role.ADMIN)`, accepting both connection modes — S8, S9, FR-002, FR-006, FR-011a
- [X] T016 [US1] Wire platform-generated ExternalId creation and its Secrets Manager storage into registration, writing only the ARN reference to `cloud_account.external_id_ref` — S8, FR-003a, Principle III
- [X] T016a [US1] Add `POST /accounts/external-id` (admin-gated), returning a fresh platform-generated ExternalId ahead of registration; extend `contracts/openapi.yaml` additively. **Closes a genuine contract gap found during implementation**: FR-003a requires the platform to generate the ExternalId, but for cross-account mode the admin needs that value *before* deploying the CloudFormation template and getting back a role ARN to pass to `POST /accounts` — the original contract had `POST /accounts` as the only registration-adjacent endpoint, with no way to hand the admin a value ahead of time. The endpoint is deliberately stateless (no persistence) — the round-tripped value is proven genuine by `POST /accounts`'s own AssumeRole verification, which only succeeds if the admin actually deployed a trust policy embedding that exact value; that structural check is what keeps this consistent with FR-003a's "MUST NOT accept an admin-supplied external-id" (the admin relays the platform's value, never chooses one) — S8, FR-003a, FR-004
- [X] T017 [US1] Write the ready-to-deploy cross-account template (CloudFormation) in `infra/modules/scan/cross_account_template.yaml`, scoped read-only, exposed via a new API response field — S8, FR-004, FR-005. Caught by local `cfn-lint` before this ever reached AWS: Cloud Control API's IAM actions are under the `cloudformation:` prefix, not `cloudcontrol:` — fixed.
- [X] T018 [US1] Wire an `audit_event` write on every registration attempt (success and refusal), reusing spec 1's `write_audit_event` helper — S8, FR-040 (spec 1). Found and fixed a real bug while testing this: writing the audit event for a *refused* registration inside the same `tenant_session` block as the `raise` caused the context manager's own rollback to silently undo the audit write — split into separate transactions (audit commits, then raise).
- [X] T019 [US1] Confirm FR-009: attempt registering the same underlying AWS account twice (same-account then cross-account, and vice versa) and confirm the second is refused with a message identifying the existing record — S9, FR-009

**Checkpoint**: An account can be connected, roles-only, verified before acceptance. SC-004 is
demonstrable.

---

## Phase 4: User Story 2 — See and manage every connected account in one place (Priority: P1)

**Goal**: The accounts admin surface — visible to all three roles, state-changing actions
admin-gated.

**Independent Test**: With one account registered, load the accounts view and confirm every
required field is visible; confirm an operator or viewer can view but not register/deactivate.

### Tests for User Story 2

- [X] T020 [P] [US2] Write `backend/tests/integration/test_accounts_view_role_matrix.py` — view accessible to admin/operator/viewer; register/deactivate/reactivate refused for operator and viewer — S10, FR-010a, FR-011a
- [X] T021 [P] [US2] Write `backend/tests/unit/test_account_deactivate_reactivate.py` — status transitions (`verified`↔`disabled`), in-progress scan allowed to finish, duplicate-registration refusal still applies to a deactivated account — S9, FR-009a, FR-009b, FR-009c, SC-008

### Implementation for User Story 2

- [ ] T022 [US2] Write `GET /accounts` in `accounts.py`, gated `require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER)`, including the verification-failure reason in the response — S10, FR-010, FR-010a, FR-012. **Partially done in T015's PR**: the route exists and lists every field except `failureReason` -- deferred here since no path before Phase 6 ever produces a `FAILED` account (registration always verifies synchronously before accepting, per FR-007), so there is nothing real to display yet; add the field when Phase 6's scan-failure handling gives `FAILED` a genuine cause to report, rather than speculating now.
- [X] T023 [US2] Write `PATCH /accounts/{id}` (region-list edit), admin-gated — S9, FR-008, FR-011a. Landed in T015's PR alongside registration -- one router file, natural to build together.
- [X] T024 [US2] Write `POST /accounts/{id}/deactivate`, admin-gated, refusing a scan-in-progress abort (FR-009b) — S9, FR-009a, FR-011a. Landed in T015's PR.
- [X] T025 [US2] Write `POST /accounts/{id}/reactivate`, admin-gated, no re-verification (Edge Cases) — S9, FR-009c, FR-011a. Landed in T015's PR.
- [X] T026 [US2] Build `frontend/src/app/features/accounts/accounts-list.component.ts` — mode, region list, status, last-scan summary, failure reason, visible to all roles — S10, FR-010, FR-012
- [X] T027 [US2] Build `frontend/src/app/features/accounts/account-form.component.ts` — register/deactivate/reactivate actions, disabled (not merely hidden) for non-admin roles per spec 1's role-guard precedent — S9, FR-011, FR-011a
- [X] T028 [US2] Regenerate the Angular API client for the new endpoints; confirm `client-drift` CI passes — Principle V. Pulled forward into T015's PR: `client-drift` diffs the checked-in client against a fresh regeneration on every PR, so it had to happen the moment the contract grew new endpoints, not wait for Phase 4.

**Checkpoint**: The full account lifecycle (register → view → deactivate → reactivate) is usable
end to end through the UI *once two pre-existing, cross-cutting gaps below are closed* -- neither
is spec 002's to fix unilaterally, both were found while wiring T026/T027 and are flagged here
rather than silently patched:

1. **No sign-in flow exists anywhere in the frontend.** `auth.guard.ts` redirects an unauthenticated
   caller to `/sign-in`, but no `/sign-in` route, component, or Cognito Hosted-UI OAuth
   redirect/callback handling exists -- `auth.service.ts` has `signOut()` but nothing that signs a
   user *in* or captures a token. This blocks every route behind `authGuard`, not just `/accounts`;
   it is a spec-1-scale gap (frontend auth was scaffolded, never finished), not something to
   improvise as a side effect of this spec's accounts screen.
2. **The deploy pipeline builds the frontend before the API URL is known.** `deploy-dev.yml`/
   `deploy-prod.yml` run `npm run build` *before* `terraform apply`, so the API Gateway URL
   (`terraform output api_endpoint`) does not exist yet at build time -- a standard Angular
   build-time environment file cannot be correctly populated under that ordering. T026/T027 land a
   runtime-config seam for this (`frontend/src/app/core/api-config.ts`, reading
   `window.__CLOUDPULSE_CONFIG__.apiBaseUrl`, defaulting to `''`/same-origin) so the frontend code
   is ready for a fix, but actually populating that config (reordering the pipeline, or adding a
   post-apply step that injects it into the deployed `index.html`) is a CI/CD change outside this
   session's scope to decide unilaterally.

Both gaps mean the accounts screen builds, lints, and passes its backend contract correctly, but is
not yet reachable by a real signed-in user in a real deployment. Flagged to the user; not a spec 002
functional requirement (FR-034/FR-037's sign-in mechanics are spec 1's, not this spec's, scope).

---

## Phase 5: User Story 3 — Discover everything in an account, not a curated subset (Priority: P1)

**Goal**: Whole-account discovery via combined generic surfaces, plus targeted enrichment for the
six P1 governance-critical types.

**Independent Test**: Against a test account with an unanticipated resource type and a
deliberately untagged resource, run discovery and confirm both appear with full identity fields.

### Tests for User Story 3

- [X] T029 [P] [US3] Write `backend/tests/unit/test_discovery_tagging_api.py` — moto-mocked Resource Groups Tagging API sweep, untagged resources included — S12, FR-016, FR-017
- [X] T030 [P] [US3] Write `backend/tests/unit/test_discovery_cloud_control.py` — moto-mocked Cloud Control `ListResources`; resolve research.md R-209's VERIFY marker here (moto's fidelity) before writing further discovery tests, falling back to a hand-built fixture if moto's coverage is thin — S12, FR-016
- [X] T031 [P] [US3] Write `backend/tests/unit/test_normalized_resource_shape.py` — every discovered resource conforms to the FR-013 shape regardless of source surface — S11, FR-013
- [X] T032 [P] [US3] Write `backend/tests/unit/test_enrichment_p1_types.py` — all six P1 types (EC2, EBS, EIP, S3, RDS, Lambda) populate `resource.detail` with state/size/attachment/runtime fields — S13, S14, FR-019

### Implementation for User Story 3

- [X] T033 [US3] Write `backend/app/scan/discovery.py` — combined Tagging API + Cloud Control sweep, deduplicated (research.md R-201) — S12, FR-016, FR-017. **The actual sweep calls live in `connectors/aws.py`, not here**: `check_connector_boundary.py` (FR-054) only allows boto3/botocore imports inside `connectors/`, so `discovery.py` orchestrates (builds the `ConnectorAccount`, calls the injected `Connector`) while `AwsConnector.discover()` does the real Tagging API + Cloud Control work and the ARN-based dedup between them.
- [X] T034 [US3] Implement `discover()` on `backend/connectors/aws.py` against the Phase 2 protocol, using each resource's ARN as its stable unique identifier — S11, FR-014, FR-015
- [X] T035 [US3] Write `backend/app/scan/enrichment.py` — six targeted boto3 describe calls (research.md R-202) — S13, S14, FR-019. Same boundary split as T033: the six describe calls and the registry mapping function-name-strings to callables both live in `connectors/aws.py`; `enrichment.py` calls `connector.enrich(resource)` per resource.
- [X] T036 [US3] Wire enrichment dispatch through `coverage.py`'s data-driven registry rather than an if/elif chain (coverage-as-data foundation) — FR-021. Dispatch happens inside `AwsConnector.enrich()`, which is necessarily stateful (caches the session `discover()` built) since the `Connector` protocol's `enrich(resource)` signature carries no account/session parameter of its own.
- [X] T037 [US3] Implement global-surface once-per-account deduplication (FR-018) in `discovery.py` — S12, FR-018. Two mechanisms, not one: within-call ARN dedup (Tagging vs. Cloud Control overlap) happens in `AwsConnector.discover()`; cross-*region* dedup for genuinely global resources (e.g. S3 buckets, found again from every region scanned) is NOT attempted here — `discover()` has no visibility into other regions' results, since each region is a separate unit of work (R-211). It is instead a natural consequence of `resource`'s `UNIQUE(tenant_id, arn)` constraint at persistence time (Phase 6): a second sighting from another region updates `last_seen_at` rather than inserting a duplicate row.

**R-209's VERIFY resolved empirically** (moto[all] 5.2.3, tested directly against real AWS API shapes, not assumed): Resource Groups Tagging API IS mocked by moto for tagged resources, but moto's mock **only ever returns tagged resources** — an untagged resource never appears in its response at all, the opposite of what FR-017 needs proven. Cloud Control API (`cloudcontrol` boto3 client) is **not implemented by moto at all** — every call 404s "Not yet implemented," regardless of `TypeName`. Both gaps are handled per R-209's own documented fallback: hand-built fixtures (mocking the boto3 client/paginator directly) test the parsing and dedup code actually written, while moto's real (correct) behavior for the six P1 enrichment describe calls and for tagged-resource discovery is used wherever it genuinely applies.

**Checkpoint**: A scan of a real account returns a complete, normalized, partially-enriched
inventory. SC-002's discovery-rate claim is demonstrable (measured for real in T053).

---

## Phase 6: User Story 4 — Keep inventory current without anyone asking (Priority: P1)

**Goal**: Scheduled and on-demand scanning, fan-out orchestration, and lifecycle diffing that
never over- or under-deletes.

**Independent Test**: Delete a resource directly in AWS, trigger a scan, confirm it's marked
deleted with no manual step; force a partial failure and confirm only the failed portion's
resources are spared from diffing.

### Tests for User Story 4

- [X] T038 [P] [US4] Write `backend/tests/unit/test_scan_scheduling.py` — daily trigger, on-demand trigger, operator-only gating (research.md R-205) — S15, FR-026, FR-026a
- [X] T039 [P] [US4] Write `backend/tests/integration/test_scan_diffing.py` — Testcontainers PostgreSQL, first-seen/last-seen preserved correctly, deleted marker set only on a completed scan — S16, FR-029, FR-030, SC-003
- [X] T040 [P] [US4] Write `backend/tests/integration/test_partial_scan_no_overdelete.py` — the SC-006 scenario: force one unit of work to fail, confirm unaffected resources' deleted markers are unchanged — S16, FR-031, FR-032, SC-006
- [X] T041 [P] [US4] Write `backend/tests/unit/test_concurrent_scans_isolated.py` — two accounts' scans do not cross-contaminate results — S15, FR-027, SC-007

### Implementation for User Story 4

- [X] T042 [US4] Write `infra/modules/scan/main.tf` — Step Functions Standard state machine with a Map state fanning out per account × region × service group (research.md R-211). The ASL definition lives in its own `infra/modules/scan/scan_workflow.asl.json`, referenced via `file("./scan_workflow.asl.json")`, never inlined as a heredoc — that separation is what makes T042a's validation possible without parsing HCL — S15, FR-023. **Two corrections found only by actually running `terraform validate`, not by inspection**: (1) `aws_sfn_state_machine` has no `definition_substitutions` argument in provider 5.100.0 (confirmed by inspecting the installed provider binary directly) — CloudFormation's `DefinitionSubstitutions` property was never mirrored into this Terraform resource; switched to `templatefile()`, which still keeps the committed `.asl.json` file independently parseable by T042a's checker (the `${WorkerLambdaArn}` placeholder is a plain, valid JSON string either way). (2) Unit-of-work granularity is **one scan region**, not account × region × service group as literally written above — the `Connector` protocol (`connectors/base.py`, Phase 2, already merged) has no service-group parameter; see `app/scan/orchestrator.py`'s module docstring for the full reasoning. Also wired `infra/modules/api` to accept and use the resulting state machine ARN (T048 needs `states:StartExecution`) and added the S3 lifecycle rule `storage/main.tf` reserved for this spec (research.md R-207).
- [X] T042a [US4] Write `ops/scripts/check_stepfunctions_asl.py` and wire it into `ci.yml`'s `terraform-validate` job, alongside `check_terraform_ascii.py` — an offline structural check (StartAt/States/Next references resolve, no dead-end states) closing the same class of validate/plan blind spot terraform-ascii closes for a different resource type, found live during `/speckit-analyze` (finding F6) — S15, FR-023, playbook §0.5.2. Built during the earlier `/speckit-analyze` F6 fix, ahead of `/speckit-implement`; only the tasks.md checkbox was outstanding.
- [X] T043 [US4] Write `infra/modules/scan/scheduler.tf` — EventBridge Scheduler daily rule invoking the state machine — S15, FR-026
- [X] T044 [US4] Write `backend/handlers/scan_worker_handler.py` — the Lambda entrypoint Step Functions invokes per unit of work, assuming the target role once per unit (research.md R-206) — S15, FR-023. One Lambda handles three actions (`scan_unit`, `finalize_scan`, `trigger_daily`) via an `action` field rather than three separate functions, matching research.md R-207's cost table, which anticipated exactly one scan-worker Lambda line item.
- [X] T045 [US4] Write `backend/app/scan/orchestrator.py` — builds the Step Functions execution input from an account's region/service-group combinations — S15, FR-023. Allowlisted in `check_connector_boundary.py` for one boto3 call (`states:StartExecution`) — starting the platform's own state machine execution is platform infrastructure, the same class of exception as `app/core/db.py`'s Secrets Manager fetch, not a reach into a scanned account.
- [X] T046 [US4] Implement diffing/persistence: first-seen/last-seen updates and the deleted-marker sweep, gated on `scan.status` in (`succeeded`, `partial`) and scoped to completed units only (research.md R-204) — S16, FR-029, FR-030, FR-031, FR-032, SC-003. The sweep identifies "not found this scan" via `last_seen_at < scan.started_at` rather than an explicit found-ARN list threaded through Step Functions state, to avoid the 256KB execution-payload limit on a large account (Edge Cases).
- [X] T047 [US4] Implement the `running → succeeded | partial | failed` scan-status transition logic — S16, FR-031, FR-032. Found and fixed a real bug while testing this, not by inspection: `test_scan_diffing.py`'s and `test_partial_scan_no_overdelete.py`'s DB-session test fixtures never closed their SQLAlchemy session, leaving an idle-in-transaction connection that held a lock the *next* test's `clean_database` fixture (`DROP SCHEMA ... CASCADE`) then hung on indefinitely -- surfaced only by running two tests from the same file back to back, not by running either alone. Fixed with a `try/finally: session.close()` in both fixtures.
- [X] T048 [US4] Write `POST /accounts/{id}/scans` (on-demand trigger), gated `require_role(Role.OPERATOR)` only — S15, FR-026a. Confirmed via a structural unit test that the route does not reuse `app.core.security.require_operator` (which also admits admin).
- [X] T049 [US4] Write the raw immutable snapshot writer to spec 1's provisioned S3 bucket, with the 30-day-class lifecycle rule research.md R-207 decided — S16, FR-028. One object per (scan, region) rather than one per scan, written directly by `scan_worker_handler.py` (already boto3-allowlisted) so a large scan never needs its full result set held in memory to write one snapshot.
- [X] T050 [US4] Wire bounded retry counts (FR-024) and concurrency limits (FR-025) into the Step Functions Map state's `MaxConcurrency`/`ToleratedFailurePercentage` configuration, sized per research.md's demo-scale reasoning — S15, FR-024, FR-025. **`ToleratedFailurePercentage` was removed entirely**, not just sized: LocalStack's ASL parser rejects it as a plain integer (`ASLParserException ... mismatched input '100' expecting NUMBER`, confirmed directly against a running container -- T051), and it was already non-load-bearing in this design regardless, since the ASL's own `Catch`-to-`Pass` pattern (not Step Functions' native tolerance mechanism) is what actually absorbs a unit's failure without aborting the Map state -- removing it fixed a real LocalStack incompatibility with no functional loss. `MaxConcurrency: 5` remains, bounding concurrent Lambda invocations per scan (FR-025). `MaxAttempts: 2` in the per-unit `Retry` block (3 total attempts) bounds retries (FR-024).
- [X] T051 [US4] Write `backend/tests/integration/test_scan_orchestration.py` — resolve research.md R-210's VERIFY marker (LocalStack's Step Functions coverage) here; fall back to Lambda-level moto tests as the primary gate if LocalStack's coverage is thin — S15, FR-023. **R-210 resolved empirically**: LocalStack (community, pinned to `3.8` — `latest` now requires a Pro auth token to even start, confirmed directly) parses and executes this spec's actual committed ASL correctly, including the Map/Catch/Retry fan-out pattern (verified via `get-execution-history` against a live container). Real Lambda *invocation* inside LocalStack was not reliably available in this session's sandboxed environment (`ResourceConflictException: ... state: Failed` on a bare `lambda:Invoke`, unrelated to this spec's code) — the one test needing it skips gracefully with a clear reason when that happens, falling back to the Lambda-level moto tests (`test_scan_diffing.py`, `test_partial_scan_no_overdelete.py`, the enrichment/discovery suites) as R-210's own named fallback.

**Checkpoint**: 🏁 **P1 functionally complete.** Every P1 user story is implemented. What remains
before declaring P1 done is proving it against real AWS, not mocked tests — that's Phase 7.

---

## Phase 7: P1 Completion — Role Matrix, Live Verification, Teardown

**Purpose**: The mocked-test suite proves the logic; this phase proves the system, against a real
AWS account, the way spec 1's T107–T113 did. Playbook §0.5.5: run `/speckit-analyze` a second
time after this phase, before starting Phase 8.

- [X] T052 Write `backend/tests/integration/test_role_matrix_accounts.py` — the full SC-009 three-role matrix, explicitly asserting admin is refused triggering an on-demand scan (the cell a naive "admin can do everything" implementation would get wrong — quickstart.md V9) — S8–S15, SC-009. Two real bugs found while testing, not by inspection: (1) `@mock_aws` on a *test function* does not cover a *fixture's* setup, which runs first — registration's AWS calls were silently escaping the mock entirely until the fixture itself was decorated too. (2) moto's default mocked account ID is `123456789012`, not `000000000000` — a state machine created under moto has that real account ID in its ARN, so an env var pointing at a made-up `000000000000` ARN got a genuine `StateMachineDoesNotExist`, not a mock artifact.
- [X] T053 **Live-verification — partially completed, blocked, and stopped by explicit user decision.** Deployed this spec's work to dev for real (10m14s apply, 65 resources, health check passed). Attempting quickstart.md V1 (`POST /accounts` with `connectionMode: local`) surfaced a genuine infrastructure gap that no mocked test could have caught: `infra/modules/network/main.tf` provisions only S3 (free Gateway endpoint) and Secrets Manager (paid Interface endpoint) — there is no NAT Gateway/instance and no Interface endpoints for STS, Step Functions, the Resource Groups Tagging API, Cloud Control, EC2, RDS, or Lambda's own control-plane APIs. Since a VPC-attached Lambda's ENI can never hold a public IP (a hard AWS platform constraint, not a config choice), the worker Lambda had no path to any of those APIs and the request hung to Lambda's 30s hard timeout with nothing logged. Confirmed via CloudWatch Logs plus direct inspection of the network module — not assumed. Fixing it requires either a NAT Gateway (~$32/mo), a NAT instance (~$3–4/mo, the cheapest real option), or ~6 paid Interface VPC endpoints (~$88–100/mo); there is no free option given Lambda's VPC networking constraints. Presented to the user with these tradeoffs; the user does not have a second AWS account (so cross-account scenarios, V2 and SC-004's cross-account half, were never attempted regardless), and explicitly chose to stop rather than spend anything to fix the gap: *"stop live verification and accept that the scan/discovery pipeline stays proven only at the mocked-test level for now."* SC-001 through SC-009 therefore remain proven at the mocked-test level (Phases 1–7) only; same-account live proof and all cross-account proof are open, deferred until the user has either a NAT budget or a second AWS account — S8–S16, SC-001–SC-009
- [X] T054 **Teardown and cost sweep** — run immediately after stopping T053, per the user's decision. `ops/teardown.sh dev` → `terraform destroy` ran for ~3.5 hours (RDS/CloudFront/security-group deletion is inherently slow at this resource count) and stopped one resource short: the frontend S3 bucket (`cloudpulse-dev-frontend-767828743440`) had 7 object versions Terraform's `aws_s3_bucket` won't auto-empty, returning `BucketNotEmpty`. Separately, the shell's AWS credentials expired mid-teardown (`InvalidClientTokenId` on the `default` profile) — resolved by the user re-running `aws sso login --profile cloudpulse-dev`. Emptied the bucket directly (`delete-objects` on all 7 versions) and re-ran `terraform destroy`, which completed cleanly: `Destroy complete! Resources: 1 destroyed.`, `terraform state list` empty. Full cost sweep across RDS (clusters/instances/both snapshot types), Lambda, VPC, NAT gateways, EC2, Elastic IPs, ELB/ALB, CloudFront, Cognito, API Gateway, VPC endpoints, Secrets Manager, EventBridge/Scheduler rules, SQS, Step Functions, SNS, CloudWatch alarms/log groups, app S3 buckets, DynamoDB, and KMS aliases: all empty. Only the Terraform state bucket and lock table (`cloudpulse-tfstate-dev`, `cloudpulse-tflock-dev`) remain — bootstrap infrastructure outside this spec's stack, negligible cost, required to run Terraform again later. No cross-account role/ExternalId cleanup was needed since no cross-account registration was ever attempted (T053). `DEV_AUTO_DEPLOY` was never flipped to `true` in CI — this deploy was applied manually — so nothing to revert there — S8–S16, playbook §0.5.3

**Checkpoint**: ⚠️ **P1 functionally complete and proven at the mocked-test level; live verification is
open.** SC-001 through SC-009 pass in CI (370 backend tests) but are not yet proven against a live
AWS account end-to-end — T053 surfaced and stopped short of fixing a real VPC-networking gap, by
explicit user decision to avoid AWS cost rather than a technical blocker. Revisit T053/T054 when a
NAT budget or a second AWS account is available; the gap itself (add a NAT instance or Interface
endpoints to `infra/modules/network`) is not yet fixed and is not scoped to any other task here.

---

## Phase 8: P2 — Extended Enrichment and Scan History

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise a P1 path. If
this phase is dropped entirely, Phases 1–7 still satisfy every P1 success criterion.

- [X] T055 [P] **[P2]** Write `backend/tests/unit/test_extended_enrichment.py` — EKS, DynamoDB, ELB, IAM enrichment functions — S13, S14, S47, FR-020. All four confirmed against real moto fidelity first (same empirical-check discipline as the P1 six, R-209): EKS, DynamoDB, and IAM mock their describe calls faithfully; ELBv2 needs `Scheme` passed explicitly at creation (moto returns `None` rather than AWS's real server-side default of `internet-facing` when it's omitted) — the fixture passes it explicitly rather than working around a gap that doesn't affect this code's read path.
- [X] T056 **[P2]** Extend `coverage_definitions.json` and `connectors/aws.py`'s `ENRICHMENT_FUNCTIONS` registry with the four FR-020 types (`enrich_eks_cluster`, `enrich_dynamodb_table`, `enrich_elb_v2`, `enrich_iam_role`), plus `_ARN_TYPE_HINTS` entries so discovery recognizes their ARNs for dispatch — proving coverage-as-data's extensibility claim (SC-005) on a second, real addition rather than only the original six: zero changes to `app/scan/enrichment.py` or `AwsConnector.enrich()` itself, exactly the seam T036 established — S13, S14, S47, FR-020, SC-005
- [ ] T057 [P] **[P2]** Write `backend/tests/unit/test_scan_history.py` — trigger, timing, counts, outcome retrievable per scan — S17, FR-033
- [ ] T058 **[P2]** Write `GET /accounts/{id}/scans` (scan history), any-role-readable like the accounts view — S17, FR-033

**Checkpoint**: Extended coverage and scan history add depth without touching the P1 demo path.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T059 [P] Update `ops/erd/schema.mmd` to reflect `resource`'s three new columns — FR-028 (spec 1), Principle I. Done in T005's PR, not deferred to Phase 9: the `erd-current` CI gate (added mid-spec-1, playbook §0.5) requires a schema-migration PR to touch `ops/erd/` in the same PR, not a later one.
- [ ] T060 [P] Update `backend/README.md` and `infra/README.md` to describe the new `app/scan/`, `connectors/`, and `infra/modules/scan/` ownership — Principle I
- [ ] T061 Re-run `/speckit-analyze` on spec 002 (playbook §8's second-run note) and resolve any finding before spec 003 begins — Governance

---

## Dependencies

```text
Phase 1 (Setup) ──> Phase 2 (Foundational) ──> Phase 3 (US1: registration)
                                                      │
                                                      ▼
                                            Phase 4 (US2: admin surface)
                                                      │
                                                      ▼
                                            Phase 5 (US3: discovery)
                                                      │
                                                      ▼
                                            Phase 6 (US4: scanning + lifecycle)
                                                      │
                                                      ▼
                                  Phase 7 (P1 completion: role matrix,
                                           live verification, teardown) ──> 🏁 P1 COMPLETE
                                                      │
                                                      ▼
                                  Phase 8 (P2: extended enrichment,
                                           scan history)  [droppable]
                                                      │
                                                      ▼
                                            Phase 9 (Polish)
```

**Honest note on story independence**: US1 (register) must exist before US2 (manage) has anything
to manage, US3 (discover) needs a verified account from US1 to scan, and US4 (keep current) needs
US3's discovery logic to schedule. These are layers, matching spec 1's own precedent for a spec
whose stories build a pipeline rather than four unrelated slices — each phase still has its own
checkpoint and independent test.

**Cross-phase dependencies worth watching**:

- T006 (connector protocol) is consumed by T034 (US3) — do not implement discovery against an
  ad-hoc shape and retrofit the protocol later.
- T042 (Step Functions module) and T044 (scan worker Lambda) are co-dependent — the state machine's
  definition references the Lambda's ARN, so land them in the same PR or the `terraform plan`
  in between will show an unresolvable reference.
- T042a needs T042's `scan_workflow.asl.json` to exist first — land them in the same PR. This is
  also why T042 specifies the ASL definition as a separate file rather than an inline heredoc:
  T042a's check cannot reach inside HCL to validate it.
- T053/T054 must stay adjacent. Do not let Phase 8 work begin between live-verification and
  teardown — that is exactly the gap that let a torn-down environment quietly come back to life
  once already (playbook §0.5.3's own origin story).

## Parallel Opportunities

| Phase | Parallel set | Why safe |
|---|---|---|
| 1 | T001–T004 | Distinct directories, no shared state |
| 2 | T006–T008, T010 | Separate files; T005 (migration) and T009 (models) touch shared schema, sequence those two |
| 3 | T011–T013 | Separate test files |
| 4 | T020–T021 | Separate test files |
| 5 | T029–T032 | Separate test files |
| 6 | T038–T041 | Separate test files |
| 8 | T055, T057 | Separate test files |
| 9 | T059–T060 | Independent documents |

**Solo sequencing note**: as with spec 1, `[P]` means "no dependency, so order is free" — batching
several small `[P]` changes into one same-day PR is the practical use of this marker for a solo
maintainer, not literal concurrency.

## Implementation Strategy

**MVP scope**: Phases 1–3 (T001–T019). That delivers roles-only account registration with
verification — the trust boundary every later phase depends on, and the smallest slice with
standalone value.

**Incremental delivery**: each phase ends at a checkpoint demonstrable on its own. Phase 4 adds
management, Phase 5 adds discovery, Phase 6 adds continuous refresh — Phase 7's checkpoint is the
full P1 demo path, proven live.

**Principle VIII discipline**: T055–T058 are the only P2 tasks and are scheduled last. If time
runs short, Phase 8 is what gets cut — not any part of Phases 1–7.
