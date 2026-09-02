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

- [X] T001 Scaffold four new empty directories mirroring `accounts/`/`sdas/`'s existing
      standalone-component layout: `frontend/src/app/features/{overview,inventory,findings,scans}/`
      — no logic yet, just the layout plan.md's Project Structure commits to.
      **Done**: created locally; git cannot track empty directories, so each will be committed
      for real alongside its own phase's first file (T012, T019/T020, T029, T037).

**Checkpoint**: Directory layout exists; nothing yet imports from or deploys it.

---

## Phase 2: Foundational (blocking prerequisites for every user story)

**Purpose**: Every screen this spec adds calls the platform API once deployed; none of them work
live without research.md R-401's runtime-config fix — this is genuinely foundational, not tied to
any one story, unlike this spec's schema (which only User Story 4 needs, and stays in that story's
own phase per honest dependency ordering rather than being front-loaded here for convenience).

- [X] T002 [P] Extend `infra/envs/{dev,prod}/outputs.tf` — re-export `cognito_client_id` and
      `cognito_hosted_ui_domain` from the identity module (`infra/modules/identity/outputs.tf`
      already computes both as `client_id`/`hosted_ui_domain`; confirmed during planning they were
      never re-exported at the env level) — S27, research.md R-401
      **Done**: no deviations. `terraform fmt -check -recursive infra/` and `terraform validate`
      pass for both envs.
- [X] T003 Extend `.github/workflows/deploy-dev.yml` and `.github/workflows/deploy-prod.yml` — one
      new step between the existing "Terraform apply" and "Publish the frontend" steps that writes
      a `<script>window.__CLOUDPULSE_CONFIG__ = {...}</script>` block into the already-built
      `frontend/dist/cloudpulse/browser/index.html` (see T003a for why `browser/`), populated from
      `terraform output` (`api_endpoint`, `frontend_url`, T002's two new outputs). No reordering of
      the existing build step — confirmed during planning it already runs before `terraform apply`
      today — S27, research.md R-401
      **Done**: no deviations. The exact `run:` block was extracted from the committed YAML via
      `yaml.safe_load` (not a hand-retyped copy) and executed verbatim against the real `ng build`
      output before committing — confirms the heredoc's indentation survives YAML's block-scalar
      dedent correctly and the injected script lands immediately before `</head>`, valid HTML and
      valid JSON.
- [X] T003a **[Found live, not by inspection]** Fix `deploy-dev.yml`'s and `deploy-prod.yml`'s
      frontend publish step — Angular's `application` builder (confirmed in `angular.json`) always
      nests its real output under `dist/cloudpulse/browser/`, never directly in `dist/cloudpulse/`
      regardless of the configured `outputPath`; confirmed empirically by running the actual build,
      not assumed from the builder's docs. Both deploy workflows' "Publish the frontend" step syncs
      `frontend/dist/cloudpulse` (the parent) to S3, so `index.html` has been landing at
      `s3://bucket/browser/index.html` — CloudFront's `default_root_object = "index.html"`
      (`infra/modules/frontend/main.tf`) looks for it at the bucket root, which was never
      populated. The deployed frontend has not been reachable at its own CloudFront URL through
      this pipeline since spec 001 — every prior live-verification session tested the API directly
      (`/health`, Cognito flows) and never actually loaded the deployed SPA in a browser, which is
      why this went uncaught for three specs. Found while implementing T003, which needs to know
      the real `index.html` path to inject into — not a hypothetical, the build's actual output
      directory was inspected directly. Fix: sync `frontend/dist/cloudpulse/browser` instead of
      `frontend/dist/cloudpulse` in both workflows — S27, research.md R-401
      **Done**: both workflows' "Publish the frontend" step now syncs the `browser/` subdirectory.
      No live-verification session in this spec's history yet confirms the fix against a real
      CloudFront distribution — that remains T032's job, same as every other live-behavior claim
      in this spec.

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

- [X] T004 [P] [US1] Write `frontend/e2e/auth.spec.ts` — Playwright, `page.route()` interception
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
      **Done**: 8 tests, 6/6 role/nav + flow tests plus 2 initial failures fixed before landing.
      **Acceptance Scenarios US1.1–2 re-scoped, not silently reinterpreted**: every screen in this
      platform turned out to already be all-role read (Accounts FR-010a, SDAs FR-030, every spec
      004 screen's own FR-027 written earlier this session) — there is no case where an entire nav
      item needs hiding per role, only per-screen write controls (already disabled-not-hidden,
      proven by `sdas.spec.ts`'s own non-admin test, not re-tested here). The shell's nav is
      uniform and unconditional; only the sign-in/sign-out control toggles. Documented in
      `shell.component.ts`'s own docstring, not just here.
      **Two real bugs found by running the test, not by inspection**: (1) the phone-width test
      failed for real — 6 nav links + title + sign-out button in one unwrapped flex row overflowed
      at 375px; fixed with `flex-wrap` on both `.shell-header` and `.shell-nav` (also verified
      visually in a real browser at 375px, not just the automated check). (2) the sign-out test's
      own mocks stayed registered after use, so a later `/sign-in` visit auto-completed a fresh
      sign-in through the still-mocked Cognito routes before the assertion could observe the
      redirect. First fix attempt (`page.unroute()`) traded this for a worse flake: setting
      `window.location.href` always commits to leaving the document even when the route is
      unrouted or aborted, landing on `chrome-error://` once the target errors — confirmed by 3
      repeat runs failing identically, not a one-off. Real fix: clear the Cognito config via a
      second `addInitScript` before the final check, so `SignInComponent` no-ops on mount exactly
      like the unauthenticated-redirect test does; isolates the assertion to `authGuard`'s own
      redirect. Re-verified stable across 3 repeat runs. Test-design bug throughout, not a product
      one.
      **Also fixed in this PR**: `sdas.spec.ts`'s top comment claiming "no `/sign-in` route exists"
      was now stale (playbook §0.5.5: grep for what a fix replaces in the same PR).

### Implementation for User Story 1

- [X] T005 [US1] Extend `frontend/src/app/core/api-config.ts` — add `cognitoDomain`/
      `cognitoClientId`/`cognitoRedirectUri` to the `window.__CLOUDPULSE_CONFIG__` type and
      resolver functions, alongside the already-present `apiBaseUrl`/`e2eMockRole` — S27, FR-001
      **Done**: no deviations. Added `resolveCognitoConfig()` returning `null` unless all three
      fields are present, so callers get one clean guard clause instead of three separate optional
      checks.
- [X] T006 [US1] Write `frontend/src/app/core/sign-in.component.ts` — redirects to Cognito Hosted
      UI's `/oauth2/authorize` with a generated PKCE code challenge (S256) and random `state`, both
      held in `sessionStorage` only for the round-trip and cleared on use — S27, FR-001,
      research.md R-402
      **Done**: PKCE generation factored into a new `core/pkce.ts` (Web Crypto API, no new
      dependency) since `auth.callback.component.ts` (T007) also needs to consume it.
- [X] T007 [US1] Write `frontend/src/app/core/auth.callback.component.ts`, served at
      `/auth/callback` — the exact path `infra/envs/dev/main.tf`'s Cognito app client
      `callback_urls` already points at, confirmed during planning not assumed. Validates `state`,
      exchanges the authorization code + PKCE verifier for tokens at Cognito's `/oauth2/token`,
      calls `GET /me` with the access token, populates `AuthService`, navigates to `returnTo`
      (`authGuard` already sets this query param today) — S27, FR-001, research.md R-402
      **Done**: no deviations. Token exchange uses `fetch` directly (Cognito's own OAuth endpoint,
      not the platform's generated contract, so Principle V's "no hand-written API calls" doesn't
      apply); `GET /me` itself goes through the generated `IdentityService`, per that same
      principle.
- [X] T008 [US1] Extend `frontend/src/app/core/auth.service.ts` — the access/ID tokens
      themselves are held in memory only (a service field, never `sessionStorage` or
      `localStorage`), alongside the existing signal-based user state. (`sessionStorage` is used
      solely by T006/T007 for the PKCE verifier and `state` during the redirect round-trip — a
      separate concern from the tokens this task stores.) — S27, FR-001, plan.md Constraints
      ("zero stored credentials" applied to the frontend layer)
      **Real gap found while implementing, not by inspection**: nothing in this application ever
      attached a bearer token to an outgoing request before this — confirmed by grepping the whole
      `core/` tree for any existing `Authorization`/`Bearer` handling and finding none; every prior
      `GET /me` this session verified was called directly with `curl`, never through the running
      app, which is why this went unnoticed. `plan.md`'s own task text ("token storage... alongside
      the existing signal-based user state") didn't name this explicitly, but a stored-and-unused
      token satisfies no part of FR-001's actual "sign in" requirement. Added a small new
      `auth.interceptor.ts` (not separately listed in plan.md's file tree, which was never claimed
      exhaustive) reading the token fresh from `AuthService` on every request, wired into
      `app.config.ts` alongside the existing `correlationInterceptor`.
- [X] T009 [US1] Extend `frontend/src/app/shared/shell.component.ts` — replace the "Overview"
      placeholder nav item with real per-role navigation (compliance overview, inventory, findings,
      scan operations — each present or absent per FR-003's rule: a control whose only purpose a
      role cannot perform, or a page with no permitted content, is not shown); wire the sign-out
      control to `AuthService.signOut()` using T005's new Hosted UI config fields — S27, FR-003,
      FR-005
      **Done, with a real correction found mid-implementation**: the first version wrapped the
      entire `<nav>` in `@if (auth.isAuthenticated())`, matching FR-003's literal per-role framing
      — but running the *existing* `shell.spec.ts` a11y suite against it failed immediately: that
      suite visits `/` with no session and asserts the `navigation` landmark is present, since the
      nav is chrome the shell has always rendered unconditionally. Re-examined FR-003 against what
      actually exists (see T004's note: every screen is all-role read) and concluded the nav itself
      was never the right place to gate — fixed to render the nav list unconditionally for
      everyone, gating only the sign-in/sign-out control by auth state. Also added `.sdas`/
      `.accounts` links (spec 002/003 built those routes but never linked them from the shell,
      confirmed by re-reading the file's own prior comment: "Feature routes are added here by
      specs 002-005" — this is that "005" catching up on "002-003"'s unlinked routes too, not
      scope creep).
- [X] T010 [US1] Wire `/sign-in` and `/auth/callback` routes into `frontend/src/app/app.config.ts`
      — S27, FR-001, FR-002
      **Done**: no deviations. `authInterceptor` (T008) also wired into `provideHttpClient` here,
      ordered before `correlationInterceptor`.

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

- [X] T011 [P] [US2] Write `frontend/e2e/compliance-overview.spec.ts` — mocked `compliance-score`
      and `findings` API responses (route interception, matching `sdas.spec.ts`'s established
      pattern): overall and per-account scores match the mocked response exactly (Acceptance
      Scenario US2.1, FR-006); findings-by-type/severity counts sum to the mocked total (Acceptance
      Scenario US2.2, FR-007); an account with no completed scan shows the "not yet scanned" state,
      not a zero score or an error (Acceptance Scenario US2.3, FR-009) — S28, FR-006–FR-009,
      SC-004
      **Done**: 4/4 passing. One test-locator bug fixed (`getByText('70%')` matched both the score
      card and a table cell -- scoped to `.score-card .score`). One real service bug found by the
      zero-accounts test, not by inspection: `OverviewService.refresh()` unconditionally called
      `listFindings` even with zero accounts, so an unmocked/failing call in that scenario masked
      the empty state behind an error -- fixed by skipping the findings fetch when there are no
      accounts.

### Implementation for User Story 2

- [X] T012 [US2] Write `frontend/src/app/features/overview/compliance-overview.component.ts` —
      score cards, `ng2-charts` findings-by-type/severity charts, per-account summary table
      (account identity, score, resource count, open-finding count, FR-008); loading, empty
      ("not yet scanned"), and error states — S28, FR-006–FR-009
      **Done**: new `overview.service.ts` wraps the generated Accounts/Compliance/Findings clients
      (Principle V pattern, matching `accounts.service.ts`). "Overall" score is a sum of the
      per-account `compliantCount`/`totalCount` values the API already returned, never an
      independently invented formula (FR-006, SC-004). `provideCharts(withDefaultRegisterables())`
      added to `app.config.ts` (ng2-charts was already an installed dependency, per plan.md — this
      is the first component to actually use it).
- [X] T013 [US2] Wire the `/overview` route into `app.config.ts` as the default landing route after
      sign-in — S28, FR-006
      **Done**: `{ path: '', pathMatch: 'full', redirectTo: 'overview' }`.

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

- [X] T014 [P] [US3] Write `backend/tests/unit/test_resource_filters.py` — the `tagStatus` and
      `ownerStatus` query-building logic are independent filter dimensions (research.md R-403): a
      resource with a valid `owner` tag but no attribution matches `ownerStatus=unattributed` but
      not `tagStatus=missing:owner`, and vice versa — S29, FR-010, FR-013, research.md R-403
      **Done**: 4/4 passing, exercises `_parse_tag_status` directly (the pure-logic half of the
      filter; the DB-backed distinction is T015's job).
- [X] T015 [P] [US3] Write `backend/tests/integration/test_resources_api.py` — Testcontainers
      PostgreSQL: `GET /resources` filters by account/service/region/sdaId/tagStatus/ownerStatus in
      any combination, returning only resources matching every applied filter (Acceptance Scenario
      US3.1, FR-010); pagination never requires the full inventory to be queried at once (FR-011);
      `ownerStatus=unattributed` returns exactly the resources with no `ResourceOwner` row
      (Acceptance Scenario US3.2, FR-013); `GET /resources/{resourceId}` returns tags, owner +
      evidence (or explicit "unattributed"), findings, and enrichment detail (Acceptance Scenario
      US3.4, FR-012); a soft-deleted resource (`deleted_at IS NOT NULL`) is excluded from the
      default listing but its detail view remains reachable directly by ID (data-model.md); an
      `sdaId` filter's result set updates correctly when that SDA is removed mid-session — a
      resource that reverts to "No SDA" (tag compliance and ownership's immediate-revert
      semantics) no longer matches the now-removed `sdaId`, with no error from the filter
      continuing to reference it (spec.md Edge Cases) — S29, FR-010–FR-013, SC-005
      **Done**: 9/9 passing. Real bug caught, not by inspection: the seed fixture's first version
      inserted a duplicate `owner` rule row — migration 0010 already seeds one per tenant, hitting
      `uq_rule_tenant_key_version` — fixed to reuse the seeded row (same precedent spec 003's own
      tests already established). Real backend bug caught the same way: `_open_finding_rule_keys`
      selected `RuleRow.key` without `select_from(FindingRow)`, and SQLAlchemy couldn't determine
      which table the join was driven from ("don't know how to join to Rule") — fixed in T017.
- [X] T016 [P] [US3] Write `frontend/e2e/inventory-explorer.spec.ts` — mocked `GET /resources`
      responses: applying filters narrows the visible table (FR-010); paging fetches from the
      platform rather than loading everything up front (FR-011); opening a resource's detail panel
      shows its tags/owner/findings/enrichment (FR-012); a zero-result filter shows the explicit
      "no matching resources" state, not a blank or broken table (Edge Cases) — S29, FR-010–FR-013
      **Done**: 3/3 passing. One real route-mock bug found by running it, not by inspection: a glob
      like `**/resources*` does not cross the `/` before a resource id, so the detail-panel test's
      `GET /resources/{id}` fell through unmocked — fixed with a regex covering both the list and
      detail paths, the same fix `sdas.spec.ts` already established for this exact class of glob
      limitation.

### Implementation for User Story 3

- [X] T017 [US3] Write `backend/app/api/routers/resources.py` — `GET /resources` (paged, filtered
      per T014/T015), `GET /resources/{resourceId}` (detail: tags, owner + evidence via
      `ResourceOwner`, findings via the same query shape `GET /findings?resourceId=...` already
      proves, enrichment via `Resource.detail`) — S29, FR-010–FR-013
      **Done**: response model named `InventoryResourceSummary`, not the more obvious
      `ResourceSummary` — `findings.py` and `sdas.py` already both define a `ResourceSummary` with
      an identical shape (no collision), but this endpoint's shape is genuinely different (extra
      `service`/`sdaId`/`tagStatus`/`ownerStatus` fields); naming it the same would have forced
      FastAPI's OpenAPI generator to disambiguate all three into ugly, unstable module-qualified
      names (confirmed by trying it first, not guessed) — caught before merge, not left for a
      later cleanup.
- [X] T018 [US3] Wire the `resources` router into `backend/app/api/main.py`; regenerate
      `backend/openapi.generated.yaml` and the OpenAPI-generated frontend API client (a new
      `resources.service.ts`/`resources.serviceInterface.ts` pair, matching every existing
      per-tag service file) — T019/T020 depend on the generated client existing, and
      `client-drift` (CI) fails on any mismatch — S29, FR-048 (spec 001 contract discipline)
      **Done**: generation initially failed with "Unable to locate a Java Runtime" — Homebrew's
      `openjdk` was installed but never linked to the system `java`; worked around locally with
      `JAVA_HOME=$(brew --prefix openjdk)`, not a code change (CI's own runner already has a
      working JDK via `setup-java`-equivalent tooling, confirmed by every prior spec's green
      `client-drift` check).
- [X] T019 [US3] Write `frontend/src/app/features/inventory/inventory-explorer.component.ts` —
      server-side paged/filtered table — S29, FR-010, FR-011
      **Done**: new `inventory.service.ts` wraps the generated `ResourcesService` (Principle V
      pattern). Filter inputs are plain text fields (account/service/region/sdaId/tagStatus) plus
      a checkbox for `ownerStatus=unattributed` — no dropdown enumeration of rule keys or SDAs,
      since neither the spec nor plan.md called for one and the raw string filters already prove
      FR-010/FR-011 end-to-end.
- [X] T020 [US3] Write `frontend/src/app/features/inventory/resource-detail.component.ts` — detail
      panel — S29, FR-012
      **Done, with one real template bug found by the build, not by inspection**: `@else if (expr;
      as alias)` did not bind the alias (Angular 18's control-flow syntax) — the compiler reported
      `alias` as an unresolved component property instead. Fixed by splitting into two separate
      `@if` blocks rather than an `@if`/`@else if` chain.
- [X] T021 [US3] Wire the `/inventory` route into `app.config.ts` — S29, FR-010
      **Done**: no deviations.

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

- [X] T022 [US4] Write `backend/migrations/versions/0011_finding_acknowledgment_and_suggestion.py`
      — additive migration adding `finding.acknowledged_at`/`finding.acknowledged_by` (nullable,
      the latter FK → `app_user.id` `ON DELETE SET NULL`) and the `finding_remediation_suggestion`
      table (`finding_id` FK → `finding.id` `ON DELETE CASCADE`, **UNIQUE**; `suggestion_text`,
      `blast_radius_note`; `source` ENUM `suggestion_source` — `ai_generated`, `admin_seeded`) per
      data-model.md — S30, FR-016, FR-018, FR-020a
      **Done**: full reversible up/down. Verified end-to-end by rerunning `test_resources_api.py`
      (its `alembic_config` fixture does a real `alembic upgrade head` through 0011).
- [X] T023 [P] [US4] Update `ops/erd/schema.mmd` to reflect T022's additions — same PR as T022 per
      the `erd-current` CI gate (spec 002/003's precedent: a schema-migration PR must touch
      `ops/erd/` in the same PR) — Principle I
      **Done**: added `acknowledged_at`/`acknowledged_by` to `FINDING`, new
      `FINDING_REMEDIATION_SUGGESTION` entity, and the three new relationships.

### Tests for User Story 4

- [X] T024 [P] [US4] Write `backend/tests/integration/test_finding_acknowledgment.py` —
      Testcontainers PostgreSQL: acknowledging an open finding sets `acknowledged_at`/
      `acknowledged_by` (FR-016) without changing `status` or affecting the account's compliance
      score (FR-017); acknowledging the same finding a second time, including a near-simultaneous
      second attempt, is a no-op — the guarded `UPDATE ... WHERE acknowledged_at IS NULL` matches
      zero rows on the second attempt rather than erroring or duplicating (FR-020, data-model.md);
      a viewer's attempt is refused — S30, FR-015–FR-017, FR-020, FR-028
      **Done**: 7 tests, all pass against real PostgreSQL. Includes an audit-event-count assertion
      (2 POSTs → 2 `finding.acknowledge` audit rows, even though the second is a DB no-op).
- [X] T025 [P] [US4] Write `backend/tests/integration/test_remediation_suggestion.py` —
      Testcontainers PostgreSQL: `GET .../suggestion` returns an explicit empty body (not 404) when
      none exists (FR-019); an admin's `PUT .../suggestion` always writes `source: admin_seeded`
      (the endpoint has no path to writing `ai_generated`, per data-model.md) and the result
      displays identically in shape to how a real suggestion would (FR-020a); an operator's or
      viewer's `PUT` attempt is refused (FR-028a) while their `GET` succeeds (FR-027) — S30,
      FR-018–FR-020a, FR-027, FR-028a
      **Done**: 7 tests, all pass. Includes a direct proof that a request body claiming
      `"source": "ai_generated"` is ignored (schema has no such field) and the row still lands as
      `admin_seeded`, and an upsert-not-duplicate check (seed twice, assert exactly 1 row).
- [X] T026 [P] [US4] Write `frontend/e2e/findings-workbench.spec.ts` — mocked findings/
      acknowledge/suggestion API responses: filtering narrows the list (Acceptance Scenario US4.1,
      FR-014); acknowledging updates the row immediately with no manual refresh (Acceptance
      Scenario US4.2, FR-015, SC-006); a finding with a suggestion shows it inline with its
      blast-radius note (Acceptance Scenario US4.3, FR-018); a finding with none shows "no
      suggestion available", not an error or blank space (Acceptance Scenario US4.4, FR-019); a
      viewer sees suggestions but has no acknowledge control (Acceptance Scenario US4.5); an admin
      attaching a seed suggestion sees it display identically to a real one, visibly marked as test
      data, and a non-admin has no control to attach or edit one (Acceptance Scenario US4.6,
      FR-020a, FR-028a) — S30, FR-014–FR-020a
      **Done**: 6 tests, all pass in a real Chromium instance. Full suite (34 tests) re-run clean,
      no regressions.

### Implementation for User Story 4

- [X] T027 [US4] Write `backend/app/governance/suggestions.py` — thin read/write around
      `finding_remediation_suggestion`: fetch-or-empty (FR-019), admin-seed write that always sets
      `source=admin_seeded` (FR-020a) — S30, FR-018–FR-020a
      **Done**: `get_suggestion`/`seed_suggestion`, mirroring `scoring.py`'s pure/DB-touching split.
      `seed_suggestion` upserts via `INSERT ... ON CONFLICT (tenant_id, finding_id) DO UPDATE`.
- [X] T028 [US4] Extend `backend/app/api/routers/findings.py` — `POST
      /findings/{findingId}/acknowledge` (admin/operator, FR-015–FR-017, FR-020, FR-028) via the
      guarded `UPDATE ... WHERE acknowledged_at IS NULL`; `GET /findings/{findingId}/suggestion`
      (all-role, FR-018, FR-019, FR-027) and `PUT /findings/{findingId}/suggestion` (admin-only,
      FR-020a, FR-028a) calling T027; regenerate `backend/openapi.generated.yaml` and the
      OpenAPI-generated frontend `findings.service.ts`/`findings.serviceInterface.ts` — T029
      depends on the regenerated client existing — S30, FR-015–FR-020a, FR-027, FR-028a
      **Done**. Also added `acknowledgedAt`/`acknowledgedBy` to the existing `Finding` response
      model (`GET /findings`) — a gap the contract's "referenced not redefined" note didn't settle:
      FR-015 requires the list to reflect acknowledgment "immediately, without requiring a manual
      refresh," which needs the field on the list row itself for the frontend to patch in place.
      Found by the frontend build failing on `{ ...f, acknowledgedAt: ... }` against the
      generated `Finding` interface, not by inspection. Regenerated both the backend contract and
      frontend client twice (once per schema change); `ng build`/`ng lint` clean both times.
- [X] T029 [US4] Write `frontend/src/app/features/findings/findings-workbench.component.ts` —
      list/filter, acknowledge control, suggestion display inline with an admin-only seed control
      — S30, FR-014–FR-020a
      **Done**. Suggestion fetched lazily on expand, not for every row up front.
- [X] T030 [US4] Wire the `/findings` route into `app.config.ts` — S30, FR-014
      **Done**. Nav link already existed from Phase 3's shell (pointed at `/findings` before the
      route did).

**Checkpoint**: 🏁 **P1 functionally complete.** Every P1 user story is implemented end-to-end
against real backend data. What remains before declaring P1 done is proving it against real AWS,
not mocked tests — that's Phase 7.

---

## Phase 7: P1 Completion — Role Matrix, Live Verification, Teardown

**Purpose**: The mocked-test suite proves the logic; this phase proves the system, against a real
AWS account, the way specs 001–003 did. Playbook §0.5.5: run `/speckit-analyze` a second time after
this phase, before starting Phase 8.

- [X] T031 Write `backend/tests/integration/test_role_matrix_governance_dashboard.py` — the full
      role matrix across this spec's P1 write/read surfaces (resources read, finding acknowledge,
      finding suggestion read/write): admin-only write on suggestion-seed, admin/operator write on
      acknowledge, all-role read everywhere, explicitly asserting a non-admin/non-operator write
      attempt is refused rather than inferred from success. **P2's scan-operations role gating
      (FR-021–FR-023) is deliberately excluded** — that surface doesn't exist yet, Phase 8 — S27–S30,
      FR-027, FR-028, FR-028a
      **Done**: 19 tests, all pass against real PostgreSQL. `test_seed_finding_suggestion` explicitly
      asserts operator (not just viewer) is refused — the pattern this task called out by name.
- [X] T032 **Live-verification.** Deploy this spec's work to dev (dispatch `Deploy dev` manually,
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
      accounts) — and record SC-002–SC-007 as proven at the mocked-test level only (SC-002
      depends on V3–V6 exactly as much as SC-003–SC-007 do), the same
      honest-outcome pattern specs 002/003 both landed on. Do not re-litigate the NAT/VPC-endpoint
      cost tradeoff a third time without a new signal from the user — S27–S30, SC-001–SC-002,
      SC-003–SC-007
      **Resumed 2026-09-01 on explicit user instruction** ("run T032 live verification against real
      dev") — the standing deferral above was correct until that direct signal arrived; this is not
      a re-litigation, it is the new signal the deferral itself said to wait for.
      **T032a — real bug found live, not by inspection**: the first `Deploy dev` dispatch
      (run 33553645364) completed, but its own T041 smoke-suite step failed —
      `dashboard-smoke.spec.ts`'s `e2eMockRole` bypass never took effect against the real deployed
      site. Root cause: the runtime-config injection script (T003/R-401) does a bare
      `window.__CLOUDPULSE_CONFIG__ = {...}` assignment, which silently wipes out whatever a
      Playwright `addInitScript` set on the same object *before* this script runs — the mock role
      was set, then immediately overwritten by the real config, so `authGuard` saw no session and
      redirected to sign-in. Reproduced locally byte-for-byte first (a real `ng build` + the exact
      injection script + `npx serve -s` with SPA fallback, old script fails, fixed script passes)
      before trusting the fix enough to redeploy — confirmed the root cause, not just the symptom.
      Fixed in `deploy-dev.yml` and `deploy-prod.yml` (mirrored, T003's own precedent, even though
      prod never sets `e2eMockRole`): `Object.assign({}, window.__CLOUDPULSE_CONFIG__, {...})`
      instead of a bare replace, so a pre-existing key survives and real values still win on every
      key they actually set — S27, research.md R-401
      **T032b — a second, more severe real bug, found by continuing V1 in an actual browser after
      the redeploy**: the smoke suite (mocked) passed, but a real sign-in attempt did not. Three
      real Cognito users created (`admin-create-user`/`admin-set-user-password --permanent`/
      `admin-add-user-to-group`, one per role, matching spec 001 quickstart's own established
      procedure) and used to sign in through the actual Hosted UI in a real browser. The dashboard's
      root page never rendered — the browser tab itself reported no document loaded. Root cause,
      confirmed by comparing the raw HTTP response (healthy) against actual browser behavior (not
      guessed): `SignInComponent.ngOnInit()` fires `window.location.href =
      https://${config.domain}/oauth2/authorize?...` immediately on mount (no click required, per
      its own docstring), and `config.domain` was `aws_cognito_user_pool_domain.this.domain` — the
      Cognito domain *prefix* only (e.g. `cloudpulse-dev-767828743440`), not a resolvable host. The
      real Hosted UI host is that prefix plus `.auth.<region>.amazoncognito.com` (confirmed via
      `aws cognito-idp describe-user-pool-domain` and a direct `curl` against both forms — the
      prefix alone doesn't resolve, the full form 302s to `/login` for real). The browser committed
      to leaving the document for the bogus host and landed on an error page, which is why nothing
      rendered — the same `window.location.href`-always-commits behavior this session's own T004
      note already documented for a *different* symptom (sign-out), now the same root mechanism
      surfacing a second, far more severe way: **this broke every real sign-in this platform has
      ever offered, since spec 001 first built the Hosted UI redirect** — invisible until now
      because no live-verification session before this one ever completed a real browser sign-in
      (T003a's own finding already established that no session had even loaded the deployed SPA;
      this is the next layer down that stayed hidden once that was fixed). Fixed at the source,
      `infra/modules/identity/outputs.tf`'s `hosted_ui_domain` output (not scattered across every
      frontend consumer): now returns the full FQDN via a new `data "aws_region" "current"` lookup,
      matching every other module's own existing pattern for this (`scan`/`governance`/`network`/
      `api` all already do this). `sign-in.component.ts`/`auth.service.ts` needed no change — they
      already expected to consume a directly-usable host. This is spec 001's bug, not spec 004's,
      but T032 is where it was found and where the honest record belongs — S27, spec 001 FR-001,
      research.md (new note, spec 004's own R-408)
      **T032c — a third real bug, found continuing V1 after T032b's redeploy**: the Hosted UI
      redirect and real sign-in itself now worked (a genuine login form, real credentials
      accepted), but the callback showed "Sign-in failed." The browser console showed the actual
      cause directly, not guessed: a CORS preflight failure on `GET /me` -- "Response to preflight
      request doesn't pass access control check: It does not have HTTP ok status." A direct `curl
      -X OPTIONS` against `/me` confirmed it: API Gateway's `cors_configuration` decorates *every*
      response, including this one, with correct CORS headers -- but the response itself was a 405
      from the FastAPI app, because the `$default` route (every path, per its own comment) has a
      custom authorizer attached, so the preflight is proxied through to the Lambda rather than
      short-circuited by API Gateway, and Starlette has no `OPTIONS` handler registered on any
      route. A 405 preflight fails browser CORS regardless of which headers are attached to it --
      this is the same class of platform-wide bug as T032b, affecting every authenticated request
      the dashboard (or any future spec's frontend) will ever make, not just `/me`. Fixed with
      `fastapi.middleware.cors.CORSMiddleware`, added in `app/api/main.py` when
      `CLOUDPULSE_FRONTEND_URL` is set (new Lambda env var, `infra/modules/api/main.tf`, reusing
      `var.allowed_origins[0]` -- the exact value `cors_configuration` already restricts to, not a
      second source of truth). Read directly via `os.environ`, not `get_settings()`: several unit
      tests construct `create_app()` with no database/Cognito environment configured at all, and
      routing the CORS check through the full `Settings` model would have forced every one of them
      to fully configure an environment they don't otherwise need -- caught by running the full
      suite after the first draft, which failed six tests on `Settings` validation errors it hadn't
      before. 3 new tests (`test_cors_preflight.py`): preflight succeeds from the configured
      origin, is refused from an unconfigured one, and (documenting the pre-fix baseline) no CORS
      handling is added at all when `CLOUDPULSE_FRONTEND_URL` is unset. Full backend suite re-run
      clean — S27, spec 001 FR-047 (as amended -- FR-047 already required this; it was simply
      unmet), research.md (new note, spec 004's own R-409)
      **Final result, after T032a/b/c's fixes redeployed**: V1 fully confirmed live, all three
      roles — real Cognito sign-in via the actual Hosted UI (admin/operator/viewer, one user each),
      role-based control gating on the Accounts screen (viewer and operator both see a disabled
      "Register an account" control with the correct disclaimer text; admin sees it enabled),
      sign-out through real Cognito `/logout` confirmed to end the session, and unauthenticated
      direct URL access confirmed to redirect to real sign-in. V2 confirmed as a side effect of V1
      — Overview/Findings/Accounts/Scan-operations all rendered explicit, non-blank empty states
      with zero connected accounts. **V3–V8 remain unproven live** — R-407's VPC-networking gap
      (account registration hangs to Lambda's 30s timeout) was still open and was not re-litigated
      a third time without a new user signal; SC-002–SC-007 stay proven at the mocked-test level
      only, same honest-outcome pattern as before. Three real, previously-invisible production bugs
      (T032a/b/c) were found and fixed only because this session actually drove a real browser
      against the real deployed system rather than trusting mocked coverage.
- [X] T033 **Teardown and cost sweep**, immediately following T032, never separated from it by
      other work: run the full playbook §0.5.3 sweep. Research.md R-406 states this spec adds zero
      new billable AWS resources, so there is no spec-004-specific sweep addition the way R-306
      needed one for tag compliance and ownership's new SQS queues — the generic checklist is the
      complete one here — S27–S30, playbook §0.5.3
      **Done, immediately after T032 per the adjacency rule.** `ops/teardown.sh dev` ran
      (83 resources planned: RDS, VPC, Lambda, Cognito pool, CloudFront, S3). It exited 0 but was
      not actually clean — see T033a. After T033a's fix, the full sweep confirmed zero of: RDS
      clusters/snapshots, Lambda functions, non-default VPCs, NAT gateways, EC2 instances, ELBs,
      EIPs, CloudFront distributions, Cognito user pools, API Gateway APIs, Step Functions, SQS
      queues, SNS topics, EventBridge rules, CloudWatch alarms, and orphaned (no-retention) log
      groups. Only the two `cloudpulse-tfstate-*` buckets remain, which is expected — they hold
      Terraform state for both environments and are outside `infra/envs/dev`'s blast radius. The
      three Cognito test users provisioned for T032 (`admin`/`operator`/`viewer@cloudpulse-t032-
      verify.test`) were destroyed along with the pool; no separate cleanup was needed.
- [X] T033a A fix T033 itself surfaced, not anticipated by this list: `terraform destroy` failed
      on `module.frontend.aws_s3_bucket.origin` with `BucketNotEmpty` (the bucket always holds a
      deployed build) but `ops/teardown.sh` reported success anyway (`[exited with code 0]`), which
      would have left a real dev S3 bucket running indefinitely after every future teardown had
      this gone unnoticed. Found by diffing the sweep's live bucket list against the destroy log,
      not by trusting the exit code. Emptied the bucket by hand (`aws s3 rm --recursive`) and
      completed the destroy (`terraform destroy` targeted at the one remaining resource) to finish
      T033. Root-cause fix in `infra/modules/frontend/main.tf`: `force_destroy =
      var.environment != "prod"` — dev's bucket always holds a deployed build and destroy must be
      able to clear it; prod's must never be auto-emptied. `terraform fmt`/`validate` clean — S27,
      playbook §0.5.3

**Checkpoint**: 🏁 **P1 complete. Live-verification (T032/T033) run against the real dev
account: V1/V2 confirmed live, V3–V8 still blocked by R-407, one real teardown bug
(T033a) found and fixed.**

---

## Phase 8: User Story 5 — Trigger and track a scan without leaving the dashboard (Priority: P2)

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise a P1 path. If
this phase is dropped entirely, Phases 1–7 still satisfy every P1 success criterion (SC-008
excepted, per the Tier Summary above). Reuses account onboarding and discovery's existing
on-demand-scan and scan-history APIs entirely — this story adds no new scanning mechanism, only
the screen that surfaces what already exists, plus one small, additive response-shape extension
(research.md R-405). **Amended by T036a**: this spec's own FR-022 turned out to require widening
*who* can call the existing trigger endpoint (admin+operator, not operator-only) — a real,
user-approved change to spec 002's shipped role gating, not merely a new screen over unchanged
capability. See T036a for the full account.

### Tests for User Story 5

- [X] T034 [P] [US5] **[P2]** Write `backend/tests/unit/test_scan_deltas.py` — the `added`/
      `removed`/`changed` fields (research.md R-405) are computed correctly from
      `resource.first_seen_at`/`last_seen_at`/`deleted_at` against a scan's
      `[started_at, finished_at]` window, with no new persisted state — S31, FR-021, research.md
      R-405
      **Done**: `app/governance/scan_deltas.py`'s `compute_scan_deltas` extracted as a pure function
      (mirrors `scoring.py`'s pure/DB-touching split); 8 tests. One real bug caught by running the
      first draft, not by inspection: a fixture modeled a resource with `last_seen_at` inside the
      scan window AND `deleted_at` set by that same scan -- an impossible combination, since
      `orchestrator.py`'s `sweep_deleted_resources` only ever marks `deleted_at` for a resource
      whose `last_seen_at` predates the scan (not re-confirmed by it). Fixed the fixture, not the
      function.
- [X] T035 [P] [US5] **[P2]** Write `frontend/e2e/scan-operations.spec.ts` — mocked scan-history/
      trigger-scan responses: history shows start time, duration, and deltas (Acceptance Scenario
      US5.1, FR-021); triggering a scan shows a status that updates through to a final state via
      polling (research.md Assumptions), without a manual reload (Acceptance Scenario US5.2,
      FR-022, SC-008); a viewer sees history but has no trigger control (Acceptance Scenario US5.3,
      FR-023) — S31, FR-021–FR-023
      **Done**: 3 tests, all pass in a real Chromium instance. Full e2e suite (37 tests) re-run
      clean.

### Implementation for User Story 5

- [X] T036 [US5] **[P2]** Extend `backend/app/api/routers/accounts.py`'s `list_scan_history` /
      `ScansList` response model — three new, additive, non-required integer fields computed at
      query time per T034/research.md R-405; no new column, no new table. Regenerate
      `backend/openapi.generated.yaml` and the frontend `accounts.service.ts`/
      `accounts.serviceInterface.ts` — T037 depends on the regenerated client exposing the new
      fields — S31, FR-021
      **Done**: deltas computed only once `finished_at` is set (a still-running scan's deltas are
      `null`, not guessed); extended `test_scan_history.py` with a real resource inside the older
      scan's window to prove the wiring end-to-end, not just the pure function in isolation.
- [X] T036a [US5] **[P2]** **Not anticipated by this task list.** Widened `trigger_scan`
      (`backend/app/api/routers/accounts.py`) from operator-only to admin+operator, discovered
      while starting T037: this spec's own FR-022 ("An admin or operator MUST be able to trigger an
      on-demand scan") directly contradicts spec 002's existing FR-026a/research.md R-205
      (operator-only, admin deliberately excluded, a Clarifications-session decision with its own
      dedicated role-matrix test proving admin refused). Flagged to the user rather than silently
      picking a side; resolved as "widen the backend to match spec 004's FR-022" (the alternative
      was leaving FR-022 unmet). `trigger_scan` now depends on the shared `require_operator` alias
      (admin+operator) instead of its own operator-only dependency. Amended in place, not silently:
      spec 002's spec.md (FR-026a, FR-011a's cross-reference), research.md (R-205), and
      quickstart.md (V9's table) all carry a dated amendment note pointing back to this task and
      spec 004's FR-022, rather than being silently rewritten as if the exclusion never existed.
      `test_role_matrix_accounts.py`'s decisive "admin refused" cell flipped to admin=202 with its
      docstring updated to explain why; `test_scan_scheduling.py`'s
      `test_admin_cannot_trigger_an_on_demand_scan` (no-DB unit test, now testing something false)
      removed -- the real-DB role matrix is the correct place for this cell now that admin's request
      reaches `_get_or_404`, not the role gate; its structural guard test inverted to assert the
      route *does* now reuse the shared alias. Full backend suite re-run clean after the fix — S31,
      FR-022 (spec 004); FR-011a, FR-026a (spec 002, as amended)
- [X] T037 [US5] **[P2]** Write `frontend/src/app/features/scans/scan-operations.component.ts` —
      history table with deltas, "Scan now" trigger control (admin/operator only, FR-023), polled
      status until a final state — S31, FR-021–FR-023
      **Done**: lists every connected account (reusing the existing `AccountsService`), expandable
      per-account history, 2s-interval poll (capped at 30 attempts) after triggering until the new
      scan reaches a final status.
- [X] T038 [US5] **[P2]** Wire the `/scans` route into `app.config.ts` — S31, FR-021
      **Done**. Nav link already existed from Phase 3's shell.

**Checkpoint**: P2 stretch scope complete; SC-008 now provable; quickstart.md V8 can be run live as
a follow-up to Phase 7's T032 if desired (not itself re-numbered as a new live-verify task — it
extends the same dev deployment T032/T033 already covered, redeployed if it was torn down).

---

## Phase 9: Hardening (S33) [P2]

- [X] T039 [P2] Write `frontend/e2e/dashboard-smoke.spec.ts` — end-to-end smoke suite covering each
      P1 user story's primary journey in one pass (sign in as each role; view compliance overview;
      filter and drill into inventory; filter, view a suggestion on, and acknowledge a finding) —
      S33, FR-024
      **Done**: 3 tests (one per role), each a full overview → inventory drill-down → findings
      + suggestion (+ acknowledge for admin/operator) pass. "Sign in as each role" reuses the
      established `e2eMockRole` mechanism every other e2e spec in this suite already uses for role
      identity — the real PKCE flow itself stays `auth.spec.ts`'s (T004) job, not duplicated here.
- [X] T040 [P2] Audit pass: confirm every P1 screen (T012, T019/T020, T029) has a defined loading,
      empty, and error state, each visually and behaviorally distinct from the other two (FR-025,
      fixed by this spec's own checklist review to actually require a loading state, not merely
      contrast against one) — fill any gap found, cite the fix against the specific screen and
      state — S33, FR-025
      **Done, two real gaps found and fixed, not by inspection alone but by tracing each screen's
      service layer**: (1) `resource-detail.component.ts` (T020) had a loading state and an
      (implicit, via nested content) empty state, but no error state at all — `InventoryService
      .loadDetail` had no `catch`, so a fetch failure left the loading spinner replaced by nothing,
      a blank panel indistinguishable from "still loading" once the spinner's own condition went
      false. Fixed: added `detailError` signal + `catch`, rendered as `role="alert"`. (2) The
      findings workbench's (T029) inline suggestion panel had the same shape of gap —
      `FindingsService.loadSuggestion` had no `catch`, so a failed suggestion fetch left "Loading
      suggestion…" showing forever, never resolving to a distinct error. Fixed the same way, scoped
      per-finding-id. Both gaps proven fixed with new e2e tests (`inventory-explorer.spec.ts`,
      `findings-workbench.spec.ts`) asserting the alert appears and the stuck spinner does not.
      Overview, inventory list, and findings list already had all three states correctly.
- [X] T041 [P2] Extend `.github/workflows/deploy-dev.yml` — run T039's smoke suite against the real
      dev environment after each successful deploy (FR-026), gated the same way every other
      dev-only step already is — S33, FR-026
      **Done**: new step after the existing backend `/health` smoke test, pointing
      `playwright.config.ts`'s `E2E_BASE_URL` at `terraform output frontend_url` — proves the
      deployed JS bundle and static assets actually boot, route, and render (T003a's own bug was
      exactly this class, caught only by loading a page in a browser), not that a real connected
      AWS account round-trips end-to-end (that stays T032's job, deliberately not duplicated).
      `playwright.config.ts` updated to skip its local `webServer` when `E2E_BASE_URL` is set —
      verified locally by running the suite against a real running origin with no local server
      management, not just read as correct.

**Checkpoint**: P2 hardening complete; the P1 demo path has automated regression coverage running
against real infrastructure after every dev deploy, not only in CI's mocked suite.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [X] T042 [P] Update `backend/README.md`, `frontend/src/app/features/README.md`, and
      `infra/README.md` to describe this spec's new `app/api/routers/resources.py`,
      `app/governance/suggestions.py`, the four new frontend feature areas, and the deploy-time
      runtime-config injection (research.md R-401) — Principle I
      **Done**. Also documented `scan_deltas.py` (T034) alongside `suggestions.py` in
      `backend/README.md`'s `app/governance/` row — both are spec 004 additions to that package,
      and T042's own text only named one of the two.
- [X] T043 Re-run `/speckit-analyze` on spec 004 (playbook §8's second-run note) and resolve any
      finding before spec 005 begins — Governance
      **Done**. One finding (MEDIUM): SC-003 (2-second compliance-overview load at up to 5,000
      resources) had zero test coverage at any level — its only planned verification was T032's
      live-verification, now indefinitely deferred, so it stood entirely unproven. Flagged to the
      user; resolved by adding a synthetic timing test to `compliance-overview.spec.ts` (a
      3,000-open-finding mocked payload, asserting the overview renders within the 2-second budget
      from navigation start) — passes at ~300-500ms. This proves client-side processing isn't the
      bottleneck; it does not and cannot prove real-network/real-AWS latency, which stays T032's
      job. No other finding (0 duplication, 0 ambiguity, 0 constitution violations, 100% FR
      coverage, 7/8 → 8/8 SC coverage after this fix).
- [X] T044 **Not anticipated by this task list — process correction, not spec 004 work.**
      Spec 5 was specified as `005-notification-engine` (PR #94, merged), diverging from
      `SPECKIT_PLAYBOOK.md` §0.4 step 18's own plan (spec 5 = cost-and-utilization, S39/S42)
      without updating the playbook to match — the playbook's §0.3 scope table still listed E6
      Notification Engine as an intentional MVP cut at the same time a whole spec for it was
      merged to trunk. Caught before spec 5's `/speckit-plan` began, corrected rather than
      silently carried forward: `SPECKIT_PLAYBOOK.md` now folds S24/S25 (email + day-0/2/4
      cadence) into spec 5's actual scope alongside cost-and-utilization — a real scope
      decision, not a revert — with a superseded-note trail at §0.3 rather than a silent
      rewrite, and `specs/005-notification-engine/` removed so numbering re-aligns: the next
      `/speckit-specify` lands on `005-cost-and-utilization` as originally planned. PR #94
      stays in git history as the honest record of what was actually built — this task
      documents the correction, not an erasure of it — Governance, §0.1's judged-evidence rule.

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
