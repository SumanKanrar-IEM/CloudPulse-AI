---

description: "Task list template for feature implementation"
---

# Tasks: Governance Dashboard

**Input**: Design documents from `/specs/004-governance-dashboard/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml,
quickstart.md — all merged to `pods/pod73`.

**Process note** (per this task list's own generation instruction): if implementation surfaces a
fix this list didn't anticipate, add a new task for it in this file *before* opening that fix's
PR — `pr-task-reference` CI requires a task ID in the PR body regardless, but the task belongs
here for the same reason every other task does, not invented after the fact just to satisfy the
gate. Specs 002/003's own tasks.md have several examples of this pattern (T016a, T042a, T032a) if
a model is useful.

## Tier Summary

**P1 (demo-critical, frozen)**: Phases 1–7, T001–T033. Completing these satisfies SC-001–SC-007
at the mocked-test level (CI), with T032/T033 attempting live proof against a real AWS account.
SC-008 needs P2's User Story 5 to exist at all — the one success criterion honestly tied to P2
completion, per spec.md's own "Tier dependency" note and plan.md's Constitution Check table.

**P2 (stretch)**: Phases 8–9, T034–T041. Every P2 task is marked **[P2]** in its description.
Dropping both phases entirely leaves every P1 story and SC-001–SC-007 intact — only SC-008 and
FR-021–FR-026 go with it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US5, matching spec.md)
- Every task cites its backlog S-number and spec requirement(s)

---

## Phase 1: Setup

- [ ] T001 Scaffold four new empty directories mirroring `accounts/`/`sdas/`'s existing
      standalone-component layout: `frontend/src/app/features/{overview,inventory,findings,scans}/`
      — no logic yet, just the layout plan.md's Project Structure commits to.

**Checkpoint**: Directory layout exists; nothing yet imports from or deploys it.

---

## Phase 2: Foundational (blocking prerequisites for every user story)

**Purpose**: Every screen this spec adds calls the platform API once deployed; none of them work
live without research.md R-401's runtime-config fix — this is genuinely foundational, not tied to
any one story, unlike this spec's schema (which only User Story 4 needs, and stays in that story's
own phase per honest dependency ordering rather than being front-loaded here for convenience).

- [ ] T002 [P] Extend `infra/envs/{dev,prod}/outputs.tf` — re-export `cognito_client_id` and
      `cognito_hosted_ui_domain` from the identity module (`infra/modules/identity/outputs.tf`
      already computes both as `client_id`/`hosted_ui_domain`; confirmed during planning they were
      never re-exported at the env level) — S27, research.md R-401
- [ ] T003 Extend `.github/workflows/deploy-dev.yml` and `.github/workflows/deploy-prod.yml` — one
      new step between the existing "Terraform apply" and "Publish the frontend" steps that writes
      a `<script>window.__CLOUDPULSE_CONFIG__ = {...}</script>` block into the already-built
      `frontend/dist/cloudpulse/index.html`, populated from `terraform output` (`api_endpoint`,
      T002's two new outputs). No reordering of the existing build step — confirmed during planning
      it already runs before `terraform apply` today — S27, research.md R-401

**Checkpoint**: Once deployed, every screen this spec builds can reach the real API and Cognito;
nothing yet renders anything.

---

## Phase 3: User Story 1 — Sign in and see only what my role permits (Priority: P1)

**Goal**: Real sign-in/callback (Authorization Code + PKCE, research.md R-402), sign-out wired to
the existing `AuthService.signOut()`, real per-role navigation replacing the shell's placeholder,
responsive layout.

**Independent Test**: Sign in as each of the three roles in turn and confirm each one's navigation
contains exactly the screens and controls that role is permitted to use; sign out and confirm the
next page load requires signing in again.

### Tests for User Story 1

- [ ] T004 [P] [US1] Write `frontend/e2e/auth.spec.ts` — Playwright, `page.route()` interception
      on Cognito's `/oauth2/authorize` redirect and `/oauth2/token` exchange (research.md R-402,
      the same route-interception pattern `sdas.spec.ts` already established for the platform API,
      applied here to the two new external calls this flow makes): sign-in redirects to the Hosted
      UI URL with a PKCE challenge and `state`; the callback validates `state`, exchanges the code,
      calls `GET /me`, and lands on `returnTo`; an unauthenticated direct request to any dashboard
      route redirects to sign-in (Acceptance Scenario US1.3); sign-out clears the session and the
      next load requires signing in again (Acceptance Scenario US1.4); each role's nav contains
      exactly its permitted screens/controls (Acceptance Scenarios US1.1–2); the shell remains
      usable at phone-width (≈375px) without horizontal scrolling (Acceptance Scenario US1.5,
      FR-004) — S27, FR-001–FR-005

### Implementation for User Story 1

- [ ] T005 [US1] Extend `frontend/src/app/core/api-config.ts` — add `cognitoDomain`/
      `cognitoClientId`/`cognitoRedirectUri` to the `window.__CLOUDPULSE_CONFIG__` type and
      resolver functions, alongside the already-present `apiBaseUrl`/`e2eMockRole` — S27, FR-001
- [ ] T006 [US1] Write `frontend/src/app/core/sign-in.component.ts` — redirects to Cognito Hosted
      UI's `/oauth2/authorize` with a generated PKCE code challenge (S256) and random `state`, both
      held in `sessionStorage` only for the round-trip and cleared on use — S27, FR-001,
      research.md R-402
- [ ] T007 [US1] Write `frontend/src/app/core/auth.callback.component.ts`, served at
      `/auth/callback` — the exact path `infra/envs/dev/main.tf`'s Cognito app client
      `callback_urls` already points at, confirmed during planning not assumed. Validates `state`,
      exchanges the authorization code + PKCE verifier for tokens at Cognito's `/oauth2/token`,
      calls `GET /me` with the access token, populates `AuthService`, navigates to `returnTo`
      (`authGuard` already sets this query param today) — S27, FR-001, research.md R-402
- [ ] T008 [US1] Extend `frontend/src/app/core/auth.service.ts` — in-memory token storage
      (`sessionStorage` for the PKCE round-trip only, never `localStorage` for the tokens
      themselves) alongside the existing signal-based user state — S27, FR-001, plan.md
      Constraints ("zero stored credentials" applied to the frontend layer)
- [ ] T009 [US1] Extend `frontend/src/app/shared/shell.component.ts` — replace the "Overview"
      placeholder nav item with real per-role navigation (compliance overview, inventory, findings,
      scan operations — each present or absent per FR-003's rule: a control whose only purpose a
      role cannot perform, or a page with no permitted content, is not shown); wire the sign-out
      control to `AuthService.signOut()` using T005's new Hosted UI config fields — S27, FR-003,
      FR-005
- [ ] T010 [US1] Wire `/sign-in` and `/auth/callback` routes into `frontend/src/app/app.config.ts`
      — S27, FR-001, FR-002

**Checkpoint**: Sign-in, sign-out, and role-based navigation work end-to-end. Every other route the
shell now links to exists only as a placeholder until its own phase lands.

---

## Phase 4: User Story 2 — See compliance posture at a glance (Priority: P1)

**Goal**: Score cards, findings-by-type/severity charts (`ng2-charts`, already installed), and a
per-account summary table — every number read directly from tag compliance and ownership's
existing `compliance-score`/`findings` APIs, never independently computed.

**Independent Test**: With a test account carrying a known, hand-countable mix of compliant and
non-compliant resources, open the overview and confirm every score and count shown matches the
corresponding API response exactly.

### Tests for User Story 2

- [ ] T011 [P] [US2] Write `frontend/e2e/compliance-overview.spec.ts` — mocked `compliance-score`
      and `findings` API responses (route interception, matching `sdas.spec.ts`'s established
      pattern): overall and per-account scores match the mocked response exactly (Acceptance
      Scenario US2.1, FR-006); findings-by-type/severity counts sum to the mocked total (Acceptance
      Scenario US2.2, FR-007); an account with no completed scan shows the "not yet scanned" state,
      not a zero score or an error (Acceptance Scenario US2.3, FR-009) — S28, FR-006–FR-009,
      SC-004

### Implementation for User Story 2

- [ ] T012 [US2] Write `frontend/src/app/features/overview/compliance-overview.component.ts` —
      score cards, `ng2-charts` findings-by-type/severity charts, per-account summary table
      (account identity, score, resource count, open-finding count, FR-008); loading, empty
      ("not yet scanned"), and error states — S28, FR-006–FR-009
- [ ] T013 [US2] Wire the `/overview` route into `app.config.ts` as the default landing route after
      sign-in — S28, FR-006

**Checkpoint**: A signed-in person lands on a real compliance overview. Inventory, findings, and
scan operations remain unreachable placeholders.

---

## Phase 5: User Story 3 — Explore the full inventory and drill into one resource (Priority: P1)

**Goal**: The platform's first paginated list endpoint (`GET /resources`, confirmed during planning
that no general resource-listing endpoint existed before this spec), server-side paged and filtered
by account/service/region/tag-status/SDA, plus a resource detail view.

**Independent Test**: With a test account containing resources in a known mix of tag states, filter
the inventory to "missing owner tag" and confirm the result set exactly matches which resources
genuinely lack an attributed owner; open one resource's detail panel and confirm its tags,
owner/evidence, findings, and enrichment detail all match what the underlying APIs report.

### Tests for User Story 3

- [ ] T014 [P] [US3] Write `backend/tests/unit/test_resource_filters.py` — the `tagStatus` and
      `ownerStatus` query-building logic are independent filter dimensions (research.md R-403): a
      resource with a valid `owner` tag but no attribution matches `ownerStatus=unattributed` but
      not `tagStatus=missing:owner`, and vice versa — S29, FR-010, FR-013, research.md R-403
- [ ] T015 [P] [US3] Write `backend/tests/integration/test_resources_api.py` — Testcontainers
      PostgreSQL: `GET /resources` filters by account/service/region/sdaId/tagStatus/ownerStatus in
      any combination, returning only resources matching every applied filter (Acceptance Scenario
      US3.1, FR-010); pagination never requires the full inventory to be queried at once (FR-011);
      `ownerStatus=unattributed` returns exactly the resources with no `ResourceOwner` row
      (Acceptance Scenario US3.2, FR-013); `GET /resources/{resourceId}` returns tags, owner +
      evidence (or explicit "unattributed"), findings, and enrichment detail (Acceptance Scenario
      US3.4, FR-012); a soft-deleted resource (`deleted_at IS NOT NULL`) is excluded from the
      default listing but its detail view remains reachable directly by ID (data-model.md) — S29,
      FR-010–FR-013, SC-005
- [ ] T016 [P] [US3] Write `frontend/e2e/inventory-explorer.spec.ts` — mocked `GET /resources`
      responses: applying filters narrows the visible table (FR-010); paging fetches from the
      platform rather than loading everything up front (FR-011); opening a resource's detail panel
      shows its tags/owner/findings/enrichment (FR-012); a zero-result filter shows the explicit
      "no matching resources" state, not a blank or broken table (Edge Cases) — S29, FR-010–FR-013

### Implementation for User Story 3

- [ ] T017 [US3] Write `backend/app/api/routers/resources.py` — `GET /resources` (paged, filtered
      per T014/T015), `GET /resources/{resourceId}` (detail: tags, owner + evidence via
      `ResourceOwner`, findings via the same query shape `GET /findings?resourceId=...` already
      proves, enrichment via `Resource.detail`) — S29, FR-010–FR-013
- [ ] T018 [US3] Wire the `resources` router into `backend/app/api/main.py`; regenerate
      `backend/openapi.generated.yaml` — S29, FR-048 (spec 001 contract discipline)
- [ ] T019 [US3] Write `frontend/src/app/features/inventory/inventory-explorer.component.ts` —
      server-side paged/filtered table — S29, FR-010, FR-011
- [ ] T020 [US3] Write `frontend/src/app/features/inventory/resource-detail.component.ts` — detail
      panel — S29, FR-012
- [ ] T021 [US3] Wire the `/inventory` route into `app.config.ts` — S29, FR-010

**Checkpoint**: The inventory is browsable and filterable end-to-end against real data. Findings and
scan operations remain unreachable placeholders.

---

## Phase 6: User Story 4 — Triage findings and act on AI-suggested fixes (Priority: P1)

**Goal**: Acknowledge an open finding (orthogonal metadata, research.md R-404 — never the finding
lifecycle's `open`/`resolved`/reserved-`suppressed` states), and display a finding's remediation
suggestion — real or, until the AI-insights capability exists, an admin-seeded demo/QA test
suggestion exercising the identical display path (FR-020a, this spec's Clarifications round).

**Independent Test**: Open the findings list, filter it to a known subset, confirm exactly that
subset is shown; acknowledge one finding and confirm its acknowledged state is reflected
immediately without a manual refresh; confirm a finding with a suggestion (real or seeded) shows it
inline, and a finding with none shows the explicit "no suggestion available" state.

- [ ] T022 [US4] Write `backend/migrations/versions/0011_finding_acknowledgment_and_suggestion.py`
      — additive migration adding `finding.acknowledged_at`/`finding.acknowledged_by` (nullable,
      the latter FK → `app_user.id` `ON DELETE SET NULL`) and the `finding_remediation_suggestion`
      table (`finding_id` FK → `finding.id` `ON DELETE CASCADE`, **UNIQUE**; `suggestion_text`,
      `blast_radius_note`; `source` ENUM `suggestion_source` — `ai_generated`, `admin_seeded`) per
      data-model.md — S30, FR-016, FR-018, FR-020a
- [ ] T023 [P] [US4] Update `ops/erd/schema.mmd` to reflect T022's additions — same PR as T022 per
      the `erd-current` CI gate (spec 002/003's precedent: a schema-migration PR must touch
      `ops/erd/` in the same PR) — Principle I

### Tests for User Story 4

- [ ] T024 [P] [US4] Write `backend/tests/integration/test_finding_acknowledgment.py` —
      Testcontainers PostgreSQL: acknowledging an open finding sets `acknowledged_at`/
      `acknowledged_by` (FR-016) without changing `status` or affecting the account's compliance
      score (FR-017); acknowledging the same finding a second time, including a near-simultaneous
      second attempt, is a no-op — the guarded `UPDATE ... WHERE acknowledged_at IS NULL` matches
      zero rows on the second attempt rather than erroring or duplicating (FR-020, data-model.md);
      a viewer's attempt is refused — S30, FR-015–FR-017, FR-020, FR-028
- [ ] T025 [P] [US4] Write `backend/tests/integration/test_remediation_suggestion.py` —
      Testcontainers PostgreSQL: `GET .../suggestion` returns an explicit empty body (not 404) when
      none exists (FR-019); an admin's `PUT .../suggestion` always writes `source: admin_seeded`
      (the endpoint has no path to writing `ai_generated`, per data-model.md) and the result
      displays identically in shape to how a real suggestion would (FR-020a); an operator's or
      viewer's `PUT` attempt is refused (FR-028a) while their `GET` succeeds (FR-027) — S30,
      FR-018–FR-020a, FR-027, FR-028a
- [ ] T026 [P] [US4] Write `frontend/e2e/findings-workbench.spec.ts` — mocked findings/
      acknowledge/suggestion API responses: filtering narrows the list (Acceptance Scenario US4.1,
      FR-014); acknowledging updates the row immediately with no manual refresh (Acceptance
      Scenario US4.2, FR-015, SC-006); a finding with a suggestion shows it inline with its
      blast-radius note (Acceptance Scenario US4.3, FR-018); a finding with none shows "no
      suggestion available", not an error or blank space (Acceptance Scenario US4.4, FR-019); a
      viewer sees suggestions but has no acknowledge control (Acceptance Scenario US4.5); an admin
      attaching a seed suggestion sees it display identically to a real one, visibly marked as test
      data, and a non-admin has no control to attach or edit one (Acceptance Scenario US4.6,
      FR-020a, FR-028a) — S30, FR-014–FR-020a

### Implementation for User Story 4

- [ ] T027 [US4] Write `backend/app/governance/suggestions.py` — thin read/write around
      `finding_remediation_suggestion`: fetch-or-empty (FR-019), admin-seed write that always sets
      `source=admin_seeded` (FR-020a) — S30, FR-018–FR-020a
- [ ] T028 [US4] Extend `backend/app/api/routers/findings.py` — `POST
      /findings/{findingId}/acknowledge` (admin/operator, FR-015–FR-017, FR-020, FR-028) via the
      guarded `UPDATE ... WHERE acknowledged_at IS NULL`; `GET /findings/{findingId}/suggestion`
      (all-role, FR-018, FR-019, FR-027) and `PUT /findings/{findingId}/suggestion` (admin-only,
      FR-020a, FR-028a) calling T027 — S30, FR-015–FR-020a, FR-027, FR-028a
- [ ] T029 [US4] Write `frontend/src/app/features/findings/findings-workbench.component.ts` —
      list/filter, acknowledge control, suggestion display inline with an admin-only seed control
      — S30, FR-014–FR-020a
- [ ] T030 [US4] Wire the `/findings` route into `app.config.ts` — S30, FR-014

**Checkpoint**: 🏁 **P1 functionally complete.** Every P1 user story is implemented end-to-end
against real backend data. What remains before declaring P1 done is proving it against real AWS,
not mocked tests — that's Phase 7.

---

## Phase 7: P1 Completion — Role Matrix, Live Verification, Teardown

**Purpose**: The mocked-test suite proves the logic; this phase proves the system, against a real
AWS account, the way specs 001–003 did. Playbook §0.5.5: run `/speckit-analyze` a second time after
this phase, before starting Phase 8.

- [ ] T031 Write `backend/tests/integration/test_role_matrix_governance_dashboard.py` — the full
      role matrix across this spec's P1 write/read surfaces (resources read, finding acknowledge,
      finding suggestion read/write): admin-only write on suggestion-seed, admin/operator write on
      acknowledge, all-role read everywhere, explicitly asserting a non-admin/non-operator write
      attempt is refused rather than inferred from success. **P2's scan-operations role gating
      (FR-021–FR-023) is deliberately excluded** — that surface doesn't exist yet, Phase 8 — S27–S30,
      FR-027, FR-028, FR-028a
- [ ] T032 **Live-verification.** Deploy this spec's work to dev (dispatch `Deploy dev` manually,
      per specs 002/003's precedent), and walk quickstart.md V1–V7 against the real primary AWS
      account — confirms SC-001–SC-007 against reality, not mocks, and V3–V6 together are SC-002's
      full demo path (onboard → scan → findings + suggestions → acknowledge). **Before attempting
      any scenario
      needing a connected account (V3–V6), check whether research.md R-407's standing gap has been
      resolved.** Tag compliance and ownership's own T032 already confirmed (twice, following
      account onboarding and discovery's T053) that account registration hangs to Lambda's
      30-second timeout — a VPC-networking gap unrelated to this spec's own code, already priced
      out and twice declined by the user to fund. If still open, scope this task honestly to what's
      actually provable — V1 (sign-in, every role) and V2 (empty/error states with zero connected
      accounts) — and record SC-003–SC-007 as proven at the mocked-test level only, the same
      honest-outcome pattern specs 002/003 both landed on. Do not re-litigate the NAT/VPC-endpoint
      cost tradeoff a third time without a new signal from the user — S27–S30, SC-001–SC-002,
      SC-003–SC-007
- [ ] T033 **Teardown and cost sweep**, immediately following T032, never separated from it by
      other work: run the full playbook §0.5.3 sweep. Research.md R-406 states this spec adds zero
      new billable AWS resources, so there is no spec-004-specific sweep addition the way R-306
      needed one for tag compliance and ownership's new SQS queues — the generic checklist is the
      complete one here — S27–S30, playbook §0.5.3

**Checkpoint**: 🏁 **P1 complete at the mocked-test level (CI), live-verification outcome recorded
honestly per T032's own instructions.**

---

## Phase 8: User Story 5 — Trigger and track a scan without leaving the dashboard (Priority: P2)

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise a P1 path. If
this phase is dropped entirely, Phases 1–7 still satisfy every P1 success criterion (SC-008
excepted, per the Tier Summary above). Reuses account onboarding and discovery's existing
on-demand-scan and scan-history APIs entirely — this story adds no new scanning or
scan-triggering capability, only the screen that surfaces what already exists, plus one small,
additive response-shape extension (research.md R-405).

### Tests for User Story 5

- [ ] T034 [P] [US5] **[P2]** Write `backend/tests/unit/test_scan_deltas.py` — the `added`/
      `removed`/`changed` fields (research.md R-405) are computed correctly from
      `resource.first_seen_at`/`last_seen_at`/`deleted_at` against a scan's
      `[started_at, finished_at]` window, with no new persisted state — S31, FR-021, research.md
      R-405
- [ ] T035 [P] [US5] **[P2]** Write `frontend/e2e/scan-operations.spec.ts` — mocked scan-history/
      trigger-scan responses: history shows start time, duration, and deltas (Acceptance Scenario
      US5.1, FR-021); triggering a scan shows a status that updates through to a final state via
      polling (research.md Assumptions), without a manual reload (Acceptance Scenario US5.2,
      FR-022, SC-008); a viewer sees history but has no trigger control (Acceptance Scenario US5.3,
      FR-023) — S31, FR-021–FR-023

### Implementation for User Story 5

- [ ] T036 [US5] **[P2]** Extend `backend/app/api/routers/accounts.py`'s `list_scan_history` /
      `ScansList` response model — three new, additive, non-required integer fields computed at
      query time per T034/research.md R-405; no new column, no new table — S31, FR-021
- [ ] T037 [US5] **[P2]** Write `frontend/src/app/features/scans/scan-operations.component.ts` —
      history table with deltas, "Scan now" trigger control (admin/operator only, FR-023), polled
      status until a final state — S31, FR-021–FR-023
- [ ] T038 [US5] **[P2]** Wire the `/scans` route into `app.config.ts` — S31, FR-021

**Checkpoint**: P2 stretch scope complete; SC-008 now provable; quickstart.md V8 can be run live as
a follow-up to Phase 7's T032 if desired (not itself re-numbered as a new live-verify task — it
extends the same dev deployment T032/T033 already covered, redeployed if it was torn down).

---

## Phase 9: Hardening (S33) [P2]

- [ ] T039 [P2] Write `frontend/e2e/dashboard-smoke.spec.ts` — end-to-end smoke suite covering each
      P1 user story's primary journey in one pass (sign in as each role; view compliance overview;
      filter and drill into inventory; filter, view a suggestion on, and acknowledge a finding) —
      S33, FR-024
- [ ] T040 [P2] Audit pass: confirm every P1 screen (T012, T019/T020, T029) has a defined loading,
      empty, and error state, each visually and behaviorally distinct from the other two (FR-025,
      fixed by this spec's own checklist review to actually require a loading state, not merely
      contrast against one) — fill any gap found, cite the fix against the specific screen and
      state — S33, FR-025
- [ ] T041 [P2] Extend `.github/workflows/deploy-dev.yml` — run T039's smoke suite against the real
      dev environment after each successful deploy (FR-026), gated the same way every other
      dev-only step already is — S33, FR-026

**Checkpoint**: P2 hardening complete; the P1 demo path has automated regression coverage running
against real infrastructure after every dev deploy, not only in CI's mocked suite.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [ ] T042 [P] Update `backend/README.md`, `frontend/src/app/features/README.md`, and
      `infra/README.md` to describe this spec's new `app/api/routers/resources.py`,
      `app/governance/suggestions.py`, the four new frontend feature areas, and the deploy-time
      runtime-config injection (research.md R-401) — Principle I
- [ ] T043 Re-run `/speckit-analyze` on spec 004 (playbook §8's second-run note) and resolve any
      finding before spec 005 begins — Governance

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → Phase 3+**: strictly sequential — Phase 2's deploy-config fix is what makes
  every later phase's live functioning possible at all.
- **Phase 3 (US1) blocks every other user story**: nothing is reachable without sign-in and
  role-based navigation existing first — spec.md's own dependency ordering, unchanged here.
- **Phases 4, 5, 6 (US2, US3, US4) are independent of each other** once Phase 3 lands — different
  files, different routers, different frontend feature directories — and may run in parallel.
- **Phase 6 (US4) owns its own schema (T022/T023)**, not front-loaded into Phase 2, because no
  other story needs it — honest dependency ordering keeps Phases 4–5 free of a migration they
  don't touch.
- **Phase 7 depends on Phases 3–6 all being merged**: it is the integration-proof phase, the same
  role tag compliance and ownership's own Phase 8 played there.
- **T0XX-style mid-implementation additions**: if any phase's work surfaces a gap this list didn't
  anticipate, add the task here before its fix PR, per this file's own Process Note.
- **T031/T032/T033 must stay adjacent**: do not let Phase 8 work begin between live-verification
  and teardown — account onboarding and discovery's own playbook §0.5.3 origin story is exactly
  this failure mode.

## Parallel Execution Example

Phases 4 and 5's test tasks can all run together — three independent files, no shared state:

```text
T011 [P] [US2] frontend/e2e/compliance-overview.spec.ts
T014 [P] [US3] backend/tests/unit/test_resource_filters.py
T015 [P] [US3] backend/tests/integration/test_resources_api.py
T016 [P] [US3] frontend/e2e/inventory-explorer.spec.ts
```

## Implementation Strategy

**MVP first**: Phases 1–4 (Setup, Foundational, US1, US2) alone deliver a demonstrable "sign in,
see compliance posture" capability — not yet the demo's namesake "full governance story," but a
real, working slice. **Incremental delivery to a demoable P1**: Phases 1–6 in order is the shortest
path to every P1 acceptance scenario being exercisable; Phase 7 is what turns "exercisable in CI"
into "proven against real AWS" — bounded honestly by research.md R-407's standing constraint, not
silently worked around. P2 (Phases 8–9) is additive polish afterward, never a prerequisite for
declaring the P1 demo path complete.
