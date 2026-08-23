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
SC-004 and SC-006 through SC-009. SC-005 (coverage-as-data takes effect with no code change) is
P1 foundation — verified by T054 alongside the rest, not deferred to Phase 8.
**P2 (stretch)**: Phase 8 only, T055–T058. Every P2 task is marked **[P2]** in its description.
Dropping Phase 8 entirely leaves the P1 demo path intact (FR-020's extended enrichment types and
FR-033's scan history are additive, nothing else depends on them) — that is the Principle VIII
check.

---

## Phase 1: Setup

**Purpose**: Fill the directories spec 1 reserved empty. No new dependency — boto3 (already a
spec 1 dependency) covers Cloud Control API, Tagging API, and Step Functions; no new Angular
package either.

- [ ] T001 [P] Create `backend/app/scan/__init__.py` and empty `orchestrator.py`, `discovery.py`, `enrichment.py`, `coverage.py` — S11, FR-014
- [ ] T002 [P] Create `backend/connectors/aws.py` as an empty stub (implemented in Phase 5) — S11, FR-014
- [ ] T003 [P] Create `frontend/src/app/features/accounts/` with empty `accounts-list.component.ts`, `account-form.component.ts`, `accounts.service.ts` — S10, FR-010
- [ ] T004 [P] Create `infra/modules/scan/` with a placeholder `main.tf`, `variables.tf`, `outputs.tf` — S15, FR-023

**Checkpoint**: Directory structure exists; no user story work is blocked waiting for scaffolding.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The connector protocol, the schema extension, and coverage-as-data — every user
story below depends on at least one of these.

**⚠️ CRITICAL**: T005's migration and T006's protocol are load-bearing for every phase after this
one. Land them together in one PR.

- [ ] T005 Write migration `0009_resource_lifecycle_and_detail` adding `state`, `deleted_at`, `detail` to `resource` in `backend/migrations/versions/` — data-model.md, FR-013, FR-030
- [ ] T006 [P] Write `backend/connectors/base.py` — the `Connector` protocol and `NormalizedResource` shape (data-model.md's FR-014 section) — FR-014, Principle V
- [ ] T007 [P] Write `backend/app/scan/coverage.py` loading a coverage-definition file at scan-orchestration time (research.md R-203) — FR-021, FR-022
- [ ] T008 [P] Write `backend/app/scan/coverage_definitions.json` seeded with the six P1 governance-critical types (FR-019) mapped to their enrichment function names — FR-019, FR-021
- [ ] T009 Extend `backend/app/models/` for `resource`'s three new columns; confirm the existing `cloud_account`/`scan` SQLAlchemy models already expose `disabled`/`partial` (data-model.md — no model change needed there, just confirm) — data-model.md
- [ ] T010 [P] Write `backend/tests/unit/test_connector_protocol.py` asserting the protocol shape, and extend `ops/scripts/check_connector_boundary.py`'s existing scope check (no change expected — confirms `connectors/aws.py` doesn't yet violate the boundary with an empty stub) — FR-014, connector-boundary CI

**Checkpoint**: Schema, connector interface, and coverage-as-data are settled. User story work can
begin.

---

## Phase 3: User Story 1 — Connect an account without ever handling a credential (Priority: P1)

**Goal**: Roles-only registration, verified before acceptance, admin-gated.

**Independent Test**: Register the platform's own account (same-account mode) and confirm
verified; separately attempt registration with an access key or an untrusted role and confirm
both refused before storage.

### Tests for User Story 1

- [ ] T011 [P] [US1] Write `backend/tests/unit/test_account_registration.py` — role-only input, access-key rejection, connection-mode validation — S8, S9, FR-001, FR-006
- [ ] T012 [P] [US1] Write `backend/tests/unit/test_external_id_generation.py` — platform-generated, unique per account, sufficient entropy, admin-supplied value rejected — S8, FR-003a
- [ ] T013 [P] [US1] Write `backend/tests/integration/test_cross_account_verification.py` — moto-mocked STS AssumeRole, ExternalId condition required and enforced, dry-run read check — S8, S9, FR-003, FR-007, SC-004

### Implementation for User Story 1

- [ ] T014 [US1] Write `backend/app/scan/verification.py` — dry-run role assumption plus a real read-only action, distinguishing "role not found" from "assumed but no usable access" — S9, FR-005, FR-007
- [ ] T015 [US1] Write `POST /accounts` in `backend/app/api/routers/accounts.py`, gated `require_role(Role.ADMIN)`, accepting both connection modes — S8, S9, FR-002, FR-006, FR-011a
- [ ] T016 [US1] Wire platform-generated ExternalId creation and its Secrets Manager storage into registration, writing only the ARN reference to `cloud_account.external_id_ref` — S8, FR-003a, Principle III
- [ ] T017 [US1] Write the ready-to-deploy cross-account template (CloudFormation) in `infra/modules/scan/cross_account_template.yaml`, scoped read-only, exposed via a new API response field — S8, FR-004, FR-005
- [ ] T018 [US1] Wire an `audit_event` write on every registration attempt (success and refusal), reusing spec 1's `write_audit_event` helper — S8, FR-040 (spec 1)
- [ ] T019 [US1] Confirm FR-009: attempt registering the same underlying AWS account twice (same-account then cross-account, and vice versa) and confirm the second is refused with a message identifying the existing record — S9, FR-009

**Checkpoint**: An account can be connected, roles-only, verified before acceptance. SC-004 is
demonstrable.

---

## Phase 4: User Story 2 — See and manage every connected account in one place (Priority: P1)

**Goal**: The accounts admin surface — visible to all three roles, state-changing actions
admin-gated.

**Independent Test**: With one account registered, load the accounts view and confirm every
required field is visible; confirm an operator or viewer can view but not register/deactivate.

### Tests for User Story 2

- [ ] T020 [P] [US2] Write `backend/tests/integration/test_accounts_view_role_matrix.py` — view accessible to admin/operator/viewer; register/deactivate/reactivate refused for operator and viewer — S10, FR-010a, FR-011a
- [ ] T021 [P] [US2] Write `backend/tests/unit/test_account_deactivate_reactivate.py` — status transitions (`verified`↔`disabled`), in-progress scan allowed to finish, duplicate-registration refusal still applies to a deactivated account — S9, FR-009a, FR-009b, FR-009c, SC-008

### Implementation for User Story 2

- [ ] T022 [US2] Write `GET /accounts` in `accounts.py`, gated `require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER)`, including the verification-failure reason in the response — S10, FR-010, FR-010a, FR-012
- [ ] T023 [US2] Write `PATCH /accounts/{id}` (region-list edit), admin-gated — S9, FR-008, FR-011a
- [ ] T024 [US2] Write `POST /accounts/{id}/deactivate`, admin-gated, refusing a scan-in-progress abort (FR-009b) — S9, FR-009a, FR-011a
- [ ] T025 [US2] Write `POST /accounts/{id}/reactivate`, admin-gated, no re-verification (Edge Cases) — S9, FR-009c, FR-011a
- [ ] T026 [US2] Build `frontend/src/app/features/accounts/accounts-list.component.ts` — mode, region list, status, last-scan summary, failure reason, visible to all roles — S10, FR-010, FR-012
- [ ] T027 [US2] Build `frontend/src/app/features/accounts/account-form.component.ts` — register/deactivate/reactivate actions, disabled (not merely hidden) for non-admin roles per spec 1's role-guard precedent — S9, FR-011, FR-011a
- [ ] T028 [US2] Regenerate the Angular API client for the new endpoints; confirm `client-drift` CI passes — Principle V

**Checkpoint**: The full account lifecycle (register → view → deactivate → reactivate) is usable
end to end through the UI.

---

## Phase 5: User Story 3 — Discover everything in an account, not a curated subset (Priority: P1)

**Goal**: Whole-account discovery via combined generic surfaces, plus targeted enrichment for the
six P1 governance-critical types.

**Independent Test**: Against a test account with an unanticipated resource type and a
deliberately untagged resource, run discovery and confirm both appear with full identity fields.

### Tests for User Story 3

- [ ] T029 [P] [US3] Write `backend/tests/unit/test_discovery_tagging_api.py` — moto-mocked Resource Groups Tagging API sweep, untagged resources included — S12, FR-016, FR-017
- [ ] T030 [P] [US3] Write `backend/tests/unit/test_discovery_cloud_control.py` — moto-mocked Cloud Control `ListResources`; resolve research.md R-209's VERIFY marker here (moto's fidelity) before writing further discovery tests, falling back to a hand-built fixture if moto's coverage is thin — S12, FR-016
- [ ] T031 [P] [US3] Write `backend/tests/unit/test_normalized_resource_shape.py` — every discovered resource conforms to the FR-013 shape regardless of source surface — S11, FR-013
- [ ] T032 [P] [US3] Write `backend/tests/unit/test_enrichment_p1_types.py` — all six P1 types (EC2, EBS, EIP, S3, RDS, Lambda) populate `resource.detail` with state/size/attachment/runtime fields — S13, S14, FR-019

### Implementation for User Story 3

- [ ] T033 [US3] Write `backend/app/scan/discovery.py` — combined Tagging API + Cloud Control sweep, deduplicated (research.md R-201) — S12, FR-016, FR-017
- [ ] T034 [US3] Implement `discover()` on `backend/connectors/aws.py` against the Phase 2 protocol, using each resource's ARN as its stable unique identifier — S11, FR-014, FR-015
- [ ] T035 [US3] Write `backend/app/scan/enrichment.py` — six targeted boto3 describe calls (research.md R-202) — S13, S14, FR-019
- [ ] T036 [US3] Wire enrichment dispatch through `coverage.py`'s data-driven registry rather than an if/elif chain — S47-foundation, FR-021
- [ ] T037 [US3] Implement global-surface once-per-account deduplication (FR-018) in `discovery.py` — S12, FR-018

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

- [ ] T038 [P] [US4] Write `backend/tests/unit/test_scan_scheduling.py` — daily trigger, on-demand trigger, operator-only gating (research.md R-205) — S15, FR-026, FR-026a
- [ ] T039 [P] [US4] Write `backend/tests/integration/test_scan_diffing.py` — Testcontainers PostgreSQL, first-seen/last-seen preserved correctly, deleted marker set only on a completed scan — S16, FR-029, FR-030, SC-003
- [ ] T040 [P] [US4] Write `backend/tests/integration/test_partial_scan_no_overdelete.py` — the SC-006 scenario: force one unit of work to fail, confirm unaffected resources' deleted markers are unchanged — S16, FR-031, FR-032, SC-006
- [ ] T041 [P] [US4] Write `backend/tests/unit/test_concurrent_scans_isolated.py` — two accounts' scans do not cross-contaminate results — S15, FR-027, SC-007

### Implementation for User Story 4

- [ ] T042 [US4] Write `infra/modules/scan/main.tf` — Step Functions Standard state machine with a Map state fanning out per account × region × service group (research.md R-203) — S15, FR-023
- [ ] T043 [US4] Write `infra/modules/scan/scheduler.tf` — EventBridge Scheduler daily rule invoking the state machine — S15, FR-026
- [ ] T044 [US4] Write `backend/handlers/scan_worker_handler.py` — the Lambda entrypoint Step Functions invokes per unit of work, assuming the target role once per unit (research.md R-206) — S15, FR-023
- [ ] T045 [US4] Write `backend/app/scan/orchestrator.py` — builds the Step Functions execution input from an account's region/service-group combinations — S15, FR-023
- [ ] T046 [US4] Implement diffing/persistence: first-seen/last-seen updates and the deleted-marker sweep, gated on `scan.status` in (`succeeded`, `partial`) and scoped to completed units only (research.md R-204) — S16, FR-029, FR-030, FR-031, FR-032, SC-003
- [ ] T047 [US4] Implement the `running → succeeded | partial | failed` scan-status transition logic — S16, FR-031, FR-032
- [ ] T048 [US4] Write `POST /accounts/{id}/scans` (on-demand trigger), gated `require_role(Role.OPERATOR)` only — S15, FR-026a
- [ ] T049 [US4] Write the raw immutable snapshot writer to spec 1's provisioned S3 bucket, with the 30-day-class lifecycle rule research.md R-207 decided — S16, FR-028
- [ ] T050 [US4] Wire bounded retry counts (FR-024) and concurrency limits (FR-025) into the Step Functions Map state's `MaxConcurrency`/`ToleratedFailurePercentage` configuration, sized per research.md's demo-scale reasoning — S15, FR-024, FR-025
- [ ] T051 [US4] Write `backend/tests/integration/test_scan_orchestration.py` — resolve research.md R-210's VERIFY marker (LocalStack's Step Functions coverage) here; fall back to Lambda-level moto tests as the primary gate if LocalStack's coverage is thin — S15, FR-023

**Checkpoint**: 🏁 **P1 functionally complete.** Every P1 user story is implemented. What remains
before declaring P1 done is proving it against real AWS, not mocked tests — that's Phase 7.

---

## Phase 7: P1 Completion — Role Matrix, Live Verification, Teardown

**Purpose**: The mocked-test suite proves the logic; this phase proves the system, against a real
AWS account, the way spec 1's T107–T113 did. Playbook §0.5.5: run `/speckit-analyze` a second
time after this phase, before starting Phase 8.

- [ ] T052 Write `backend/tests/integration/test_role_matrix_accounts.py` — the full SC-009 three-role matrix, explicitly asserting admin is refused triggering an on-demand scan (the cell a naive "admin can do everything" implementation would get wrong — quickstart.md V9) — S8–S15, SC-009
- [ ] T053 **Live-verification.** Flip `DEV_AUTO_DEPLOY` to `true` (or dispatch `Deploy dev` manually), deploy this spec's work to dev, and walk quickstart.md V1–V9 against a real primary AWS account and a real second AWS account for cross-account verification (research.md R-208) — confirms SC-001 through SC-009 against reality, not mocks — S8–S16, SC-001–SC-009
- [ ] T054 **Teardown and cost sweep**, immediately following T053, never separated from it by other work: run the full playbook §0.5.3 sweep, plus this spec's own additions from research.md R-207/R-208 — confirm the second AWS account's cross-account role and ExternalId secret are removed, `aws stepfunctions list-state-machines` returns none for this environment, and set `DEV_AUTO_DEPLOY` back to `false` if dev is being left torn down — S8–S16, playbook §0.5.3

**Checkpoint**: 🏁 **P1 COMPLETE, proven against real AWS.** SC-001 through SC-009 all pass live,
not just in CI. Everything below is optional.

---

## Phase 8: P2 — Extended Enrichment and Scan History

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise a P1 path. If
this phase is dropped entirely, Phases 1–7 still satisfy every P1 success criterion.

- [ ] T055 [P] **[P2]** Write `backend/tests/unit/test_extended_enrichment.py` — EKS, DynamoDB, ELB, IAM enrichment functions — S13, S14, S47, FR-020
- [ ] T056 **[P2]** Extend `coverage_definitions.json` and `enrichment.py` with the four FR-020 types, proving coverage-as-data's extensibility claim (SC-005) on a second, real addition rather than only the original six — S13, S14, S47, FR-020, SC-005
- [ ] T057 [P] **[P2]** Write `backend/tests/unit/test_scan_history.py` — trigger, timing, counts, outcome retrievable per scan — S17, FR-033
- [ ] T058 **[P2]** Write `GET /accounts/{id}/scans` (scan history), any-role-readable like the accounts view — S17, FR-033

**Checkpoint**: Extended coverage and scan history add depth without touching the P1 demo path.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T059 [P] Update `ops/erd/schema.mmd` to reflect `resource`'s three new columns — FR-028 (spec 1), Principle I
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
