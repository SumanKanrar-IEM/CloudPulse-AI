---

description: "Task list template for feature implementation"
---

# Tasks: Tag Compliance and Ownership

**Input**: Design documents from `/specs/003-tag-compliance-and-ownership/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml,
quickstart.md — all merged to `pods/pod73`.

**Process note** (per this task list's own generation instruction): if implementation surfaces a
fix this list didn't anticipate, add a new task for it in this file *before* opening that fix's
PR — `pr-task-reference` CI requires a task ID in the PR body regardless, but the task belongs
here for the same reason every other task does, not invented after the fact just to satisfy the
gate. Spec 002's own tasks.md has several examples of this pattern (T016a, T042a) if a model is
useful.

## Tier Summary

**P1 (demo-critical, frozen)**: Phases 1–8, T001–T033. Completing these satisfies SC-001–SC-004
and SC-006–SC-008 at the mocked-test level (CI), with T032/T033 attempting live proof against a
real AWS account. SC-005 (attribution fallback) needs P2's T038–T039 to exist at all — the one
success criterion honestly tied to P2 completion, per plan.md's Constitution Check table.

**P2 (stretch)**: Phase 9 only, T034–T042. Every P2 task is marked **[P2]** in its description.
Dropping Phase 9 entirely leaves every P1 story and SC-001–SC-004/SC-006–SC-008 intact — only
SC-005, FR-011/FR-012 (SDA admin UI), FR-024–FR-026 (attribution fallback), and FR-027/FR-028
(identity resolution) go with it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US8, matching spec.md)
- Every task cites its backlog S-number and spec requirement(s)

---

## Phase 1: Setup

- [X] T001 Scaffold `backend/app/governance/__init__.py` (empty package, mirroring `app/scan/`'s
      shape per plan.md's Project Structure Decision) and `infra/modules/governance/` (empty
      directory, Terraform files land here starting Phase 7) — no logic yet, just the layout this
      spec's plan.md commits to.

**Checkpoint**: Directory layout exists; nothing yet imports from or deploys it.

---

## Phase 2: Foundational (blocking prerequisites for every user story)

**Purpose**: Schema and seed data every P1 story reads or writes.

- [X] T002 Write `backend/migrations/versions/0010_resource_sda_and_tenant_identity_pattern.py` —
      additive migration adding `resource.sda_id` (FK → `sda.id`, `ON DELETE SET NULL`, nullable),
      the `owner_identity_override` table, and `tenant.owner_identity_pattern` (nullable
      VARCHAR(500)), per data-model.md. In the same migration, seed five `rule` rows at
      `version=1, enabled=true`: `project_name`, `owner`, `project_id`, `created_by` (each
      `required: true`) and `environment` (`required: false`) — data-model.md's "seed data" note;
      delivered as a migration-time INSERT, not application code (FR-001's discipline applied to
      seeding itself) — S18, S18a, FR-001, FR-003, data-model.md `sda_id`/`owner_identity_override`/
      `tenant.owner_identity_pattern`/`rule` seed sections. **Real bug found while implementing
      T004/T006, not by inspection**: the original seed INSERT passed `json.dumps({...})` (a Python
      `str`) as the value for a JSONB column via `op.bulk_insert`. SQLAlchemy's JSONB type
      serializes whatever Python value it's given, so a `str` gets serialized *again* — the column
      ends up holding a JSON string literal containing the JSON text, not a JSON object. Every read
      back through the ORM (`RuleDefinition.model_validate(row.definition)` in T006) then failed
      pydantic validation with `Input should be a valid dictionary ... input_type=str`, surfacing
      as a 500 on `GET /rules` — not caught by T002's own upgrade/downgrade verification, since
      that only checked the raw SQL text via `SELECT ... FROM rule`, which prints a JSON-shaped
      string either way and looks correct at a glance. Fixed by passing the plain Python dict
      directly (`"definition": {...}`, no `json.dumps`) and removing the now-unused `json` import.
- [X] T003 [P] Update `ops/erd/schema.mmd` to reflect `resource.sda_id`, `owner_identity_override`,
      and `tenant.owner_identity_pattern` — same PR as T002 per the `erd-current` CI gate
      (spec 002's T059 precedent: a schema-migration PR must touch `ops/erd/` in the same PR) —
      Principle I

**Checkpoint**: Schema exists; five rules are seeded; nothing yet reads or writes any of it.

---

## Phase 3: User Story 1 — Define what "compliant" means, as data an admin controls (Priority: P1)

**Goal**: Admin-editable tagging rules, seeded with the four mandatory tags, case-insensitive
matching, next-scan-effective edits.

**Independent Test**: With no scan yet run, edit a rule, then run a scan and confirm the resulting
findings reflect the new rule, not the old one.

### Tests for User Story 1

- [X] T004 [P] [US1] Write `backend/tests/integration/test_rules_api.py` — role gating (admin
      write, all-role read per FR-029/FR-030), the five seeded rules exist and match FR-003's exact
      required/not-required split, `extra="forbid"`-style rejection of unrecognized fields. **Moved
      from `tests/unit/` to `tests/integration/`** — same class of deviation already documented for
      T057 and others: verifying the seeded rules' actual content needs a genuinely migrated
      database, not a mocked session — S18, FR-001–FR-003, FR-029, FR-030
- [X] T005 [P] [US1] Write `backend/tests/unit/test_rule_versioning.py` — editing a rule creates a
      new version under the same key rather than mutating in place; `definition`'s three
      independent checks (required/allowed-values/format) each produce a distinct finding kind
      downstream (structural assertion here, full behavior in US3). Scoped to the Pydantic
      schema layer only (no DB) once T004 moved to integration/ and already covers the full
      DB-backed versioning behavior — no overlap between the two files — S18, FR-004, FR-005, FR-006

### Implementation for User Story 1

- [X] T006 [US1] Write `backend/app/api/routers/rules.py` — `GET /rules`, `POST /rules`,
      `PATCH /rules/{ruleKey}`, gated per FR-029 (admin write) / FR-030 (all-role read); PATCH
      creates a new `Rule` row under the same `key` with `version` incremented (research.md
      R-301) — S18, FR-001–FR-006
- [X] T007 [US1] Wire `rules` router into `backend/app/api/main.py`; regenerate
      `backend/openapi.generated.yaml` — S18, FR-048 (spec 001 contract discipline)

**Checkpoint**: Rules are readable and admin-editable via the API; case-insensitive matching and
next-scan timing are asserted at the unit level. Nothing evaluates a rule against a resource yet
(US3).

---

## Phase 4: User Story 2 — Group resources into the internal projects that actually own them (Priority: P1)

**Goal**: SDA registry with tag-value mapping, matching at scan time, a visible "No SDA" bucket,
overlap refusal on register/edit, and unrestricted removal that immediately reverts attached
resources (FR-010b).

**Independent Test**: Register one SDA, run a scan against an account with matching and
non-matching resources, confirm the split; remove the SDA and confirm its resources revert to "No
SDA" without a new scan.

### Tests for User Story 2

- [X] T008 [P] [US2] Write `backend/tests/integration/test_sdas_api.py` — role gating on all four
      operations (POST/PATCH/DELETE admin-only, GET all-role), request-shape validation. **Moved
      from `tests/unit/` to `tests/integration/`**, same precedent as T004: a 200-path role-gating
      assertion needs real rows to serialize. This file's `TestOverlapDetection` class also absorbs
      T009's scope (see T009's note below) — S18a, FR-007, FR-010b, FR-029, FR-030
- [X] T008a [P] [US2] Write `backend/tests/integration/test_sda_matching_and_reclassification.py`
      — Testcontainers PostgreSQL, the SDA registry's primary behavior, not just its edge cases: a
      resource whose tags satisfy a registered SDA's mapping attaches to it (FR-008, Acceptance
      Scenario US2.1); a resource matching no SDA lands in and stays visible in the "No SDA"
      bucket via `GET /sdas/unmatched-resources` (FR-009, SC-006); editing an existing SDA's
      mapping, or registering a new one, reclassifies previously-unmatched or
      differently-matched resources starting with the next scan — not immediately, and not
      requiring a separate trigger (FR-010, Acceptance Scenario US2.3, SC-007). Found missing by
      `/speckit-analyze` (finding E1, 2026-08-25): T009/T010 only ever covered the overlap-refusal
      and removal edge cases, never this behavior itself — S18a, FR-008, FR-009, FR-010, SC-006,
      SC-007
- [X] T009 [P] [US2] Write `backend/tests/integration/test_sda_overlap_detection.py` —
      Testcontainers PostgreSQL, research.md R-305's exact-intersection rule: identical mappings
      refused, and the subset case (`{team: platform}` vs. `{team: platform, env: prod}`) also
      refused, not just literal duplicates. **Folded into `test_sdas_api.py`'s
      `TestOverlapDetection` class** rather than a separate file — both need the same
      admin-authenticated `TestClient` fixture T008 already builds, and splitting it out would only
      duplicate that setup; also covers a case beyond the two named above: a shared key with a
      genuinely different value (`{team: platform}` vs. `{team: data}`) is correctly *not* refused
      — S18a, FR-010a
- [X] T010 [P] [US2] Write `backend/tests/integration/test_sda_removal_reverts_resources.py` —
      Testcontainers PostgreSQL, proves the `ON DELETE SET NULL` FK behavior directly: a resource
      attached to an SDA has `sda_id` become `NULL` the instant the SDA row is deleted, with no
      application code and no scan involved. **Real bug found while writing this test, not by
      inspection**: the first version asserted against `db.get(Resource, resource_id)` immediately
      after `db.delete(sda); db.commit()` and got the *old* `sda_id` back — SQLAlchemy's identity
      map serves the already-loaded Python object rather than re-querying, and has no way to know a
      database-level FK action (not ORM-tracked) changed the row. Fixed with `db.expire_all()`
      before the re-fetch — S18a, FR-010b

### Implementation for User Story 2

- [X] T011 [US2] Write `backend/app/governance/sda_matching.py` — tag-value mapping match (a
      resource matches when every key in an SDA's `tag_values` is present on the resource with
      exactly that value, FR-008), the overlap-detection check research.md R-305 defines (called
      from both SDA create and update, FR-010a), and `reclassify_account_resources` — the function
      Phase 7's compliance-validation worker will call once per finalized scan (research.md R-303),
      exercised directly by T008a in the meantime, the same "pure logic now, real trigger later"
      split Phase 5's validation module also follows — S18a, FR-008, FR-009, FR-010, FR-010a
- [X] T012 [US2] Write `backend/app/api/routers/sdas.py` — `GET /sdas`, `POST /sdas`,
      `PATCH /sdas/{sdaId}`, `DELETE /sdas/{sdaId}` (FR-010b: never refused for attached
      resources), `GET /sdas/unmatched-resources` (FR-009's "No SDA" visibility — this one
      endpoint is P1 even though the dedicated UI screen consuming it, FR-012, is P2) — S18a,
      FR-007–FR-010b. **Real gap found while implementing**: FastAPI asserts a 204 response can't
      declare a body-carrying `response_model` — `remove_sda` needed `response_model=None`
      explicit, not just a `-> None` return annotation. Also extended
      `tests/unit/test_no_registration_path.py`'s `/accounts`-only exemption to include `/sdas`:
      `registerSda`'s operationId legitimately matches that test's "register" fragment for the same
      reason `registerAccount` already does (registering a governance object, never a person's
      identity) — a spec-001-owned guard needing a narrow, justified extension for a case it didn't
      anticipate, the same class of change as `check_connector_boundary.py`'s extension in spec 002.

**Checkpoint**: SDAs are registerable, editable, and removable via the API; matching and overlap
refusal are proven against a real database. Resources aren't actually attached to SDAs yet — that
happens at scan time, wired in Phase 7 alongside validation.

---

## Phase 5: User Story 3 — See exactly which resources fail the standard, and know when they're fixed (Priority: P1)

**Goal**: Rule evaluation against top-level resources only, three distinct violation kinds,
dedup, auto-close, and a finding that survives a rule edit by following the rule's key
(research.md R-301) rather than being orphaned against a superseded version.

**Independent Test**: A resource missing a required tag gets a finding; fixing the tag and
re-scanning auto-closes it; editing the rule that produced it and re-scanning still finds and
closes the same finding row, not a new one.

### Tests for User Story 3

- [X] T013 [P] [US3] Write `backend/tests/unit/test_validation_engine.py` — the three violation
      kinds (missing/invalid-value/invalid-format) each produce a distinct finding, severity comes
      from `rule.definition.severity` (default `medium`), an uncovered/disabled rule produces no
      finding, a fixed tag auto-closes its finding on re-evaluation (SC-002), and validation
      MUST NOT run — must open, dedupe, or close nothing — against a scan recorded `failed`,
      only `succeeded`/`partial` (FR-017; found missing a dedicated assertion by
      `/speckit-analyze` finding E3, 2026-08-25) — S19, FR-004, FR-013–FR-017, SC-002
      **Done**: moved to `tests/integration/` (same precedent as T004/T008 — proving a finding
      actually opens a DB row needs a real database). Migration 0010 seeds 5 rules against the
      tenant, enabled — collided with test-created rule keys (`uq_rule_tenant_key_version`) and
      produced unwanted extra findings; fixed with a `_disable_seeded_rules()` helper and renamed
      test rule keys off the seeded set. The original "uncovered rule" half of the disabled-rule
      test was a misconception (no per-resource-type rule-coverage concept exists) and also
      exercised a bogus `definition`-JSON `enabled` key the app never reads — simplified to
      `test_a_disabled_rule_produces_no_finding` using the real `enabled` column.
- [X] T014 [P] [US3] Write `backend/tests/integration/test_finding_rule_version_repointing.py` —
      Testcontainers PostgreSQL, the decisive test for research.md R-301: open a finding under
      rule version 1, edit the rule to version 2, re-evaluate, confirm the **same finding row**
      (not a new one) now has `rule_id` pointing at version 2 and can auto-close under version 2's
      criteria (SC-002) — the specific correctness risk the Clarifications session (2026-08-25)
      exists to prevent — S19, FR-006, FR-015, FR-016, SC-002
      **Done**: this test caught a real bug — see T016.
- [X] T015 [P] [US3] Write `backend/tests/unit/test_parent_child_resolution.py` — a resource whose
      enrichment `detail` names an owning resource (EBS volume's `attached_instance_id`, EIP's
      `associated_instance_id`) gets `parent_resource_id` set to that resource; everything else
      keeps it `NULL`; validation evaluates only rows where `parent_resource_id IS NULL` — S19,
      FR-013, FR-013a
      **Done**: moved to `tests/integration/` (same precedent as T013). Fixed a variable-order
      mixup where a test destructured the `db` fixture's `(raw_wrapper, plain_session, tenant_id)`
      tuple wrong and called `raw.raw.execute(...)` on the plain `Session` (no `.raw` attribute).

### Implementation for User Story 3

- [X] T016 [US3] Write `backend/app/governance/validation.py` — resolves parent/child relationships
      onto `resource.parent_resource_id` (FR-013a), evaluates enabled rules against top-level
      resources only (FR-013), opens a finding per violation kind (FR-014) via the join-on-`key`
      lookup R-301 defines (not a `rule_id`-only lookup), re-points `rule_id`/`rule_version`/
      `severity` on re-evaluation rather than inserting a duplicate (FR-015), and auto-closes
      (FR-016) — gated to run only against `succeeded`/`partial` scans, never `failed` (FR-017,
      reusing spec 002's R-204 completion gating) — S19, FR-013–FR-017
      **Done**: T014's test caught a genuine FR-006 bug — `evaluate_resource()`'s auto-close
      branch resolved the violation but never re-pointed `rule_id`/`rule_version` onto the closing
      version, so a finding resolved under an edited rule kept showing the stale version that
      originally opened it. Fixed by re-pointing in the closing branch too, matching the
      still-violating branch.
- [X] T017 [US3] Write `backend/app/api/routers/findings.py` — `GET /findings` filterable by
      `accountId`/`resourceId`/`status`, all-role read — S19, FR-014, FR-030
      **Done**: no deviations.

**Checkpoint**: Given a resource and a rule, findings open, dedupe, and auto-close correctly,
including across a rule edit. Nothing computes a score yet (US4), and nothing calls this from a
real scan yet (wired in Phase 7).

---

## Phase 6: User Story 4 — See compliance at a glance, per account and per project (Priority: P1)

**Goal**: Compliance score per account and per SDA, well-defined at zero resources, matching a
hand count exactly.

**Independent Test**: On a small test account with a known, hand-countable mix, retrieve the score
and confirm it matches the manual count exactly.

### Tests for User Story 4

- [X] T018 [P] [US4] Write `backend/tests/unit/test_compliance_scoring.py` — score formula
      (compliant top-level resources ÷ total top-level resources) verified against a hand-counted
      fixture set so the assertion itself proves SC-003's "matches a manual tally" bar, not just
      that the code runs; per-SDA scoping; the zero-resources case returns a well-defined value
      rather than raising — S20, FR-018, FR-019a, SC-003
      **Done**: moved to `tests/integration/` (same precedent as T013 — "matches a manual tally"
      needs real `Resource`/`Finding` rows, not a mock). Combines a pure `TestComputeScore` class
      (the formula itself, incl. the zero-total case) with DB-backed hand-count tests covering:
      account-scoped mix, a resolved finding not counting against the score, a child resource
      excluded from both counts (T016's top-level-only definition), zero-resource account,
      per-SDA scoping (Acceptance Scenario US4.2), and a freshly registered SDA with no matched
      resources (Acceptance Scenario US4.3).

### Implementation for User Story 4

- [X] T019 [US4] Write `backend/app/governance/scoring.py` — compliant/total counts scoped to an
      account or to one SDA, `parent_resource_id IS NULL` as the top-level filter (same canonical
      definition T016 establishes) — S20, FR-018, FR-019a
      **Done**: no deviations. `compute_score()` is a pure function (score = compliant/total,
      1.0 when total is 0 per FR-019a and the contract's `ComplianceScore.score` doc); the two
      scoped query functions each fetch the scope's top-level resources, then count how many have
      no OPEN finding.
- [X] T020 [US4] Write `backend/app/api/routers/compliance.py` —
      `GET /accounts/{accountId}/compliance-score`, `GET /sdas/{sdaId}/compliance-score`,
      all-role read — S20, FR-018, FR-019, FR-030
      **Done**: no deviations. 404s if the account/SDA doesn't exist in the caller's tenant,
      matching `sdas.py`'s `_get_or_404` pattern.

**Checkpoint**: Scores are computable and API-retrievable, provably matching a hand count at the
unit level. Nothing has populated real findings from a real scan yet — that's Phase 7.

---

## Phase 7: User Story 5 — Know who to talk to about any resource (Priority: P1)

**Goal**: Direct-creator ownership attribution via a bulk CloudTrail sweep (research.md R-302),
wired into spec 002's scan lifecycle via SQS + Lambda workers (research.md R-303) rather than a
second orchestration mechanism — and this is also where Phase 4/5/6's governance logic actually
gets invoked from a real scan for the first time.

**Independent Test**: Create a resource in the AWS console, run a scan, confirm the recorded owner
is that console user with evidence citing the creation event.

### Tests for User Story 5

- [X] T021 [P] [US5] Write `backend/tests/unit/test_cloudtrail_sweep.py` — **research.md R-307
      VERIFY resolved here, before writing the rest of this file**: confirm empirically whether
      moto mocks `cloudtrail.lookup_events` with enough fidelity to auto-generate events from other
      mocked API calls (e.g. does `ec2.run_instances` produce a correlatable `RunInstances` event),
      or whether hand-built `lookup_events` response fixtures are needed instead (same fallback
      research.md R-209 already established for a different service). Either way, test the bulk
      sweep's pagination and event-to-resource correlation logic as actually written — S21, FR-020,
      research.md R-302, R-307
      **Done**: R-307 resolved definitively, not just partially like R-209 — moto raises
      `NotImplementedError: The lookup_events action has not been implemented` unconditionally, so
      every test in this file uses hand-built `lookup_events` fixtures (MagicMock client/paginator),
      with no partial-fidelity path at all. Covers pagination, creation-event-name filtering,
      resource correlation, earliest-event-wins on duplicates, and human/non-human (`IAMUser`/`Root`
      vs `AssumedRole`) principal classification parsed from the `CloudTrailEvent` JSON field.
- [X] T022 [P] [US5] Write `backend/tests/unit/test_ownership_attribution.py` — direct attribution
      for a human-principal creation event with evidence citing the event; a resource outside the
      90-day window (or with no determinable creator) stays queued unattributed rather than guessed;
      an existing attribution is never overwritten by a later, lower-confidence result (the guarded
      `UPDATE ... WHERE confidence <= :new` pattern data-model.md's `resource_owner` section
      defines) — S21, FR-020–FR-023
      **Done**: moved to `tests/integration/` (same precedent as T013/T018 — FR-023's guarded
      `ON CONFLICT ... WHERE` upsert is a real Postgres behavior, not something a mock proves). The
      guard direction needed care: `owner_confidence` is declared `(high, medium, low)` in migration
      0001, so Postgres's native enum ordinal has `high` sort first/smallest — "new is
      same-or-better than existing" is `EXCLUDED.confidence <= resource_owner.confidence`, verified
      by a dedicated test that a MEDIUM write cannot clobber an existing HIGH row, and that a
      same-confidence write updates in place.
- [X] T023 [US5] Extend `backend/connectors/aws.py` — one new method: a bulk, paginated
      `cloudtrail:lookup_events` sweep for one `(account, region, 90-day window)`, returning a map
      from resource identifier to `{principal, event_name, event_time, is_write}` (research.md
      R-302) — stays behind the FR-054 connector boundary spec 001 established, no new AWS-access
      path outside it — S21, FR-020
      **Done**: `sweep_cloudtrail_events()`. Creation events are recognized via a bounded,
      documented allow-list (`_CREATION_EVENT_NAMES`) tied 1:1 to the ten types
      `ENRICHMENT_FUNCTIONS` already treats as governance-critical (R-202) — FR-020's "for every
      resource" is satisfied by leaving anything outside that list's creator undetermined (FR-022),
      not by attempting exhaustive AWS service coverage. `is_human` is resolved here (not left to
      the caller) since only this function parses the raw `CloudTrailEvent` JSON for
      `userIdentity.type`; a human principal is `IAMUser` or `Root` for this spec's P1 scope.
- [X] T024 [US5] Write `backend/app/governance/ownership.py` — direct-creator attribution: correlate
      T023's event map against the scan's current resource set, write `ResourceOwner` rows with
      `confidence=high` and `evidence={"kind":"direct",...}` (FR-021), leave unmatched/out-of-window
      resources unattributed (FR-022), guard every write against overwriting a higher-confidence
      existing row (FR-023) — S21, FR-020–FR-023
      **Done**: `attribute_ownership()`/`_write_attribution()`, via `postgresql.insert(...)
      .on_conflict_do_update(..., where=...)`. Applies to every non-deleted resource, top-level or
      child — FR-020 carries no top-level-only qualifier the way FR-013/FR-018 do, confirmed by a
      dedicated test. `owner_email` stores the raw principal ARN/identity string directly for P1
      (quickstart.md V4's own documented behavior: "the raw identity, if email resolution hasn't
      run — P2"), not a resolved email — S23a's resolution chain is P2, out of scope here.
- [X] T025 [US5] Write `infra/modules/governance/main.tf` — two SQS queues + DLQs
      (`compliance-validation`, `ownership-attribution`, Standard not FIFO per research.md R-306),
      two Lambda workers (arm64, 1024MB, matching spec 002's scan-worker sizing), and one IAM
      policy extension: `cloudtrail:LookupEvents` added to spec 002's existing scanner role (not a
      new role) — wire into `infra/envs/{dev,prod}/main.tf` — S21, research.md R-303, R-306
      **Done**: no deviations. `cloudtrail:LookupEvents` added to `cross_account_template.yaml`'s
      `cloudpulse-scanner` role (cross-account mode) and directly to the ownership-worker's own
      runtime policy (same-account/local mode) — both paths this spec's two connection modes can
      take. `infra/modules/scan`'s worker IAM policy and Lambda environment also needed extending
      (new `sqs:SendMessage` permission + queue-URL env vars) since T026's enqueue call runs inside
      the existing scan-worker Lambda, not a new one — the governance module is declared before the
      scan module in both env files so its queue outputs can feed into it. `terraform fmt`/
      `validate` run locally against both dev and prod (no AWS credentials needed for validate).
- [X] T026 [US5] Extend `backend/app/scan/orchestrator.py`'s `finalize_scan` — after it sets the
      scan's final status and runs the deleted-marker sweep (spec 002's existing behavior,
      unchanged), enqueue one message per finalized scan to both new SQS queues (research.md
      R-303) — this is the one integration point connecting spec 002's scan lifecycle to this
      spec's governance pipeline; no second orchestration mechanism — S19, S20, S21, research.md
      R-303
      **Done**: `_enqueue_governance_messages()`, gated inside the same
      `if final_status is not ScanStatus.FAILED:` block as the deleted-marker sweep (matching
      Phase 5's own FR-017 gate — a failed scan starts no governance work). `app/scan/orchestrator.py`
      was already allow-listed in `check_connector_boundary.py` for its own Step Functions calls
      (platform infrastructure, not a scanned account); the new `boto3.client("sqs")` call is the
      same class of exception, no gate change needed. This is finalize_scan's *first* AWS call ever
      — broke all four pre-existing integration tests that call it directly, since none mocked SQS.
      Fixed with a `conftest.py` autouse fixture (`_noop_governance_enqueue`) that no-ops the
      enqueue by default for every integration test; T030's own file overrides it (same fixture
      name, nearer scope) to exercise the real call.
- [X] T027 [US5] Write `backend/handlers/ownership_attribution_worker_handler.py` — SQS-triggered
      Lambda entrypoint calling T023/T024 for the finalized scan's account/regions — S21, FR-020
      **Done**: no deviations. Sweeps every region in `account.scan_regions`, merges the per-region
      event maps, then calls `attribute_ownership` once for the whole account.
- [X] T028 [US5] Write `backend/handlers/compliance_validation_worker_handler.py` — SQS-triggered
      Lambda entrypoint calling T011's SDA matching, T016's validation, and T019's scoring, in that
      order, for the finalized scan's resources — S18a, S19, S20
      **Done**: found a genuine ordering bug while wiring this handler, fixed before it ever shipped
      — T016's `resolve_parent_child_relationships()` is called explicitly *before* T011's SDA
      matching (which this task's own stated order lists first), not after. SDA matching only
      evaluates `parent_resource_id IS NULL` resources; on a brand-new resource's very first scan,
      nothing had resolved `parent_resource_id` for it yet, so a genuine child resource would have
      been incorrectly SDA-matched as top-level had matching run first. `validate_account` still
      calls the same resolution again internally (idempotent, cheap) as part of its own contract.
      T019's scoring is logged for observability only — the score itself is never persisted
      (data-model.md: computed fresh on every `GET .../compliance-score` call).
- [X] T029 [US5] Write `backend/app/api/routers/ownership.py` — `GET /resources/{resourceId}/owner`,
      returns 200 with a null `owner` field for a queued-unattributed resource (not 404), all-role
      read — S21, FR-020, FR-030
      **Done**: no deviations.
- [X] T030 [P] [US5] Write `backend/tests/integration/test_governance_worker_wiring.py` — proves
      `finalize_scan` actually enqueues to both queues and both worker handlers actually process a
      finalized scan end-to-end (LocalStack SQS, or moto if LocalStack's SQS coverage proves
      thinner — same either-way-workable framing as spec 002's R-210) — S18a, S19, S20, S21,
      research.md R-303
      **Done**: LocalStack SQS proved sufficient (no moto fallback needed for this leg). Follows
      R-210's established split for this codebase exactly: real LocalStack SQS proves the *enqueue*
      reaches a real SQS-compatible API with the correct message shape; the worker handler
      *functions* are invoked directly in-process against real Testcontainers Postgres (R-210's own
      "Lambda-level tests" fallback, since a full LocalStack Lambda deployment was already found
      impractical there) — `app.core.db.get_engine` monkeypatched onto the test container
      (bypassing Secrets Manager, which no test container provides) and
      `connectors.aws.sweep_cloudtrail_events` monkeypatched (R-307: no moto coverage to route that
      leg through). One test proves the full chain: finalize_scan → both real queues receive the
      correct message → the compliance worker's SDA-match+validate produces the expected
      `sda_id`/`Finding` state → the ownership worker's sweep+attribute produces the expected
      `ResourceOwner` row.

**Checkpoint**: 🏁 **P1 functionally complete.** Every P1 user story is implemented and wired to a
real scan's completion. What remains before declaring P1 done is proving it against real AWS, not
mocked tests — that's Phase 8.

---

## Phase 8: P1 Completion — Role Matrix, Live Verification, Teardown

**Purpose**: The mocked-test suite proves the logic; this phase proves the system, against a real
AWS account, the way specs 001/002 did. Playbook §0.5.5: run `/speckit-analyze` a second time after
this phase, before starting Phase 9.

- [X] T031 Write `backend/tests/integration/test_role_matrix_governance.py` — the full role matrix
      across rules/SDAs/findings/scores/ownership (quickstart.md V7): admin-only write on
      rules/SDAs, all-role read everywhere, explicitly asserting a non-admin write attempt is
      refused rather than inferred from admin's own success — S18–S21, FR-029, FR-030
      **Done**: no deviations. 34 cells (6 view actions x 3 roles + 5 write actions x 3 roles),
      matching quickstart.md V7's table exactly (its P2 owner-identity-pattern/override row is
      deliberately excluded — that surface doesn't exist yet, Phase 9). View cells need real
      account/SDA/resource rows to return anything but an empty list — inserted directly via the
      ORM since the accounts router isn't mounted in this app (out of V7's scope). Also surfaced
      and fixed an unrelated environment issue: the shared `/private/tmp/cloudpulse_venv` this
      session's earlier phases used had been wiped by macOS's tmp-directory cleanup mid-session
      (all installed packages' `.py` sources gone, only empty package directories left) — rebuilt
      in the session scratchpad instead (`pip install --ignore-requires-python -e ".[dev]"`, the
      same override the original venv must have used, since this Mac has no Python 3.12 and
      `pyproject.toml` pins `==3.12.*`).
- [ ] T032 **Live-verification.** Deploy this spec's work to dev (flip `DEV_AUTO_DEPLOY` or
      dispatch `Deploy dev` manually, per spec 002's precedent), and walk quickstart.md V1–V4, V6,
      V7, V8 against the real primary AWS account — confirms SC-001–SC-004 and SC-006–SC-008
      against reality, not mocks. **V5 (fallback chain) is out of scope for this task** — it needs
      P2's T038/T039, which don't exist yet; live-verifying it is Phase 9's concern once P2 lands,
      not silently skipped forever — S18–S21, SC-001–SC-004, SC-006–SC-008
      **Deferred (2026-08-29)**: explicit user decision, same as spec 002's T053/T054 — not
      attempted and not abandoned. Cost estimated first (research.md R-306: this spec's own new
      resources round to under $0.01 for a verification session; the real cost is specs 001/002's
      existing dev footprint staying up, unchanged by this spec). User: revisit later, remind when
      needed — do not resurface unprompted.
- [ ] T033 **Teardown and cost sweep**, immediately following T032, never separated from it by
      other work: run the full playbook §0.5.3 sweep, plus this spec's own additions from
      research.md R-306 — confirm `aws sqs list-queues` shows neither new queue nor their DLQs, and
      confirm the two new Lambda workers' CloudWatch log groups are gone or have a retention policy
      set (not `retentionInDays: null`) — S18–S21, playbook §0.5.3
      **Deferred (2026-08-29)**: blocked on T032 — nothing to tear down since nothing was deployed.

**Checkpoint**: ⚠️ **P1 implemented and merged; live verification deferred by explicit user
decision (2026-08-29), same shape as spec 002's own T053/T054 outcome** — not attempted, not
abandoned. Every P1 story is implemented, tested against mocks, and role-matrix-verified; what's
missing is proof against real AWS. Revisit T032/T033 when the user raises it again.

---

## Phase 9: P2 — SDA Admin UI, Attribution Fallback, Owner Identity Resolution

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise a P1 path. If
this phase is dropped entirely, Phases 1–8 still satisfy every P1 success criterion (SC-005
excepted, per the Tier Summary above).

### User Story 6 — Manage projects and triage unmatched resources from a screen (Priority: P2)

- [X] T034 [P] [US6] **[P2]** Write `frontend/src/app/features/sdas/sdas-list.component.spec.ts`
      (or the project's established Playwright pattern for a P1-equivalent screen, per spec 002's
      US2 frontend tests) — create/edit/remove an SDA from the screen, confirm effect matches the
      API directly — S18b, FR-011
      **Done**: written as `frontend/e2e/sdas.spec.ts` — spec 002's own `accounts` feature turned
      out to have no dedicated frontend test at all (checked directly: no `.spec.ts` exists
      anywhere under `features/`), so "the established Playwright pattern" meant only
      `e2e/shell.spec.ts`'s a11y suite — this is the first *functional* Playwright test in the
      repo, not a pre-existing pattern reused. Found and fixed a genuine, pre-existing gap while
      writing it: neither `/sdas` nor spec 002's `/accounts` route could be reached at all locally
      or in CI — `authGuard` redirects to `/sign-in`, which was never implemented (confirmed:
      `NG04002: Cannot match any routes`), and no mock-auth mechanism existed. **Stopped and asked
      the user** rather than silently working around it; the user chose a minimal test-only auth
      bypass. Added `window.__CLOUDPULSE_CONFIG__.e2eMockRole` (api-config.ts) — the same
      deploy-time runtime-config seam `apiBaseUrl` already uses, seeded via an `APP_INITIALIZER` in
      `app.config.ts`, set only by a Playwright `page.addInitScript()` before app boot. Cannot
      grant real access (`authGuard`'s own docstring: "a usability control, not a security
      control") — every HTTP call the seeded session makes still needs a real or intercepted
      response. The backend is not running in this suite (`playwright.config.ts`'s `webServer`
      starts only the Angular dev server), so requests are intercepted and served from an in-memory
      fixture store matching the generated client's contract shapes exactly — this proves the
      contract-level half of "effect matches the API"; the real backend/database half is T032's
      live-verification concern, already deferred by explicit user decision. 6/6 tests pass;
      13/13 across the full e2e suite (no regression on `shell.spec.ts`'s a11y checks).
- [X] T035 [US6] **[P2]** Write `frontend/src/app/features/sdas/sdas-list.component.ts` — CRUD
      screen for SDAs and their tag-value mappings, equivalent in effect to FR-007–FR-010b's API
      surface — S18b, FR-011
      **Done**: no deviations. Mirrors `accounts-list.component.ts`'s established pattern exactly
      (standalone component, signals, role-guarded controls disabled not hidden, per spec 1's
      role-guard precedent). Tag-value mapping is edited as one "key=value" per line rather than a
      dynamic multi-row widget — the same minimal-input style `account-form.component.ts` already
      uses for its comma-separated region list.
- [X] T036 [US6] **[P2]** Write `frontend/src/app/features/sdas/no-sda-triage.component.ts` —
      triage view over `GET /sdas/unmatched-resources` (T012) — S18b, FR-012
      **Done**: no deviations. Extracted as its own component and embedded in
      `sdas-list.component.ts` (one route, two composed components) rather than a second nav item
      -- FR-012's own requirement is a triage *view*, not a separate top-level screen.
- [X] T037 [US6] **[P2]** Wire the `sdas` feature into `frontend/src/app/app.config.ts` routes;
      regenerate the OpenAPI-generated frontend API client for the new `/rules`/`/sdas`/`/findings`/
      `/compliance`/`/ownership` paths — S18b, FR-011
      **Done**: no deviations. The generated client was already current (regenerated after every
      earlier phase's router change); this task's own scope was route wiring only.

### User Story 7 — Attribute ownership even when a pipeline created the resource (Priority: P2)

- [X] T038 [P] [US7] **[P2]** Write `backend/tests/unit/test_attribution_fallback.py` — a pipeline/
      automation creator triggers the fallback path; a human modifier with ≥3 write events in the
      lookback window is attributed at reduced confidence with fallback-specific evidence; fewer
      than 3 events leaves the resource unattributed rather than a below-threshold guess — S22,
      FR-024–FR-026
      **Done**: moved to `tests/integration/`, same precedent as T022 — FR-023's guarded upsert
      underlies every write here too. Covers: automation-creator fallback to the most-frequent
      human modifier; below-threshold (<3) stays unattributed; most-frequent-wins when multiple
      humans qualify; non-human write events never count toward the threshold; direct attribution
      always takes priority over fallback when both apply.
- [X] T039 [US7] **[P2]** Extend `backend/app/governance/ownership.py` — when T024's direct-creator
      step finds an automation identity instead of a human, fall back to the most frequent human
      modifier meeting the ≥3-write-event threshold (FR-024/FR-025), else leave the resource
      unattributed (FR-026) — S22, FR-024–FR-026
      **Done**: `attribute_ownership()` gained an optional `write_events_by_resource` param;
      `connectors/aws.py` gained a sibling `sweep_write_events()` function (a second, independent
      `LookupEvents` pass rather than widening T023's own return shape — keeps the tested P1 sweep
      untouched, at the cost of one extra paginated call, immaterial at demo-scale event volume).
      Fallback confidence is MEDIUM, not LOW — a documented plan-level choice (data-model.md leaves
      the exact level to implementation sizing, only requiring it be lower than direct). Wired into
      `handlers/ownership_attribution_worker_handler.py`.

### User Story 8 — Resolve any attributed owner to a real email address (Priority: P2)

- [X] T040 [P] [US8] **[P2]** Write `backend/tests/unit/test_owner_identity_resolution.py` — the
      precedence chain: a syntactically valid `owner` tag wins outright; else the admin-configured
      pattern applied to the audit-trail identity; else the manual override table; a changed
      pattern takes effect immediately with no redeploy — S23a, FR-027, FR-028
      **Done**: moved to `tests/integration/` (same precedent as every other governance test this
      spec moved) — the chain reads real `Tenant.owner_identity_pattern` and
      `owner_identity_override` state. Also covers case-insensitive `owner`-tag lookup, matching
      FR-002's established convention, and "nothing resolves returns `None`" (the caller's
      fallback, not this chain's job).
- [X] T041 [US8] **[P2]** Write `backend/app/governance/identity_resolution.py` — the three-step
      resolution chain T040 tests — S23a, FR-027, FR-028
      **Done**: `resolve_owner_email()`. Wired into `app/governance/ownership.py`'s direct and
      fallback attribution paths — `owner_email` is now the resolved contact email when the chain
      produces one, falling back to the raw principal identity otherwise (quickstart.md V4's
      documented pre-P2 behavior, now also the genuine "nothing resolved" case). `evidence.principal`
      always stays the raw audit-trail identity regardless — the resolved email is a display
      convenience, not a replacement for the evidence trail.
- [X] T042 [US8] **[P2]** Extend `backend/app/api/routers/ownership.py` —
      `GET`/`PUT /owner-identity-pattern`, `GET`/`PUT /owner-identity-overrides`, admin write /
      all-role read — S23a, FR-027–FR-030
      **Done**: no deviations. Override writes upsert on `(tenant_id, principal_id)` via
      `ON CONFLICT DO UPDATE`, matching the table's own unique constraint. Role-matrix cells added
      to `test_role_matrix_governance.py` (quickstart.md V7's last row, previously excluded as
      "doesn't exist yet").

**Checkpoint**: P2 stretch scope complete; SC-005 now provable; quickstart.md V5 can be run live as
a follow-up to Phase 8's T032 if desired (not itself re-numbered as a new live-verify task — it
extends the same dev deployment T032/T033 already covered, redeployed if it was torn down).

---

## Final Phase: Polish & Cross-Cutting Concerns

- [ ] T043 [P] Update `backend/README.md` and `infra/README.md` to describe the new
      `app/governance/` and `infra/modules/governance/` ownership — Principle I
- [ ] T044 Re-run `/speckit-analyze` on spec 003 (playbook §8's second-run note) and resolve any
      finding before spec 004 begins — Governance

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → Phase 3+**: strictly sequential — Phase 2's migration is the schema every
  later phase's tests and code touch.
- **Phase 3 (US1) and Phase 4 (US2) are independent of each other** and may run in parallel
  (different files, different routers) — both are prerequisites for Phase 5 (US3 evaluates rules
  from Phase 3 against resources SDA-matched in Phase 4's logic, though SDA-matching itself is
  invoked from Phase 7, not Phase 5 — Phase 5 only needs Phase 3's rules to exist).
- **Phase 5 (US3) blocks Phase 6 (US4)**: scoring counts findings validation produces.
- **Phase 7 (US5) depends on Phases 3–6 all being merged**: it is the integration phase that wires
  every earlier governance module into a real scan's completion (T026–T030) — this is why it is
  last among the P1 stories despite US5 itself (spec.md) being independently describable.
- **T042a-style mid-implementation additions**: if Phase 7's live-worker wiring surfaces a gap
  Phases 3–6 didn't anticipate (the way spec 002's own T047 found a session-leak bug during
  implementation), add the task here before its fix PR, per this file's own Process Note.
- **T031/T032/T033 must stay adjacent**: do not let Phase 9 work begin between live-verification
  and teardown — spec 002's playbook §0.5.3 origin story is exactly this failure mode.

## Parallel Execution Example

Phase 3 (US1) and Phase 4 (US2)'s test tasks can all run together — five independent files, no
shared state:

```text
T004 [P] [US1] backend/tests/unit/test_rules_api.py
T005 [P] [US1] backend/tests/unit/test_rule_versioning.py
T008 [P] [US2] backend/tests/unit/test_sdas_api.py
T008a [P] [US2] backend/tests/integration/test_sda_matching_and_reclassification.py
T009 [P] [US2] backend/tests/integration/test_sda_overlap_detection.py
T010 [P] [US2] backend/tests/integration/test_sda_removal_reverts_resources.py
```

## Implementation Strategy

**MVP first**: Phases 1–3 (Setup, Foundational, US1) alone deliver a demonstrable "rules are data,
admin-editable, next-scan-effective" capability — the foundation, but not yet the demo's namesake
"governance signal." **Incremental delivery to a demoable P1**: Phases 1–7 in order is the
shortest path to every P1 acceptance scenario being exercisable; Phase 8 is what turns "exercisable
in CI" into "proven against real AWS." P2 (Phase 9) is additive polish afterward, never a
prerequisite for declaring the P1 demo path complete.
