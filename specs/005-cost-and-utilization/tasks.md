---

description: "Task list template for feature implementation"
---

# Tasks: Cost, Utilization, and Notifications

**Input**: Design documents from `/specs/005-cost-and-utilization/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml,
quickstart.md — all merged to `pods/pod73`.

**Process note** (per this task list's own generation instruction): if implementation surfaces a
fix this list didn't anticipate, add a new task for it in this file *before* opening that fix's
PR — `pr-task-reference` CI requires a task ID in the PR body regardless, but the task belongs
here for the same reason every other task does, not invented after the fact just to satisfy the
gate. Specs 002–004's own tasks.md files have several examples of this pattern (T016a, T042a,
T032a, T036a, T032a/b/c) if a model is useful.

## Tier Summary

**P1 (demo-critical, frozen)**: Phases 1–6, T001–T026. Completing these satisfies SC-001–SC-004
at the mocked-test level (CI) — spend visibility, day-0 owner notification, and the day-2/4
cadence with escalation flag. T025/T026 attempt live proof against the real AWS account, honestly
bounded by research.md R-511 (Cost Explorer and IAM have no VPC PrivateLink support at all;
funding a narrow SES endpoint was priced and declined) — every one of this spec's AWS-touching P1
capabilities stays mocked-only until R-407 is funded.

**P2 (stretch)**: Phases 7–10, T027–T049. Every P2 task is marked **[P2]** in its description.
Dropping all four P2 stories leaves every P1 story and SC-001–SC-004 intact — only SC-005–SC-008
and FR-015–FR-020 go with them. User Story 6 (utilization, T038–T041) is the one P2 capability
that makes no AWS call at all (research.md R-509) and is fully live-verifiable regardless of
R-407's status — its own live-verify/teardown pair lives in the Final Phase (T051/T052), separate
from P1's, because it's the only genuinely new thing to prove live once P2 exists.

## Phase 1: Setup

- [X] T001 [P] Scaffold three new empty directories mirroring `accounts/`/`sdas/`'s existing
      standalone-component layout: `frontend/src/app/features/{cost,utilization,iam-hygiene}/` —
      no logic yet, just the layout plan.md's Project Structure commits to.
      **Done.**
- [X] T002 [P] Scaffold `infra/modules/cost/` (empty directory) — the new Terraform module
      plan.md's Project Structure names; its four files (`main.tf`, `scheduler.tf`,
      `variables.tf`, `outputs.tf`) are populated incrementally as each story's own worker is
      built (T010, T016, T047), matching `governance`/`scan`'s own precedent of one module built
      up across several phases rather than scaffolded whole up front.
      **Done.**

**Checkpoint**: Directory layout exists; nothing yet imports from or deploys it.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Every story in this spec either writes a new table or extends `finding` — this is
genuinely shared schema, unlike specs where only one story touches the database (spec 004's own
precedent for *not* front-loading a single-story schema applies in reverse here: 5 of 7 stories
depend on this migration, so it belongs here, not in whichever story happens to run first).

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Write migration `backend/migrations/versions/0012_cost_utilization_and_notifications.py`
      plus the model/enum changes it codifies: four new enums (`finding_kind`,
      `notification_cadence_point`, `notification_outcome`, `iam_principal_type`) in
      `backend/app/models/enums.py`; `backend/app/models/core.py` gains three new tables
      (`spend_record`, `budget`, `notification`), one small new table (`iam_hygiene_flag`), and
      `finding` is extended additively — `resource_id`/`rule_id`/`rule_version` become nullable,
      new `kind` (default `tag_violation`)/`sda_id`/`escalated_at` columns, the
      `ck_finding_kind_shape` CHECK constraint, and the `uq_finding_open_overrun_per_sda` partial
      unique index (data-model.md, research.md R-508) — S24, S25, S39–S42, S54–S56
      Write `backend/tests/integration/test_finding_kind_constraint.py` alongside it: a
      `tag_violation` row with `sda_id` set is rejected; a `budget_overrun` row with `resource_id`
      set is rejected; the existing `uq_finding_open_per_resource_rule` index still refuses a
      second open tag-violation finding on the same resource/rule; a `budget_overrun` row's
      `resource_id`/`rule_id` being `NULL` does **not** collide with that index (confirms the
      schema note in data-model.md that a Postgres unique index never matches on `NULL`).
      **Done.** `EXPECTED_TABLES` in `test_migrations.py` extended with the four new tables.
      Also fixed a pre-existing test that now asserted something false:
      `test_tenant_scoping.py::test_finding_pins_the_rule_version` checked
      `rule_version`'s column-level `NOT NULL` — no longer true now that a `budget_overrun`
      finding has no rule at all — rewritten to check `ck_finding_kind_shape`'s text instead,
      which is where that guarantee actually lives now for a `tag_violation` finding. Full
      backend suite (594 tests), mypy, and ruff all clean after the fix.
- [X] T003a **Not anticipated by this task list — found while implementing T007.**
      `spend_record.service` was `NOT NULL`, but a whole-day gap row (FR-002a) has no
      per-service breakdown to report — the same "never guess" discipline `amount_usd` already
      followed, missing from this column. Worse: the single plain `UniqueConstraint(tenant_id,
      cloud_account_id, service, spend_date, sda_id)` silently allowed duplicate "No SDA" rows
      for the same account/service/day, since Postgres never treats two NULLs as equal for a
      plain constraint's purposes — a correction ingestion would have inserted a second row
      instead of updating the first. New migration
      `backend/migrations/versions/0013_spend_record_null_safe_uniqueness.py`: `service` becomes
      nullable, the plain constraint is replaced by three partial unique indexes (real SDA,
      "No SDA" bucket, and gap — each with its own conflict target), new CHECK constraint
      `ck_spend_record_amount_and_service_required_unless_gap`. Not an edit to the already-
      committed migration 0012 — a new one, never amend merged history — S39, FR-001, FR-002a

**Checkpoint**: Schema exists — every table this spec needs is real, but nothing yet reads or
writes any of it.

---

## Phase 3: User Story 1 — See where the money is actually going (Priority: P1)

**Goal**: Daily spend, ingested and reconciling within ±1%, surfaced on a cost dashboard with
drill-down (S39, S42, FR-001, FR-002, FR-002a, FR-003).

**Independent Test**: Let a day's spend ingest for a test account; confirm the dashboard's total
matches the cloud provider's own console within ±1%, and drill-down reaches a consistent resource
list (research.md R-512 — resource-level *attribution*, not a per-resource dollar figure).

### Tests for User Story 1

- [X] T004 [P] [US1] Write `backend/tests/unit/test_spend_ingestion.py` — the pure attribution/
      correction/gap logic: a Cost Explorer tag-group result maps to the correct `Sda` via
      `sda_matching.find_matching_sda` (reused, research.md R-505); a second ingestion for the
      same account/service/day/SDA updates the existing row rather than duplicating it; a
      still-missing day after retries writes an `is_gap = true` row with `amount_usd = NULL`,
      never a guessed or zeroed value — S39, FR-001, FR-002a
      **Done, scope split in two (found while implementing, not anticipated as written)**: only
      the genuinely pure pieces landed in this unit-test file —
      `app.governance.spend.resolve_sda_id` (extracted as its own pure function) and
      `connectors.aws._parse_cost_and_usage_response` (8 tests, no DB). The correction/gap
      behavior itself needs a real unique index to conflict against — not unit-testable — moved
      to a new integration test, T004a below, matching this project's own established
      unit/integration split (`compute_scan_deltas` is pure and unit-tested;
      `test_finding_kind_constraint.py` is exactly this pattern already for a different table).
- [X] T004a **Not anticipated by this task list.** Write
      `backend/tests/integration/test_spend_ingestion.py` — `ingest_spend_rows` against a real
      PostgreSQL: a gap is recorded when `rows=None`; a second gap for the same day doesn't
      duplicate; `rows=[]` (real zero-cost) is never treated as a gap; an untagged row lands in
      the "No SDA" bucket; a tagged row attributes to the matching SDA; a repeat ingestion
      corrects in place for both the "No SDA" bucket and a real SDA (T003a's own fix, proven
      end-to-end); the "No SDA" bucket and a real SDA never collide for the same service/day.
      8 tests, all pass — S39, FR-001, FR-002a
- [X] T005 [P] [US1] Write `backend/tests/integration/test_spend_api.py` — `GET /spend` (filtered
      by account/SDA/date range) and `GET /spend/summary` (org total, per-project breakdown,
      trend) against real ingested rows, including a gap day rendering as `amountUsd: null` in the
      trend array, not a missing point — S39, S42, FR-003
      **Done**, alongside T010's router (same-PR sequencing, matching this project's own
      precedent of a route and its integration test landing in the same commit). 6 tests, all
      pass — list filtering by account/SDA/`sdaId=none`, summary totals, per-project breakdown,
      and the gap-day-renders-as-null trend case.

### Implementation for User Story 1

- [X] T006 [US1] Extend `backend/connectors/aws.py` — `get_daily_spend(account, region, tag_key,
      day)` calling `ce:GetCostAndUsage` grouped by service and the platform's configured
      project-tag key, through the existing `_build_session` (same-account ambient identity or
      cross-account assumed role, unchanged pattern) — S39, research.md R-503
      **Done.** Also adds the pure `_parse_cost_and_usage_response` helper (T004) — Cost
      Explorer's own `"{tag_key}${value}"` group-key format, an untagged group's empty value
      after `$` correctly mapped to `None`, not `""`.
- [X] T007 [US1] New `backend/app/governance/spend.py` — upserts `SpendRecord` per (account,
      service, day, sda) via T004's tested attribution/correction logic, writes an `is_gap` row
      after retries are exhausted (FR-002a) — S39, FR-001, FR-002a
      **Done, one deliberate signature change from this task's original wording**: the function
      is `ingest_spend_rows(session, account, day, rows)` — receiving already-fetched rows,
      not calling `connectors.aws.get_daily_spend` itself. Matches
      `ownership_attribution_worker_handler.py`'s own established precedent exactly (the
      connector call and `ConnectorAccount` construction live in the *handler*, never delegated
      through `app/governance/`) — checked against that file directly before deviating, not
      guessed. Keeps this module free of any AWS-SDK-adjacent code at all, a stricter reading of
      the connector-boundary rule (Principle V) than the task's original wording implied. Also
      found and fixed a real bug live (not by inspection): `on_conflict_do_update`'s
      `index_where` must match the target partial index's predicate *textually*, not just
      logically — SQLAlchemy's `.is_(False)` renders `IS false`, the index itself was created
      with literal `= false`; Postgres refused to infer an arbiter index and every upsert failed
      until both were made to match verbatim.
- [X] T008 [US1] New `backend/handlers/cost_ingestion_worker_handler.py` — daily EventBridge
      entrypoint (`{"action": "trigger_daily"}` payload, no per-account knowledge, matching
      `scan_worker_handler.py`'s exact shape per research.md R-501): queries every registered
      account, calls T007 per account with a plain try/except per account (one account's failure
      doesn't block another's, logged not raised) — S39, research.md R-501
      **Done.** Also builds `ConnectorAccount` and runs the retry loop here (T007's note above)
      — matches `ownership_attribution_worker_handler.py`'s exact shape. Ingests "yesterday"
      (UTC), not "today" — Cost Explorer reports completed days only, stated explicitly in the
      function's own docstring rather than left implicit.
- [X] T009 [US1] New `infra/modules/cost/{main.tf,variables.tf,outputs.tf}` — the
      `cost-ingestion-worker` Lambda (arm64, 512MB, VPC-attached like every existing worker),
      its IAM role (`ce:GetCostAndUsage`, `sts:AssumeRole` on `cloudpulse-scanner` scoped
      identically to `ownership_attribution_worker`'s existing policy, `secretsmanager:
      GetSecretValue` for the DB credential and ExternalId secrets), and `infra/modules/cost/
      scheduler.tf`'s first rule (daily, invoking this Lambda) — wire `module "cost"` into
      `infra/envs/{dev,prod}/main.tf` alongside the existing `module "governance"`/`module
      "scan"` calls — S39, research.md R-503, R-510
      `terraform fmt -check -recursive infra/` and `terraform validate` (both envs) must pass.
      **Done.** `terraform fmt -check -recursive infra/` clean; `terraform validate -backend=false`
      passes for both envs and the module itself.
- [X] T010 [US1] New `backend/app/api/routers/spend.py` — `GET /spend`, `GET /spend/summary`
      (contracts/openapi.yaml's exact shape), `require_viewer`-gated per the spec's own visibility
      Assumption. Regenerate `backend/openapi.generated.yaml` and the frontend
      `spend.service.ts`/interface — S39, S42, FR-003
      **Done.** Both endpoints implemented and wired into `app/api/main.py`; mypy/ruff clean.
      `openapi.generated.yaml` regenerated (`/spend`, `/spend/summary` confirmed present). Frontend
      client regeneration initially failed silently (`npm run generate:api` needs a JVM; none was
      linked on this machine — `brew`'s `openjdk` was installed but not on `PATH`/`JAVA_HOME`).
      Ran it with `JAVA_HOME=$(brew --prefix openjdk)/libexec/openjdk.jdk/Contents/Home`; produced
      `spend.service.ts`/`spend.serviceInterface.ts` and the five `spend-*` model files cleanly.
- [X] T010a [US1] Fix `GET /spend`'s `sdaId` validation — a malformed value returned 500
      instead of 422 — S39, FR-003
      **Added retroactively** (same discipline as T003a), found during this phase's own
      self-review, not by a task description. `sdaId` is typed as a string rather than a UUID so
      the literal `"none"` sentinel can share the parameter — which means FastAPI never validates
      the UUID case, and `uuid.UUID("not-a-uuid")` raised a bare `ValueError`. There is no
      `ValueError` exception handler, so it reached the catch-all and surfaced as an unhandled
      500. Now rejected as a 422 `VALIDATION_FAILED` via the same `AppError` pattern
      `accounts.py` already uses, with `422` declared in the contract. Confirmed to be a real
      defect rather than a hypothetical: the new regression test fails `assert 500 == 422`
      against the pre-fix code and passes after.
- [X] T011 [P] [US1] New `frontend/src/app/features/cost/{cost.service.ts,
      cost-dashboard.component.ts}` — trend chart (`ng2-charts`, reused from spec 004), per-
      project table, drill-down to a resource list (R-512); wire the `/cost` route into
      `app.config.ts` — S39, S42, FR-003
      **Done.** `CostService` wraps the generated `SpendService`/`ResourcesService`
      (signal-based state, matching `OverviewService`'s established pattern). Drill-down calls
      `GET /resources?sdaId=...` per R-512 (resource-list membership, not a per-resource dollar
      figure -- Cost Explorer has no such dimension). Gap days render as a broken line via
      Chart.js's own default `spanGaps: false` on `null` points -- no extra config needed.
      `ng build --configuration development`, `tsc --noEmit`, and `ng lint` all clean.

**Checkpoint**: A day's spend can be ingested, reconciles within ±1%, and is visible on a real
dashboard page with working drill-down. SC-001–SC-002 provable at the mocked-test level.

---

## Phase 4: User Story 2 — A resource owner learns their resource has a compliance problem (Priority: P1)

**Goal**: The owner of a newly-opened finding gets an email that day, naming the resource and
violation, with a working deep link (S24, FR-004, FR-005, FR-010, FR-012, FR-013, FR-014).

**Independent Test**: Open a finding on a resource with a resolved owner email; confirm one email
arrives that day with the resource, violation, and a working deep link; confirm a finding with no
resolvable owner email sends nothing and is recorded as unnotifiable.

### Tests for User Story 2

- [X] T012 [P] [US2] Write `backend/tests/unit/test_notification_due.py` — the "what's due today"
      query: a finding opened today with no `Notification` row for `day_0` is due; a finding
      already carrying a `day_0` row (any outcome) is not due again; a finding whose owner email
      can't be resolved or has bounced (spec 003's bounce flagging) is due but resolves to
      `withheld_no_owner_email`/`withheld_bounced`, never `sent` — S24, FR-004, FR-010
      **Done.** Two placement notes, both recorded in the file's own docstring. (1) The
      "already attempted, so not due again" rule is a real `NOT EXISTS` against the
      `uq_notification_tenant_finding_cadence`-constrained table — there is nothing a stub
      session can prove about it — so it is asserted against a real PostgreSQL in T013
      instead. Same split, and the same stated reason, as `test_spend_ingestion.py`'s own
      docstring already records for this codebase. What stayed here is genuinely pure: the
      deep link, the email contents, and the per-finding outcome branch. (2)
      `withheld_bounced` is deliberately untested — nothing in the system can set it, per
      T017a; a test would have to assert a mechanism into existence.
- [X] T013 [P] [US2] Write `backend/tests/integration/test_day0_notification.py` — a real finding
      with a resolvable owner email produces one `sent` `Notification` row and one email call;
      the sent email's link resolves to `{frontend_url}/findings/{findingId}` — that specific
      finding's own ID, not a generic findings-list URL (FR-005); the email's from-address
      matches the one configured, fixed sending identity, asserted the same way across every
      test case in this file rather than left as an assumption (FR-014); two findings opening the
      same day for the same owner produce two distinct `Notification` rows and two separate email
      calls, never one bundled message (FR-012) — S24, FR-004, FR-005, FR-012, FR-013, FR-014
      **Done.** FR-014's from-address is asserted by the file's shared `_run` helper, which
      every test goes through, so a new test cannot forget it. FR-005's deep link is checked
      against *two* findings in one run, so a hardcoded or first-row ID fails rather than
      coincidentally passing. Also carries T012's due-query half (see T012's note).

### Implementation for User Story 2

- [X] T014 [US2] New `backend/app/governance/notifications.py` — `send_due_day0_notifications
      (session)`: T012's tested due-query, resolves each finding's owner email (spec 003's
      existing chain, unchanged), sends via SES with the deep link (`{frontend_url}/findings/
      {findingId}`, reusing spec 004's existing route shape) and the resource/violation content
      FR-004/FR-005 fix, writes one `Notification` row per attempt regardless of outcome — S24,
      FR-004, FR-005, FR-010, FR-012, FR-014
      **Done.** Three decisions worth recording. (1) The SES client is *not* imported here —
      the send is a `Callable` the handler passes in, the same boundary
      `ownership_attribution_worker_handler.py` set (Principle V), which is what makes every
      rule testable without mocking a cloud client. (2) FR-014's sending identity rides on the
      `NotificationEmail` itself rather than being filled in by the transport, so "every email
      leaves from the one configured identity" is assertable in a plain unit test. (3) A
      *transport* failure records no row on purpose, so the next daily pass retries it —
      FR-010's "never retried forever" is about an unnotifiable address, not a transient
      error. Owner email is read from spec 003's existing `resource_owner` row rather than
      re-running `resolve_owner_email` at send time, so the email cannot disagree with what
      the dashboard shows for the same finding. A 48-hour lookback bounds the query: without
      it the first deployment would email the owner of every finding specs 003/004 ever
      opened.
- [X] T015 [US2] New `backend/handlers/notification_worker_handler.py` — daily EventBridge
      entrypoint calling T014 (day-2/4/escalation logic joins this same handler in Phase 5,
      T021 — one daily pass, not three separate triggers) — S24, research.md R-501
      **Done.** `frontend_url` and `notification_sender_email` are validated here, at the
      point of use, rather than on the shared `Settings` model — that one model is used by
      every Lambda, and the API/scan/migration functions have no notification configuration
      at all, so making the fields required would stop those resolving settings.
- [X] T016 [US2] Extend `infra/modules/cost/{main.tf,scheduler.tf}` — the `notification-worker`
      Lambda (arm64, 512MB, VPC-attached, `ses:SendEmail` IAM permission, no PrivateLink endpoint
      per research.md R-504's declined decision) and its own daily EventBridge Scheduler rule —
      S24, research.md R-504, R-510
      `terraform fmt -check -recursive infra/` and `terraform validate` must pass.
      **Done**, both clean, dev and prod. `ses:SendEmail` is scoped to the one configured
      identity ARN rather than `*` (an unset sender falls back to `*` only because an
      empty-string ARN is a malformed policy document that would fail the whole apply — the
      worker itself refuses to run without the value). `frontend_url` is wired from
      `module.frontend.url`, the same CloudFront domain the API already takes as its single
      allowed CORS origin, so a deep link lands on the app the recipient actually uses. The
      scheduler role's invoke policy gained the new function alongside the existing one
      rather than getting a second role.
- [X] T017 [US2] New `backend/app/api/routers/findings.py` extension — `GET /findings/
      {findingId}/notifications` (FR-013's admin-auditable trail), `require_viewer`-gated.
      Regenerate `backend/openapi.generated.yaml` — S24, FR-013
      **Done.** Contract regenerated. A finding with no attempts recorded is a normal 200 with
      an empty list — only a missing finding is a 404, the same distinction
      `getFindingSuggestion` already draws. Endpoint tests live in
      `tests/integration/test_finding_acknowledgment.py`, which already owns this router's
      API-level fixtures, rather than in a second near-identical harness.

- [X] T014a [US2] Tenant-filter the day-0 due query's `NOT EXISTS` subquery in
      `backend/app/governance/notifications.py`. Found in self-review of T014: the correlated
      subquery over `notification` was built with a bare `select()` rather than through
      `session.scoped`, so a tenant-scoped model was being queried without a tenant filter.
      Not a live leak — a finding's notifications can only belong to that finding's own
      tenant — but FR-030's rule is that a tenant-scoped model is never queried unscoped, and
      a subquery is still a query. Added retroactively per this file's Process Note rather
      than folded in silently — S24, FR-030

- [ ] T017a [US2] **BLOCKED — FR-010's bounce clause has no mechanism to build on.** Spec.md's
      FR-010 and its Edge Case both cite "spec 003's bounce flagging" as an existing feature to
      integrate with. It does not exist. Verified by grep across the whole repository: zero
      mentions of bounce/undeliverable/deliverability in `specs/003-*/` (spec, plan, or tasks),
      and no deliverability column or table anywhere in the schema — not on `resource_owner`,
      `owner_identity_override`, or `tenant`. `OwnerConfidence` is about attribution confidence,
      not deliverability. The only artifacts are spec 005's own `NotificationOutcome
      .WITHHELD_BOUNCED` enum value and migration 0012 that created it, so **nothing can ever
      set that outcome today**.
      FR-010's first clause ("owner email cannot be resolved") is fully implemented in T014 via
      the existing `resolve_owner_email` chain, so the P1 demo path is unaffected. Building the
      second clause means real unplanned scope — an SES configuration set, an SNS topic and
      bounce-event handler, a suppression table, and a migration — and it is not meaningfully
      testable end-to-end anyway while SES itself is unreachable from the VPC (R-504's declined
      funding). Deliberately deferred rather than faked: a hardcoded `False` "has this bounced"
      predicate would make the requirement look satisfied while changing nothing.
      **Needs a decision** (not this task list's to make): either fund the R-504/R-407 networking
      gap and build real bounce handling as its own spec-level scope, or amend FR-010 to drop the
      bounce clause and remove the unreachable enum value.

**Checkpoint**: A newly-opened finding with a resolvable owner email is emailed the same day, with
a working deep link, and every attempt (sent or withheld) is auditable. SC-003 provable at the
mocked-test level — with FR-010's bounce clause explicitly excluded per T017a.

---

## Phase 5: User Story 3 — Reminders keep pressure on an unresolved finding, then flag it for attention (Priority: P1)

**Goal**: Day-2/4 reminders that stop the moment a finding leaves the open state, and an
escalated flag (visibility only) for a finding still open after day 4 (S25, FR-006–FR-009,
FR-011).

**Independent Test**: Clock-forward a finding through day 2 and day 4 while it stays open,
confirming both reminders fire; confirm no reminder fires for a finding acknowledged/resolved/
suppressed before its scheduled send; confirm a finding still open after day 4 is visible as
escalated, and that acknowledging it afterward clears the flag.

### Tests for User Story 3

- [ ] T018 [P] [US3] Write `backend/tests/unit/test_notification_cadence.py` — day-2/day-4 due
      logic mirrors T012's day-0 shape; a finding acknowledged/resolved/suppressed before a
      reminder's scheduled send is not due (FR-007); a finding that reopens after resolution gets
      its own independent `day_0`/`day_2`/`day_4` rows, unaffected by its prior occurrence's
      `Notification` rows (FR-011, since a reopened finding is a fresh `Finding.id` per spec
      003's own re-open semantics) — S25, FR-006, FR-007, FR-011
- [ ] T019 [P] [US3] Write `backend/tests/integration/test_escalation_flag.py` — a finding still
      open after its `day_4` reminder sends gets `escalated_at` set; `GET /findings/{findingId}`
      reflects it; acknowledging the finding afterward clears `escalated_at` on the next read —
      S25, FR-008, FR-009

### Implementation for User Story 3

- [ ] T020 [US3] Extend `backend/app/governance/notifications.py` — `send_due_reminders(session)`
      (day-2/day-4, T018's tested logic) and `flag_stale_escalations(session)` (sets
      `escalated_at` the first time a still-open finding's `day_4` row is written) — S25,
      FR-006–FR-009, FR-011
- [ ] T021 [US3] Extend `backend/handlers/notification_worker_handler.py` — one daily pass now
      calls T014's day-0 logic, T020's reminder logic, and T020's escalation-flag logic together,
      in that order, per research.md R-501's "one worker queries what's due" design — S25,
      research.md R-501
- [ ] T022 [US3] Extend `backend/app/api/routers/findings.py` — the `Finding` response model
      gains `escalatedAt` (optional date-time, non-null exactly while FR-008/FR-009's escalated
      state is active). Regenerate `backend/openapi.generated.yaml` and the frontend client —
      S25, FR-009
- [ ] T023 [P] [US3] Extend `frontend/src/app/features/findings/findings-workbench.component.ts`
      — an "Escalated" badge, visually distinct from open-and-in-cadence and from acknowledged
      (FR-009) — S25, FR-009

**Checkpoint**: 🏁 **P1 functionally complete.** Every P1 user story is implemented. What remains
is proving it against reality (Phase 6) — SC-001–SC-004 are provable at the mocked-test level
now.

---

## Phase 6: P1 Completion — Role Matrix, Live Verification, Teardown

**Purpose**: The mocked-test suite proves the logic; this phase proves the system, against a real
AWS account, the way specs 001–004 did — honestly bounded this time by a constraint already known
before the attempt (research.md R-511), not discovered mid-attempt the way spec 002/003's own
first tries were.

- [ ] T024 Write `backend/tests/integration/test_role_matrix_cost_and_notifications.py` — the
      full role matrix across this spec's P1 read surfaces (`GET /spend`, `GET /spend/summary`,
      `GET /findings/{findingId}/notifications`): all three roles can read (spec 003/004's
      established "governance data is visible to every role" pattern, no write endpoint exists
      in P1 scope to test refusal against — noted explicitly, not silently assumed) — S24, S25,
      S39, S42, FR-003, FR-013
- [ ] T025 **Live-verification.** Deploy this spec's P1 work to dev (dispatch `Deploy dev`
      manually, per specs 002–004's precedent). **Before attempting any AWS-call-dependent
      scenario, re-confirm research.md R-511's status has not changed** — Cost Explorer and IAM
      have no VPC PrivateLink support at all (a platform limitation, not a funding gap that could
      have quietly resolved itself), and the narrow SES endpoint (research.md R-504) was priced
      and explicitly declined. Unless a new signal from the user has arrived since this task was
      written, do not re-attempt either call blind — confirm the deploy itself succeeds (health
      check, version match) and that no existing spec 001–004 flow regressed, and record
      SC-001–SC-004 as proven at the mocked-test level only, the same honest-outcome pattern
      specs 002/003/004 all landed on for their own R-407-bounded stories — S24, S25, S39, S42,
      SC-001–SC-004
- [ ] T026 **Teardown and cost sweep**, immediately following T025, never separated from it by
      other work: run the full playbook §0.5.3 sweep, extended per research.md R-510 to confirm
      `cost-ingestion-worker` and `notification-worker` (their Lambdas, EventBridge Scheduler
      rules, and CloudWatch log groups) are gone — S24, S25, S39, S42, playbook §0.5.3

**Checkpoint**: 🏁 **P1 complete at the mocked-test level (CI); live-verification (T025/T026)
honestly bounded by research.md R-511, not silently skipped.**

---

## Phase 7: User Story 4 — A new project gets a spending guardrail without anyone asking for one (Priority: P2)

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise the P1 path.
Dropping this phase (and Phases 8–10) leaves Phases 1–6 fully satisfying SC-001–SC-004.

**Goal**: A budget exists for every project the moment it's registered, with 80%/100% thresholds
(S40, FR-015).

**Independent Test**: Register a new project/SDA; confirm a budget already exists for it with the
correct thresholds, created synchronously (research.md R-502), not on any later schedule.

### Tests for User Story 4

- [ ] T027 [P] [US4] **[P2]** Write `backend/tests/unit/test_budget_creation.py` — a `Budget` row
      is created with the fixed 80%/100% actual-and-forecast thresholds and no crossed-timestamps
      set — S40, FR-015
- [ ] T028 [P] [US4] **[P2]** Write `backend/tests/integration/test_sda_registration_creates_
      budget.py` — `POST /sdas` (spec 003's existing endpoint) produces exactly one `Budget` row
      per SDA, in the same transaction as the SDA itself — S40, FR-015, research.md R-502

### Implementation for User Story 4

- [ ] T029 [US4] **[P2]** Extend `backend/app/api/routers/sdas.py` — `POST /sdas` creates the
      `Budget` row synchronously, inside the existing registration transaction (research.md
      R-502) — S40, FR-015
- [ ] T030 [US4] **[P2]** New `backend/app/api/routers/budgets.py` — `GET /budgets`,
      `require_viewer`-gated. Regenerate `backend/openapi.generated.yaml` and the frontend
      client — S40, FR-015
- [ ] T031 [P] [US4] **[P2]** Extend `frontend/src/app/features/cost/{cost.service.ts,
      cost-dashboard.component.ts}` — a budget row per project (amount, 80%/100% crossed state)
      alongside the existing spend table — S40, FR-015

**Checkpoint**: Every registered project has a budget with visible threshold state. SC-005
provable at the mocked-test level.

---

## Phase 8: User Story 5 — An overrun budget becomes a finding, not a surprise at month's end (Priority: P2)

**⚠️ P2 — STRETCH ONLY.** Depends on Phase 7 (a `Budget` must exist), Phase 3 (the threshold
check runs inside `cost_ingestion_worker_handler.py`, created there), and Phases 4–5 (this
story's finding is notified via the same machinery, unchanged).

**Goal**: Actual spend crossing 100% of budget opens a finding in the existing pipeline, notified
and resolved the same way any other finding is (S41, FR-016, FR-017).

**Independent Test**: Push a test project's spend past its 100% threshold; confirm a finding
opens with `kind: "budget_overrun"`, is notified, and resolves when spend drops back under
threshold.

### Tests for User Story 5

- [ ] T032 [P] [US5] **[P2]** Write `backend/tests/unit/test_budget_thresholds.py` — the
      80%/100% actual-crossing detection; the forecast calculation (research.md R-506's simple
      7-day-average × days-remaining trend, not a second Cost Explorer call); only actual-100%
      crossing (not forecast-100%, not either 80%) returns "open a finding" (research.md R-507)
      — S41, FR-015, FR-016
- [ ] T033 [P] [US5] **[P2]** Write `backend/tests/integration/test_budget_overrun_finding.py` —
      crossing actual-100% opens a `kind: "budget_overrun"` finding attached to the SDA (not a
      resource); it is notified exactly as User Story 2 describes; it resolves when spend drops
      back under threshold; a second overrun for the same SDA while one is already open does not
      create a duplicate (the new partial unique index, T003) — S41, FR-016, FR-017

### Implementation for User Story 5

- [ ] T034 [US5] **[P2]** New `backend/app/governance/budgets.py` — `check_thresholds(session,
      sda, spend_record)`: T032's tested actual/forecast crossing detection, updates `Budget`'s
      four crossed-timestamp fields, opens/resolves the `budget_overrun` `Finding` per
      research.md R-507's "actual-100% only" rule — S41, FR-015–FR-017
- [ ] T035 [US5] **[P2]** Extend `backend/handlers/cost_ingestion_worker_handler.py` — call
      T034's `check_thresholds` immediately after each account's spend ingestion, same
      transaction (research.md R-505 — no separate worker, no ordering race) — S41, FR-016,
      research.md R-505
- [ ] T036 [US5] **[P2]** Extend `backend/app/api/routers/findings.py` — the `Finding` response
      model gains `kind` (required) and `sda` (optional, populated for `budget_overrun`); the
      list/detail queries change their `JOIN Resource` to a `LEFT JOIN` and add an equivalent
      `Sda` join (research.md R-508). Regenerate `backend/openapi.generated.yaml` and the
      frontend client — S41, FR-016, research.md R-508
- [ ] T037 [P] [US5] **[P2]** Extend `frontend/src/app/features/findings/findings-workbench.
      component.ts` — a `budget_overrun` finding renders its SDA name in place of a resource
      link, distinguishable at a glance from a tag-violation finding — S41, FR-016

**Checkpoint**: A budget overrun is visible, notified, and resolvable exactly like any other
finding. SC-006 provable at the mocked-test level.

---

## Phase 9: User Story 6 — See how well a sandbox account or project is actually being used (Priority: P2)

**⚠️ P2 — STRETCH ONLY.** Independent of every other phase in this spec — makes no AWS call at
all (research.md R-509), depends only on spec 002's already-persisted `resource.state`.

**Goal**: A documented utilization percentage per account/project, with three-click drill-down
(S54, S55, FR-018).

**Independent Test**: Compute utilization for a test account with a known active/idle resource
mix; confirm the API's number matches a hand calculation using the same documented formula.

### Tests for User Story 6

- [ ] T038 [P] [US6] **[P2]** Write `backend/tests/unit/test_utilization.py` — the active/idle
      state-string classification (a data dict, not an `if/elif` chain, per research.md R-509);
      resources with `state IS NULL` excluded from both numerator and denominator; an account
      with zero provisioned (state-known) resources returns the explicit "not enough data" state,
      not a divide-by-zero or a misleading 0%/100% — S54, S55, FR-018

### Implementation for User Story 6

- [ ] T039 [US6] **[P2]** New `backend/app/governance/utilization.py` — the known-idle/known-
      active state-string sets (data, matching `coverage_definitions.json`'s existing precedent)
      and `compute_utilization(session, account_id, sda_id=None)` (live aggregate query, T038's
      tested classification and edge cases) — S54, S55, FR-018, research.md R-509
- [ ] T040 [US6] **[P2]** New `backend/app/api/routers/utilization.py` — `GET /utilization`,
      `require_viewer`-gated. Regenerate `backend/openapi.generated.yaml` and the frontend
      client — S54, S55, FR-018
- [ ] T041 [P] [US6] **[P2]** New `frontend/src/app/features/utilization/{utilization.service.ts,
      utilization.component.ts}` — account → project → resource drill-down in ≤3 clicks; wire the
      `/utilization` route into `app.config.ts` — S54, S55, FR-018

**Checkpoint**: Utilization is computed and drillable, with zero new AWS dependency. SC-007
provable — and, uniquely among this spec's P2 stories, provable **live**, not just at the
mocked-test level (research.md R-509/R-511; see T051).

---

## Phase 10: User Story 7 — Find unused IAM roles and keys without risking a false flag (Priority: P2)

**⚠️ P2 — STRETCH ONLY.** Independent of every other phase in this spec.

**Goal**: Flag-only, never-auto-delete recommendations for genuinely unused IAM roles/users/keys,
zero false flags on active ones (S56, FR-019, FR-020).

**Independent Test**: Run the analysis against a test account with both an active and a
genuinely-unused role; confirm only the unused one is flagged.

### Tests for User Story 7

- [ ] T042 [P] [US7] **[P2]** Write `backend/tests/unit/test_iam_hygiene.py` — the pure
      classification logic: a role/user/key with no recent last-used evidence is flagged; one
      with recent activity is never flagged, regardless of how the evidence is shaped — S56,
      FR-019, FR-020
- [ ] T043 [P] [US7] **[P2]** Write `backend/tests/integration/test_iam_hygiene_api.py` —
      `GET /iam-hygiene` returns active flags with evidence; re-running the analysis after a
      flagged principal becomes active again clears it (`cleared_at` set), and re-running after
      it goes unused again re-flags it with a fresh `flagged_at` — S56, FR-019, FR-020

### Implementation for User Story 7

- [ ] T044 [US7] **[P2]** Extend `backend/connectors/aws.py` — `iam_unused_analysis(account)`:
      `iam:ListRoles`/`GetRole`/`ListUsers`/`ListAccessKeys`/`GetAccessKeyLastUsed` through the
      existing `_build_session`, returning raw last-used data per principal — S56, FR-019,
      research.md R-503
- [ ] T045 [US7] **[P2]** New `backend/app/governance/iam_hygiene.py` — T042's tested
      classification logic, plus the clear/re-flag upsert against `iam_hygiene_flag`'s partial
      unique index (T003) — S56, FR-019, FR-020
- [ ] T046 [US7] **[P2]** New `backend/handlers/iam_hygiene_worker_handler.py` — **weekly**
      EventBridge entrypoint (not daily — research.md R-510: IAM last-used data changes slowly,
      weekly is the cheapest cadence that still meets the flag-only bar) — S56, research.md R-510
- [ ] T047 [US7] **[P2]** Extend `infra/modules/cost/{main.tf,scheduler.tf}` — the
      `iam-hygiene-worker` Lambda (arm64, 512MB, VPC-attached, `sts:AssumeRole` on
      `cloudpulse-scanner` reused, the `iam:*` read actions T044 needs) and its weekly
      EventBridge Scheduler rule — S56, research.md R-503, R-510
      `terraform fmt -check -recursive infra/` and `terraform validate` must pass.
- [ ] T048 [US7] **[P2]** New `backend/app/api/routers/iam_hygiene.py` — `GET /iam-hygiene`,
      `require_viewer`-gated. Regenerate `backend/openapi.generated.yaml` and the frontend
      client — S56, FR-019, FR-020
- [ ] T049 [P] [US7] **[P2]** New `frontend/src/app/features/iam-hygiene/{iam-hygiene.service.ts,
      iam-hygiene.component.ts}` — flag list with evidence detail; wire the `/iam-hygiene` route
      into `app.config.ts` — S56, FR-019, FR-020

**Checkpoint**: P2 stretch scope complete; SC-005–SC-008 now provable (SC-007 also live —
T051/T052).

---

## Final Phase: Polish & Cross-Cutting Concerns

- [ ] T050 [P] Update `backend/README.md`, `frontend/src/app/features/README.md`, and
      `infra/README.md` — describe this spec's new `app/governance/{spend,budgets,notifications,
      utilization,iam_hygiene}.py`, the three new worker handlers, `infra/modules/cost/`, and the
      five new frontend feature areas — Principle I
- [ ] T051 **Live-verify User Story 6 (utilization) only** — the one capability this spec adds
      that makes no AWS call at all (research.md R-509) and is therefore fully live-verifiable
      regardless of R-407/R-511's status. Deploy (or reuse T025's dev deployment if still up),
      run quickstart.md's V6 against a real scanned account with a known active/idle resource
      mix, confirm SC-007 — S54, S55, SC-007
- [ ] T052 **Teardown and cost sweep**, immediately following T051, never separated from it by
      other work: full playbook §0.5.3 sweep, confirming every Lambda/schedule/log-group this
      spec added across all three workers is gone — playbook §0.5.3
- [ ] T053 Re-run `/speckit-analyze` on spec 005 (playbook §8's second-run note) and resolve any
      finding before spec 6 begins — Governance

**Checkpoint**: 🏁 **P1 and P2 complete at the mocked-test level (CI). Utilization (User Story 6)
additionally proven live. Every other AWS-touching capability remains honestly bounded by
research.md R-511 until R-407 is funded.**

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → Phase 3+**: strictly sequential — Phase 2's schema migration is what
  makes every later phase's persistence possible at all.
- **Phase 3 (US1) has no dependency on any other story** — it's the foundation the rest of this
  spec's P2 scope (budgets, overrun findings) builds on, but is independently valuable and
  independently testable on its own.
- **Phases 4 and 5 (US2, US3) share one worker** (`notification-worker`) and are sequenced
  together deliberately — US3's cadence logic extends the exact handler US2's day-0 logic first
  stood up, not a second, parallel entrypoint.
- **Phase 6 depends on Phases 3–5 all being merged**: it is the integration-proof phase, the same
  role tag compliance and ownership's own Phase 8, and governance dashboard's own Phase 7, played
  there.
- **Phase 7 (US4) depends on nothing but Phase 2's schema.** Phase 8 (US5) depends on Phase 7 (a
  `Budget` must exist), on Phase 3/US1 (T035 extends `cost_ingestion_worker_handler.py`, created
  in T008 — the threshold check runs inside that same daily job, research.md R-505), and reuses
  Phases 4–5's notification machinery unchanged. Phases 9 (US6) and 10 (US7) are independent of
  every other phase and of each other — different files, different workers, no shared state.
- **`infra/modules/cost/{main.tf,scheduler.tf}` is a second shared-file lineage**, beyond
  `notification_worker_handler.py`'s: T009 (Phase 3) creates it, T016 (Phase 4) and T047
  (Phase 10) each append their own worker's resources to it. Sequential, never concurrent — no
  two of those three tasks are in flight at once — but each of T016/T047 should pull the latest
  trunk before editing rather than assume the file still looks like it did when its phase's own
  branch was cut.
- **T0XX-style mid-implementation additions**: if any phase's work surfaces a gap this list
  didn't anticipate, add the task here before its fix PR, per this file's own Process Note.
- **T025/T026 must stay adjacent**: do not let Phase 7 work begin between live-verification and
  teardown. **T051/T052 must stay adjacent** for the same reason, once P2 exists.

## Parallel Execution Example

Each story's two test files can run together — independent files, no shared state:

```text
T004 [P] [US1] backend/tests/unit/test_spend_ingestion.py
T005 [P] [US1] backend/tests/integration/test_spend_api.py
```

Phases 9 and 10 (US6, US7) can be implemented in parallel by two different branches once Phase 6
merges — neither touches a file the other does.

## Implementation Strategy

**MVP first**: Phases 1–6 (Setup, Foundational, US1, US2, US3, P1 Completion) alone deliver the
full P1 demo path — spend visibility, day-0 notification, and cadence/escalation — independently
of any P2 story. **Incremental delivery to a demoable P1**: Phases 1–6 in order is the shortest
path to every P1 acceptance scenario being exercisable; Phase 6 is what turns "exercisable in CI"
into "proven against real AWS" — honestly bounded by research.md R-511 from the start, not
discovered mid-attempt. P2 (Phases 7–10) is additive polish afterward, never a prerequisite for
declaring the P1 demo path complete; User Story 6's own live-verification (T051/T052) is the one
piece of P2 work whose live-provability doesn't wait on R-407 at all.
