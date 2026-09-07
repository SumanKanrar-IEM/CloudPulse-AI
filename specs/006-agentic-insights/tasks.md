---
description: "Task list for spec 006 — agentic insights"
---

# Tasks: Agentic Insights

**Input**: Design documents from `/specs/006-agentic-insights/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included and are NOT optional here — constitution Principle VI's quality
gates require tests written with the code, and Principle IV's grounding rule is only meaningful if
something proves a fabricated reference is actually rejected.

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable — different files, no dependency on an incomplete task
- **[Story]**: US1–US7 from spec.md
- Every task names exact file paths

## Tier Summary

**P1 (must complete first, deliverable with zero P2 items)**: Phases 1–5, T001–T031 plus the
T011a/T011b insertions — 33 tasks. Delivers
SC-001, SC-002, SC-004, SC-005, SC-008, SC-009 — the digest, the suggester, and every
grounding/safety guarantee.

**P2 (stretch)**: Phases 6–10, T032–T060. Every P2 task is marked **[P2]** in its description.
Dropping all five P2 stories leaves both P1 stories and their success criteria intact — only
SC-003, SC-006, SC-007 and FR-015–FR-024 go with them.

## Process Note

If implementation surfaces a fix this list did not anticipate, **add the task here before opening
that fix's PR** — a `T0XXa`-style insertion next to the task it corrects. `pr-task-reference` CI
requires a task ID in the PR body regardless; the task exists for traceability, not to satisfy the
gate. Specs 003–005 each ended with several such tasks and the practice is what made their PR
history readable.

---

## Phase 1: Setup & Schema

**Purpose**: The tables and scaffold every later phase writes to.

- [ ] T001 Create the `agents/` tree per plan.md — `agents/definitions/`, `agents/action-groups/`,
      `agents/prompts/`, `agents/evals/`, each with a README stating what it holds and that spec
      001 reserved this tree. Replace `agents/README.md`'s "deliberately empty" wording, which
      stops being true here — S43, S44, Principle I
- [ ] T002 Write `backend/migrations/versions/0015_agentic_insights.py` — the seven tables from
      data-model.md (`agent_run`, `insight_digest`, `grounding_rejection`, `coverage_proposal`,
      `resource_metric`, `forecast`, `rightsizing_recommendation`), the **seven** enum types
      data-model.md's "Enum additions" section lists, and the partial unique indexes. Declare `REVERSIBLE: yes` — S43, FR-005, FR-006a
      `erd-current` CI requires `ops/erd/schema.mmd` to change in this same PR.
- [ ] T003 Update `ops/erd/schema.mmd` with the seven new entities and their relationships to
      `tenant`, `finding`, `resource`, `sda` and `cloud_account` — S43, FR-028 (spec 001)
- [ ] T004 [P] Add the SQLAlchemy models to `backend/app/models/core.py` and the enums to
      `backend/app/models/enums.py`, every table `TenantScoped` — S43, FR-005, FR-006a
- [ ] T005 [P] Write `backend/tests/integration/test_migration_0015.py` — every revision applies
      and downgrades cleanly, the enums hold exactly their documented values, and the partial
      unique indexes reject the duplicates they exist to prevent — S43, FR-006a

**Checkpoint**: Schema exists; nothing reads it yet.

---

## Phase 2: Foundational — Grounding & Run Accounting

**Purpose**: The two things all seven stories depend on. Built as their own phase deliberately
(plan.md): if the validator were built inside the digest phase, the suggester's compliance with
Principle IV would be an accident of ordering rather than a property of the design.

⚠️ **Blocking**: no user story may start before this phase completes.

- [ ] T006 [P] Write `backend/tests/unit/test_grounding.py` — an output naming a resource absent
      from the store is rejected; one naming only real resources passes; a figure that does not
      match the store is rejected; the validator makes no model call and is deterministic over
      the same input. Covers FR-001a's boundary in both directions: a prose numeral like "the last
      7 days" does not trigger rejection, and a fabricated *platform* figure does — S43, FR-001,
      FR-001a, FR-006, research.md R-607
- [ ] T007 Write `backend/app/governance/grounding.py` — the deterministic validator: extract
      candidate ARNs, resource ids, project names and numerals from an agent output, resolve each
      against the governance store, return a pass/reject verdict naming the first unresolvable
      reference. FR-001a fixes *what* is validated: platform-computed quantities (counts, scores,
      percentages, money) resolve; ordinary prose numerals do not; a quantity presented as a
      platform figure that the platform never computed is unresolvable — S43, FR-001, FR-001a,
      R-607
- [ ] T008 [P] Write `backend/tests/unit/test_agent_run.py` — a run records its definition hash,
      cost and cap; reaching the cap yields `truncated`, not `failed`; an unreachable model yields
      `failed` with a reason; `finished_at` is set on every terminal state — S43, FR-004, FR-005
- [ ] T009 Write `backend/app/governance/agent_runs.py` — open/close a run, enforce the cost cap,
      record `definition_hash`, and expose FR-004a's retention rule (item-wise capabilities keep
      validated items on truncation; whole-artifact capabilities discard). The cap is read from
      the environment at point of use with a conservative fallback, **not** added to `Settings` —
      see R-612 and spec 005's T029a, where the Settings route broke 11 unrelated tests — S43,
      FR-004, FR-004a, FR-005, R-612
- [ ] T010 [P] Write `backend/app/governance/definition_hash.py` and
      `backend/tests/unit/test_definition_hash.py` — content-hash a prompt/definition file so
      every stored output traces to what produced it; the hash changes when the file does — S43,
      FR-005, R-608
- [ ] T011 Extend `backend/connectors/aws.py` with `invoke_agent(...)` — the only place the
      Bedrock SDK appears (Principle V, FR-054). Returns raw output; makes no grounding or cost
      judgement, which belong to `app/governance/` — S43, FR-003, R-601, R-602
- [ ] T011a [P] Write `backend/tests/integration/test_degraded_mode.py` — **FR-007a and SC-009,
      the requirement that makes P1 shippable under R-605.** With the model unreachable: the run
      is recorded `failed` with a reason; `GET /insights/digest` serves the last valid digest or
      the explicit not-enough-data state; the findings workbench shows suggestions already stored
      and none fabricated; and no surface renders a partial or placeholder result. Then replay a
      fixed fixture with the intelligence layer disabled and assert inventory, finding and score
      output are **byte-identical** to the run with it enabled — SC-009's own stated comparison,
      not a prose claim of no regression — S43, S44, FR-007a, SC-009
- [ ] T011b [P] Write `backend/tests/unit/test_deterministic_core_isolation.py` — **Principle IV's
      own testable clause**, which no other task asserts: no module under `app/scan/`,
      `app/governance/validation.py`, `app/governance/scoring.py` or `app/governance/spend.py`
      imports a Bedrock client or reaches `app/governance/grounding.py`'s agent path, and
      replaying a fixed account snapshot twice produces byte-identical inventory and finding sets.
      `check_connector_boundary.py` restricts boto3 to `connectors/` generally but says nothing
      about Bedrock specifically reaching the deterministic core — S43, FR-007, Principle IV
- [ ] T012 [P] Write `backend/tests/unit/test_agent_read_only.py` — the action-group principal is
      refused on every non-GET method and holds no cloud credential, asserted against spec 001's
      existing `app/core/agent_access.py` rather than a re-implementation — S43, FR-002, FR-003,
      FR-056 (spec 001)

**Checkpoint**: Any capability can now run, be capped, be recorded, and have its output validated
— and the two guarantees that let P1 ship without a reachable model (FR-007a/SC-009) and keep the
deterministic core model-free (FR-007) are asserted rather than assumed.

---

## Phase 3: User Story 1 — Insight Digest (Priority: P1)

**Goal**: A daily plain-language digest on the dashboard whose every reference is real (S43,
FR-008, FR-008a, FR-009, FR-010).

**Independent Test**: Run a digest against a store with known findings, a known compliance
movement and a known spend delta; confirm it renders, and that every identifier and figure exists
in the store.

### Tests for User Story 1

- [ ] T013 [P] [US1] Write `backend/tests/unit/test_digest_selection.py` — FR-008a's deterministic
      order: severity descending, then escalated before not, then oldest first; the same finding
      set always selects the same digest set; the agent is not consulted for ranking — S43,
      FR-008a, R-606a
- [ ] T014 [P] [US1] Write `backend/tests/integration/test_digest_pipeline.py` — a run produces
      one digest per tenant per day; a re-run replaces rather than duplicating; a draft naming an
      absent resource is rejected and recorded in `grounding_rejection` with no digest stored; a
      tenant whose inputs cross no FR-008b threshold gets `is_empty = true` rather than an empty
      card, and one that crosses a threshold does not; a truncated digest run discards its partial
      output entirely (FR-004a) — S43, FR-001, FR-004a, FR-008, FR-008b, FR-010

### Implementation for User Story 1

- [ ] T015 [US1] Write `backend/app/governance/digest.py` — select findings per T013's order,
      assemble the compliance and spend inputs, invoke through T011, validate through T007, and
      persist an `insight_digest` row plus its `agent_run`. FR-008b's notability thresholds are
      computed here, before the agent is invoked, and read from the environment per R-612 rather
      than from literals or `Settings` — the agent never decides what counts as notable — S43,
      FR-008, FR-008a, FR-008b, FR-009, FR-010, R-612
- [ ] T016 [US1] Write `agents/definitions/digest.json`, `agents/prompts/digest.md` and
      `agents/action-groups/digest_tools.py` — the action group reads findings, compliance and
      spend through the platform API only (R-602), never the database — S43, FR-003, R-601, R-602
- [ ] T017 [US1] Write `backend/handlers/digest_worker_handler.py` — the daily EventBridge
      entrypoint — S43, FR-008, R-605
- [ ] T018 [US1] Write `backend/app/api/routers/insights.py` — `GET /insights/digest`,
      `GET /insights/runs`, `GET /insights/rejections`, all `require_viewer`-gated. Regenerate
      `backend/openapi.generated.yaml` and the frontend client — S43, FR-009, FR-006
- [ ] T019 [P] [US1] Extend `frontend/src/app/features/overview/compliance-overview.component.ts`
      with the digest card, labelled with the run that produced it so a stale digest is never
      mistaken for current — S43, FR-009
- [ ] T020 [US1] Extend `infra/modules/agents/{main.tf,scheduler.tf}` — the digest agent, its
      alias, its guardrail, the action-group Lambda and the daily schedule — S43, R-601, R-605,
      R-606
      `terraform fmt -check -recursive infra/` and `terraform validate` must pass.

**Checkpoint**: SC-001 and SC-004 provable at the mocked-test level.

---

## Phase 4: User Story 2 — Remediation Suggester (Priority: P1)

**Goal**: Every open finding carries an AI-drafted fix and blast-radius note, and nothing can
apply it (S44, FR-011–FR-014).

**Independent Test**: With open findings across every class, run the suggester; confirm each gets
a resource-specific suggestion marked `ai_generated`, and that no endpoint or control applies one.

### Tests for User Story 2

- [ ] T021 [P] [US2] Write `backend/tests/unit/test_suggester_rules.py` — a suggestion is drafted
      per individual finding and names that finding's own resource (Clarification 2026-09-05); an
      existing `admin_seeded` suggestion is never overwritten; a finding no longer open is skipped
      — S44, FR-011, FR-013, FR-014
- [ ] T022 [P] [US2] Write `backend/tests/integration/test_suggester_pipeline.py` — an
      `ai_generated` suggestion is written and rendered distinctly from `admin_seeded`; a
      suggestion failing grounding is rejected and the finding shows none; a truncated run keeps
      every validated suggestion produced before the cap (FR-004a) and the remainder are picked
      up next run — S44, FR-001, FR-004a, FR-011, FR-012

### Implementation for User Story 2

- [ ] T023 [US2] Extend `backend/app/governance/suggestions.py` with the `ai_generated` writer —
      the seam spec 003 defined and spec 004 rendered, which no code path has ever produced. Must
      not be reachable from any human-facing endpoint — S44, FR-011, FR-012, FR-013
- [ ] T024 [US2] Write `agents/definitions/suggester.json`, `agents/prompts/suggester.md` and
      `agents/action-groups/suggester_tools.py` — reads the finding, its resource and its rule
      through the platform API — S44, FR-003, R-602
- [ ] T025 [US2] Write `backend/handlers/suggester_worker_handler.py` — daily entrypoint,
      processing findings in priority order until the cost cap — S44, FR-004, FR-011
- [ ] T026 [P] [US2] Verify no apply/execute control exists for a suggestion anywhere in
      `frontend/src/app/features/findings/` or the API surface, and add
      `backend/tests/integration/test_no_remediation_execution.py` asserting it — S44, FR-002,
      SC-005
- [ ] T027 [US2] Extend `infra/modules/agents/` with the suggester agent, alias, guardrail,
      action-group Lambda and schedule — S44, R-601, R-606

**Checkpoint**: SC-002 and SC-005 provable at the mocked-test level. 🏁 Both P1 stories complete.

---

## Phase 5: P1 Completion — Role Matrix, Live Verification, Teardown

- [ ] T028 Write `backend/tests/integration/test_role_matrix_insights.py` — the full matrix across
      this spec's P1 read surfaces (`GET /insights/digest`, `/insights/runs`,
      `/insights/rejections`): all three roles read; an unauthenticated caller gets 401; an
      authenticated caller with no recognised group gets 403. Assert response bodies, not just
      status codes, so an empty result cannot pass as success — S43, S44, FR-009
- [ ] T029 [P] Run R-604's verification and record the result in research.md **before** any
      funding claim is made either way:
      `aws ec2 describe-vpc-endpoint-services --query 'ServiceNames' --output text | tr '\t' '\n' | grep -iE 'bedrock|monitoring'`
      A planning-time attempt returned a false "0 available" for every service because an expired
      SSO token was swallowed by `2>/dev/null || echo 0`. Do not repeat that pattern — let the
      command fail loudly — S43, R-604
- [ ] T030 **Live-verification.** Deploy to dev (dispatch `Deploy dev`). Confirm the deploy is
      healthy and the version matches trunk HEAD; confirm the digest and suggester Lambdas,
      their schedules and their log groups exist with the intended shape; confirm
      `GET /insights/digest` is reachable and correctly role-gated. **Per T029's result**, either
      exercise a real agent invocation or record SC-001/SC-002/SC-004 as proven at the
      mocked-test level with the R-605 bound stated — do not attempt a live invocation blind.
      **The precondition is two-deep, and both halves are blocked**: the model may be unreachable,
      *and* the findings/spend a digest summarises cannot be produced by a live scan, because
      account registration calls STS and the Tagging API with no route out of the VPC (spec 005
      T051a). Seed fixture data rather than expecting a live scan to supply it, and say so in the
      outcome — quickstart.md's Prerequisites now states this.
      Note: a `Deploy dev` run labelled *cancelled* may still have applied — check AWS directly
      rather than trusting the label (spec 005's own live-verification task found exactly that: a
      job timeout after `terraform apply` had completed, leaving an environment up and billing) — S43, S44, SC-001, SC-002, SC-004
- [ ] T031 **Teardown and cost sweep**, immediately following T030, never separated from it by
      other work: full playbook §0.5.3 sweep, extended to confirm this spec's agents, aliases,
      guardrails, action-group Lambdas, schedules and log groups are gone. Take a baseline sweep
      *before* deploying so the post-teardown sweep is a real before/after. Check
      `retentionInDays==null` log groups specifically — spec 005's teardown found an RDS-created
      orphan Terraform never managed and `destroy` never touched — playbook §0.5.3

**Checkpoint**: 🏁 **P1 complete.** Every P1 criterion provable; live-verification honestly bounded.

---

## Phase 6: User Story 3 — Coverage Advisor (Priority: P2)

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise the P1 path.

- [ ] T032 [P] [US3] **[P2]** Write `backend/tests/unit/test_coverage_advisor.py` — a gap
      closeable by a rule extension is proposed; one closeable by enabling an existing enricher is
      proposed; a type with **no** existing enrichment routine is surfaced as advisory only and
      never as an acceptable proposal (FR-015a, R-603) — S43, FR-015, FR-015a
- [ ] T033 [P] [US3] **[P2]** Write `backend/tests/integration/test_coverage_proposal_flow.py` —
      accept applies tenant-wide on the next scan with no code change; reject is not re-proposed;
      a non-admin can read but not decide; an advisory gap has no decision endpoint at all — S43,
      FR-016, FR-017, FR-018
- [ ] T034 [US3] **[P2]** Write `backend/app/governance/coverage_advisor.py` — gap detection
      against `coverage_definitions.json` and the rule registry, proposal creation, and the
      accept/reject transition — S43, FR-015, FR-016, FR-017, FR-018
- [ ] T035 [US3] **[P2]** Write `agents/definitions/advisor.json`, `agents/prompts/advisor.md`
      and `agents/action-groups/advisor_tools.py` — S43, FR-003
- [ ] T036 [US3] **[P2]** Write `backend/app/api/routers/coverage_proposals.py` —
      `GET /coverage-proposals`, `GET /coverage-proposals/advisory-gaps` (no decision endpoint, by
      design), `POST /coverage-proposals/{proposalId}/decision` admin-gated. Regenerate the
      contract and client — S43, FR-016, FR-017, FR-015a
- [ ] T037 [P] [US3] **[P2]** Write `frontend/src/app/features/coverage-proposals/` — proposals
      with accept/reject for admins, advisory gaps rendered distinctly with no control at all;
      wire the route into `app.config.ts` — S43, FR-016, FR-015a
- [ ] T038 [US3] **[P2]** Extend `infra/modules/agents/` with the advisor agent and its schedule —
      S43, R-606

**Checkpoint**: SC-003 provable.

---

## Phase 7: User Story 4 — Metrics Collection (Priority: P2)

- [ ] T039 [P] [US4] **[P2]** Write `backend/tests/unit/test_metrics_collection.py` — a period
      already collected is not duplicated; a resource with no measurement is recorded as unknown,
      never zero (FR-020) — S50, FR-019, FR-020
- [ ] T040 [US4] **[P2]** Write `backend/app/governance/metrics.py` — normalise and persist
      `resource_metric` rows per resource and period — S50, FR-019, FR-020
- [ ] T041 [US4] **[P2]** Extend `backend/connectors/aws.py` with `get_metric_data(...)` —
      CloudWatch `GetMetricData`, the only place that SDK call appears — S50, FR-019, R-606
- [ ] T042 [US4] **[P2]** Write `backend/handlers/metrics_collector_handler.py` — scheduled
      collection; per-account failure isolated so one account's failure does not stop others —
      S50, FR-019
- [ ] T043 [US4] **[P2]** Extend `infra/modules/agents/` with the collector Lambda, its schedule
      and `cloudwatch:GetMetricData` — S50, R-606
      Note R-606: this is the one P2 cost that grows with inventory (resources × metrics ×
      periods). State the dev posture explicitly in the module.

---

## Phase 8: User Story 5 — Forecasting (Priority: P2)

- [ ] T044 [P] [US5] **[P2]** Write `backend/tests/unit/test_forecasting.py` — the calculation is
      deterministic: the same history always yields the same forecast (FR-022); a project below
      FR-021a's configured minimum period count yields "not enough data", never a projection from
      too few points, and one exactly at the minimum does forecast — S51, FR-021, FR-021a,
      FR-022
- [ ] T045 [P] [US5] **[P2]** Write `backend/tests/integration/test_forecast_backtest.py` —
      backtesting against held-out actuals reports a measured error, and re-running reproduces it
      exactly — S51, FR-022, SC-006
- [ ] T046 [US5] **[P2]** Write `backend/app/governance/forecasting.py` — the deterministic
      calculation, with FR-021a's minimum-period threshold read from the environment per R-612.
      **No model
      call may produce or alter a forecast figure** (FR-021, Clarification 2026-09-05) — S51,
      FR-021, FR-021a, FR-022
- [ ] T047 [US5] **[P2]** Write `backend/app/api/routers/forecasts.py` — `GET /forecasts`,
      `require_viewer`-gated. Regenerate the contract and client — S51, FR-021

---

## Phase 9: User Story 6 — Rightsizing (Priority: P2)

- [ ] T048 [P] [US6] **[P2]** Write `backend/tests/unit/test_rightsizing.py` — a persistently
      low-utilization resource is recommended down with its evidence and an estimated monthly
      saving; a high or variable resource is never recommended down (FR-023) — S52, FR-023
- [ ] T049 [US6] **[P2]** Write `backend/app/governance/rightsizing.py` — S52, FR-023
- [ ] T050 [US6] **[P2]** Write `backend/app/api/routers/rightsizing.py` — `GET /rightsizing`,
      `require_viewer`-gated, no apply control (FR-002). Regenerate the contract and client — S52,
      FR-023, FR-002
- [ ] T051 [P] [US6] **[P2]** Write `frontend/src/app/features/insights/` — rightsizing
      recommendations with their evidence inline; wire the route — S52, FR-023

---

## Phase 10: User Story 7 — Forecast Narratives (Priority: P2)

- [ ] T052 [P] [US7] **[P2]** Write `backend/tests/unit/test_narrative_validation.py` — a
      narrative whose figures match the chart passes; one introducing any figure the deterministic
      calculation did not produce is rejected and not displayed (FR-024) — S53, FR-024
- [ ] T053 [US7] **[P2]** Write the narrator agent definition, prompt and action group in
      `agents/`, reusing T007's validator with an exact-figure-match mode — S53, FR-024, FR-001
- [ ] T054 [P] [US7] **[P2]** Render narratives on the cost and forecast pages in
      `frontend/src/app/features/cost/`, suppressed entirely when validation fails — S53, FR-024,
      SC-007

**Checkpoint**: SC-007 provable. P2 scope complete.

---

## Final Phase: Polish & Cross-Cutting

- [ ] T055 [P] Write `agents/evals/` cases and wire the eval suite into `.github/workflows/ci.yml`
      — runs against recorded fixtures, never live Bedrock, so CI stays deterministic and free
      (R-609). A prompt change that breaks a grounding expectation must fail the PR — S43, S44,
      FR-005, R-609
- [ ] T056 [P] Update `backend/README.md`, `frontend/src/app/features/README.md`,
      `infra/README.md` and `agents/README.md` — the new governance modules, the three worker
      handlers, `infra/modules/agents/`, the new frontend areas, and what `agents/` now holds —
      Principle I
- [ ] T057 Add the spec 006 section to `AI_WORKFLOW_JOURNAL.md`. Spec 003's second analyze pass
      raised a missing journal section as **H1 CRITICAL** (a Principle I violation) and spec 002's
      H1 caught it before that; spec 005 had to add it retroactively as T026a. Written as its own
      task this time rather than discovered a fourth time — Principle I
- [ ] T058 **Live-verify P2** — deploy and exercise the coverage-proposal accept path end to end.
      SC-003 needs no model call, which makes it the P2 criterion most likely to be provable live
      — **but its input is not free either**: the advisor detects gaps from scanned inventory, so
      the accept path runs against seeded fixture inventory unless R-407 is funded. Verify the
      acceptance transition and its effect on the next scan's configuration; record explicitly
      what was proven against real AWS and what against fixtures. Do not repeat spec 005's R-511
      error of calling a capability live-verifiable because the capability itself makes no AWS
      call — S43, SC-003, FR-015a
- [ ] T059 **Teardown and cost sweep**, immediately following T058, never separated from it —
      playbook §0.5.3
- [ ] T060 Re-run `/speckit-analyze` on spec 006 and resolve any finding. Check *data
      preconditions*, not only API shapes: spec 005's analyze pass compared shapes and still
      missed that utilization's live verification was impossible because its input could not be
      produced live — Governance

**Checkpoint**: 🏁 **P1 and P2 complete at the mocked-test level**, with live-provability bounded
by whatever T029 establishes about Bedrock's VPC reachability.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → Phase 3+**: strictly sequential. Phase 2 is blocking for every story.
- **US1 and US2 are independent of each other** — different agents, different tables, different
  surfaces. Either could ship first; US1 is sequenced first only because the digest is the
  showcase capability.
- **US3 depends on nothing but Phase 2.** US4 feeds US5, US6 and US7 (metrics are the history
  forecasts and rightsizing both read). US7 depends on US5 for the figures a narrative states, and
  additionally on US6 wherever rightsizing figures are narrated — matching the spec's own wording
  for those stories rather than the narrower "US7 depends on US5" this line previously carried.
- **`infra/modules/agents/` is a shared-file lineage**: T020, T027, T038 and T043 each append to
  it. Sequential, never concurrent — each should pull latest trunk before editing rather than
  assume the file is as its branch found it. This is the same discipline spec 005 used for
  `infra/modules/cost/` after T009/T016/T047.
- **`connectors/aws.py` is touched twice** — T011 (P1) and T041 (P2). Not concurrent.
- **T030/T031 must stay adjacent**, and **T058/T059** likewise. Do not let Phase 6 work begin
  between a live-verification task and its teardown.
- **T029 gates T030's shape**: what live verification can even attempt depends on R-604's answer.

## Parallel Execution Example

Each story's test files are independent and can be written together:

```text
T013 [P] [US1] backend/tests/unit/test_digest_selection.py
T014 [P] [US1] backend/tests/integration/test_digest_pipeline.py
T021 [P] [US2] backend/tests/unit/test_suggester_rules.py
T022 [P] [US2] backend/tests/integration/test_suggester_pipeline.py
```

Phases 6 and 7 can proceed on separate branches once Phase 5 merges — neither touches a file the
other does, except `infra/modules/agents/` (see the lineage note above).

## Implementation Strategy

**MVP**: Phases 1–5 alone deliver the whole P1 demo path — a grounded daily digest and a
per-finding suggester, with every safety guarantee Principle IV requires and no P2 dependency.

**Incremental delivery**: Phase 2's shared foundation means each later story adds one agent, one
set of tools and one surface, rather than re-deriving grounding and cost accounting. P2 is
additive polish; none of it is a prerequisite for declaring P1 complete.
