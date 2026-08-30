# Feature Specification: Governance Dashboard

**Feature Branch**: `pods/pod73-004-governance-dashboard`

**Created**: 2026-08-31

**Status**: Draft

**Input**: User description: "Give admins, operators, and viewers a single web dashboard where the entire governance story is visible: compliance posture, full inventory, findings with AI-suggested fixes, and scan operations. Functional scope (backlog S27–S31, S33; renders spec 6's suggestions): Authenticated shell (S27) [P1]: sign-in/sign-out against the platform identity service, role-based navigation guards (viewer never sees admin pages), responsive layout shell. Compliance overview (S28) [P1]: score cards, findings by type/severity charts, and a per-account summary table; numbers always match the API; loads under 2 seconds at 5,000 resources. Inventory explorer (S29) [P1]: server-side paged and filtered table (account, service, region, tag status, SDA), with a resource detail panel showing tags, owner + evidence, findings, and enrichment detail; filter \"missing owner tag\" returns the correct set. Findings workbench (S30) [P1]: list/filter findings, acknowledge them, and see each finding's AI remediation suggestion with its blast-radius note (produced by the ai-insights-agent spec) inline; acknowledging updates status immediately. Scan operations (S31) [P2]: scan history page (last run, duration, deltas) and an on-demand \"Scan now\" button with live status. Hardening (S33) [P2]: end-to-end smoke tests for the P1 journeys, empty/error states, deployment polish; e2e runs in CI against dev after each deploy. Success criteria: a viewer, operator, and admin each see exactly their permitted surface; the full demo path (onboard → scan → findings + suggestions → acknowledge) is walkable end-to-end in the UI without console access. Out of scope: notification bell/feed (cut), approval workflows (no remediation execution in MVP), cost and utilization pages (spec 5), agent chat interfaces."

## Clarifications

### Session 2026-08-31

- Q: Does the demo path's "findings + suggestions" step (SC-002) need to show an actual
  populated AI suggestion, even though the AI-insights spec that generates them doesn't
  exist yet? → A: Add a minimal, admin-only mechanism to seed a demo/QA test suggestion
  and blast-radius note on a finding — explicitly test tooling, not real AI generation —
  so FR-018's populated-display path is provable in this spec's own P1 demo path, not
  left permanently unverified until a later spec ships.

## User Scenarios & Testing *(mandatory)*

<!--
  Priority labels below use the CloudPulse AI constitution's tier semantics (Principle VIII):
  P1 = demo-critical, frozen scope; P2 = stretch, must never block or destabilise a P1 path.
  Stories are listed in dependency order within each tier, not in order of relative importance.
-->

### User Story 1 - Sign in and see only what my role permits (Priority: P1)

A person visiting the platform signs in once, using the identity the platform already
issued them, and lands in a shell that shows navigation appropriate to their role — an
admin sees every screen and every management control; an operator sees everything except
admin-only configuration; a viewer sees every governance view but no control that would
change anything. The shell works on a phone, a tablet, or a desktop without a separately
built mobile experience.

**Why this priority**: Nothing else in this spec is reachable without a signed-in session
and a navigation surface to reach it from — every other user story assumes this exists.

**Independent Test**: Sign in as each of the three roles in turn and confirm each one's
navigation contains exactly the screens and controls that role is permitted to use, no
more and no less; sign out and confirm the next page load requires signing in again.

**Acceptance Scenarios**:

1. **Given** a valid platform identity, **When** a person signs in, **Then** they land in
   the dashboard shell with navigation reflecting their role.
2. **Given** a signed-in viewer, **When** they view the navigation, **Then** no
   admin-only management control (rule editing, SDA management, identity-pattern
   configuration) is presented as available to them.
3. **Given** no signed-in session, **When** a person requests any dashboard page directly
   by URL, **Then** they are redirected to sign in rather than shown any governance data.
4. **Given** a signed-in session, **When** the person signs out, **Then** the session ends
   and the next page load requires signing in again.
5. **Given** the dashboard open on a narrow (phone-width) viewport, **When** a person
   navigates it, **Then** every P1 screen remains usable — readable and operable — without
   horizontal scrolling of the page itself.

---

### User Story 2 - See compliance posture at a glance (Priority: P1)

A signed-in person opens the dashboard and immediately sees the organization's compliance
posture: an overall score, a score per connected account, and a breakdown of open findings
by type and severity. Every number shown is the same number the platform's own API would
return for the same query — the dashboard never computes its own version of a governance
number.

**Why this priority**: This is the first thing anyone lands on after signing in, and it is
the spec's namesake "at a glance" promise — without it, the dashboard is a pile of
individually-useful screens with no unifying view of governance health.

**Independent Test**: With a test account carrying a known, hand-countable mix of
compliant and non-compliant resources, open the overview and confirm every score and count
shown matches the corresponding API response exactly.

**Acceptance Scenarios**:

1. **Given** one or more connected accounts with scored compliance, **When** the overview
   loads, **Then** it shows an overall score and each account's own score, each matching
   that account's `compliance-score` API response exactly.
2. **Given** open findings across several severities and violation types, **When** the
   overview loads, **Then** it shows a breakdown by type and by severity whose counts sum
   to the total open-finding count the findings API reports.
3. **Given** an account with no resources yet scanned, **When** the overview includes that
   account, **Then** it shows a well-defined "no data yet" state for that account's row,
   not an error or a blank space.
4. **Given** an account with up to 5,000 resources, **When** the overview is requested,
   **Then** it finishes loading within 2 seconds.

---

### User Story 3 - Explore the full inventory and drill into one resource (Priority: P1)

A signed-in person browses every discovered resource across every connected account in a
single table — filterable by account, service, region, tag-compliance status, and SDA —
without the platform ever loading the whole inventory into the browser at once. Selecting
any one resource opens a detail view showing its tags, its attributed owner and the
evidence behind that attribution, its findings, and the enrichment detail already captured
about it.

**Why this priority**: Compliance scores and findings describe *aggregate* state; a real
governance conversation ("whose bucket is this, why is it flagged, who touched it last")
needs the ability to go from a number down to one specific resource. Without this, the
dashboard can show that a problem exists but never let anyone find the resource it's
attached to.

**Independent Test**: With a test account containing resources in a known mix of tag
states, filter the inventory to "missing owner tag" and confirm the result set exactly
matches which resources genuinely lack an attributed owner; open one resource's detail
panel and confirm its tags, owner/evidence, findings, and enrichment detail all match what
the underlying APIs report for that resource.

**Acceptance Scenarios**:

1. **Given** resources spread across several accounts, services, and regions, **When** a
   person filters the inventory by any combination of account/service/region/tag-status/
   SDA, **Then** only resources matching every applied filter are shown.
2. **Given** the "missing owner tag" filter is applied, **When** results are returned,
   **Then** every resource shown genuinely has no attributed owner, and no resource with
   an attributed owner is included.
3. **Given** a large inventory, **When** a person pages through results, **Then** each page
   is fetched from the platform as needed rather than the full inventory being loaded into
   the browser up front.
4. **Given** any one resource in the inventory, **When** a person opens its detail panel,
   **Then** it shows that resource's tags, attributed owner with evidence (or "unattributed"
   if none exists), its findings, and its enrichment detail.

---

### User Story 4 - Triage findings and act on AI-suggested fixes (Priority: P1)

A signed-in admin or operator works through the list of open findings, filtering it down to
what they care about, and for each finding sees whatever AI-generated remediation
suggestion and blast-radius note the platform has produced for it, shown inline with the
finding itself. When they've reviewed a finding and decided it's being handled, they mark
it acknowledged, and that status is reflected immediately — no page reload, no stale state.
Because the capability that actually generates a suggestion is a later spec, an admin can
also attach a demo/QA test suggestion and blast-radius note directly to a finding — clearly
marked as test data, never presented as a real platform-generated recommendation — so this
story's suggestion-display behavior is provable now rather than staying permanently
unverified until that later spec ships.

**Why this priority**: Findings are the spec's namesake "namesake capability" once
compliance posture (User Story 2) has already said something is wrong; this is where a
person actually works the list down. It is P1 because the demo's own success criterion —
walking onboard → scan → findings + suggestions → acknowledge end-to-end — has no meaning
without this screen existing.

**Independent Test**: Open the findings list, filter it to a known subset, confirm exactly
that subset is shown; acknowledge one finding and confirm its acknowledged state is
reflected immediately without a manual refresh; confirm a finding with a
platform-generated suggestion shows that suggestion and blast-radius note inline, and a
finding with none shows a clear "no suggestion available" state rather than an error.

**Acceptance Scenarios**:

1. **Given** open findings of varying type, severity, and account, **When** a person
   filters the list, **Then** only findings matching the applied filters are shown.
2. **Given** an open finding an admin or operator selects to acknowledge, **When** they
   acknowledge it, **Then** its acknowledged state is reflected in the list immediately,
   without requiring a manual page refresh.
3. **Given** a finding for which the platform has produced an AI remediation suggestion and
   a blast-radius note, **When** the finding is shown, **Then** the suggestion and its
   blast-radius note are displayed inline with it.
4. **Given** a finding for which no AI remediation suggestion has been produced yet,
   **When** the finding is shown, **Then** a clear "no suggestion available" state is
   displayed instead of an error, a blank space, or a broken-looking layout.
5. **Given** a viewer (not admin or operator), **When** they view the findings workbench,
   **Then** they can see every finding and its suggestion, but have no control available to
   acknowledge one.
6. **Given** an admin attaching a demo/QA test suggestion to a finding, **When** it is
   saved, **Then** it displays inline exactly as a platform-generated suggestion would
   (Acceptance Scenario 3), visibly marked as test data, and **When** a non-admin views the
   same finding, **Then** they see the suggestion but have no control to attach or edit one.

---

### User Story 5 - Trigger and track a scan without leaving the dashboard (Priority: P2)

An admin or operator sees each connected account's scan history — when it last ran, how
long it took, and what changed — and can start a new scan on demand, watching its status
until it finishes, all without leaving the dashboard or touching the AWS console or a raw
API client.

**Why this priority**: Every other story in this spec already works against inventory,
findings, and scores that some previous scan produced; nothing here requires the
*triggering* of a scan to happen inside the dashboard itself for those stories to be
demonstrable. It is P2 because it closes the loop — "onboard → scan → findings" becomes
fully console-free — but the demo path already has a scan to work from either way.

**Why this priority (continued)**: Reuses account onboarding and discovery's own existing
on-demand-scan and scan-history capabilities entirely — this story adds no new backend
capability, only the screen that surfaces what already exists (see Dependencies).

**Independent Test**: Open an account's scan history, confirm it shows its most recent
scan's timing and resulting deltas; trigger a new scan, and confirm its status is visible
and updates until the scan completes, without needing to reload the page manually.

**Acceptance Scenarios**:

1. **Given** an account with prior scans, **When** its scan history is viewed, **Then** it
   shows each scan's start time, duration, and the resource deltas (added/removed/changed)
   it produced.
2. **Given** an admin or operator viewing a connected account, **When** they trigger an
   on-demand scan, **Then** its status becomes visible and updates until the scan reaches a
   final state, without a manual page reload.
3. **Given** a viewer viewing a connected account, **When** they view its scan operations
   screen, **Then** they can see its history, but no control to trigger a new scan is
   available to them.

---

### Edge Cases

- **A finding's AI remediation suggestion has not been generated yet (true for most
  findings until the AI-insights capability that produces them exists — a demo/QA
  test suggestion attached via FR-020a is the documented exception)**: this is the
  normal, expected state, not an error — User Story 4's "no suggestion available" state
  applies, not a loading spinner or a failure banner.
- **A person's role permits reading a page but not acting on it** (a viewer on the
  findings workbench or scan-operations screen): the page renders fully; only the
  write-side control (acknowledge, trigger scan) is unavailable to them.
- **A filtered inventory or findings query matches zero results**: a clear "no matching
  resources/findings" state is shown, distinct from a loading state or an error.
- **The platform API is unreachable or returns an error for a given screen**: that screen
  shows an explicit error state with the option to retry, never a silently stale or blank
  screen presented as if it were current data.
- **Two people acknowledge the same finding at nearly the same time**: the finding ends up
  acknowledged exactly once; the second acknowledgment attempt does not error or create a
  duplicate acknowledgment record.
- **An account has never been scanned**: its compliance-overview row, inventory results,
  and scan-history page all show an explicit "not yet scanned" state rather than treating
  the absence of data as zero compliant resources or an error.
- **A resource has no attributed owner** (queued unattributed, per account onboarding and
  discovery / tag compliance and ownership's own documented behavior): the inventory
  detail panel shows this plainly ("unattributed") rather than an empty field that looks
  like a loading failure.

## Requirements *(mandatory)*

### Functional Requirements

#### Authenticated shell (S27) [P1]

- **FR-001**: The dashboard MUST let a person sign in and sign out using the platform's
  existing identity service — no new identity provider or credential store.
- **FR-002**: An unauthenticated request for any dashboard page MUST be redirected to
  sign-in rather than shown any governance data.
- **FR-003**: Navigation MUST reflect the signed-in person's role: a control whose only
  purpose is a write action a role cannot perform, or a page with no content a role is
  permitted to see, MUST NOT be presented in that role's navigation.
- **FR-004**: The dashboard's layout MUST remain usable — readable and operable, no
  horizontal scrolling of the page itself — across common phone, tablet, and desktop
  viewport widths, for every P1 screen.
- **FR-005**: Signing out MUST end the session such that a subsequent page load requires
  signing in again.

#### Compliance overview (S28) [P1]

- **FR-006**: The overview MUST show an overall compliance score and a per-account score,
  each equal to the same account's/tenant's `compliance-score` API result — never a
  value independently computed by the dashboard.
- **FR-007**: The overview MUST show open findings broken down by violation type and by
  severity, with counts that sum to the platform's total open-finding count.
- **FR-008**: The overview MUST show a per-account summary table (account identity,
  compliance score, resource count, open finding count).
- **FR-009**: An account with no completed scan MUST be shown with an explicit "not yet
  scanned" state in the overview, not a zero score or an error.

#### Inventory explorer (S29) [P1]

- **FR-010**: The inventory MUST be filterable by account, service, region, tag-compliance
  status, and SDA, in any combination, returning only resources matching every applied
  filter.
- **FR-011**: The inventory MUST be paged and filtered server-side — the platform MUST NOT
  require loading the full inventory into the browser to page or filter it.
- **FR-012**: Selecting a resource MUST open a detail view showing its tags, its
  attributed owner and the evidence behind that attribution (or an explicit
  "unattributed" state), its findings, and its captured enrichment detail.
- **FR-013**: A "missing owner tag" filter MUST return exactly the resources genuinely
  lacking an attributed owner — no resource with an attributed owner included, no
  unattributed resource excluded.

#### Findings workbench (S30) [P1]

- **FR-014**: Findings MUST be listable and filterable by status, severity, violation
  type, account, SDA, and resource.
- **FR-015**: An admin or operator MUST be able to acknowledge an open finding; its
  acknowledged state MUST be reflected in the list immediately, without requiring a
  manual page reload.
- **FR-016**: Acknowledging a finding MUST record who acknowledged it and when, as an
  auditable action, consistent with the platform's existing audit-record requirement for
  every state-changing operation.
- **FR-017**: Acknowledging a finding MUST NOT change its open/resolved status and MUST
  NOT affect any compliance score — it is a human triage signal, not a resolution.
- **FR-018**: When a finding has a platform-generated remediation suggestion and
  blast-radius note available, the workbench MUST display both inline with the finding.
- **FR-019**: When a finding has no remediation suggestion available yet, the workbench
  MUST show an explicit "no suggestion available" state rather than an error, a blank
  space, or a loading state that never resolves.
- **FR-020**: Acknowledging the same finding a second time (including a near-simultaneous
  second attempt) MUST NOT error and MUST NOT create more than one acknowledgment record
  for that finding.
- **FR-020a**: An admin MUST be able to attach a demo/QA test suggestion and blast-radius
  note directly to a finding, for use before the platform's own AI-generated suggestions
  exist; a suggestion attached this way MUST display exactly as a platform-generated one
  would (FR-018), visibly marked as test data, and MUST NOT be presented as a genuine
  platform recommendation (Clarifications, Session 2026-08-31).

#### Scan operations (S31) [P2]

- **FR-021**: An account's scan-operations screen MUST show its scan history — each
  scan's start time, duration, and resulting resource deltas. **[P2]**
- **FR-022**: An admin or operator MUST be able to trigger an on-demand scan for a
  connected account from the dashboard, and see its status update until the scan reaches
  a final state, without a manual page reload. **[P2]**
- **FR-023**: A viewer MUST be able to see an account's scan history but MUST have no
  control available to trigger a new scan. **[P2]**

#### Hardening (S33) [P2]

- **FR-024**: End-to-end smoke tests MUST cover each P1 user story's primary journey
  (sign in as each role; view compliance overview; filter and drill into inventory; filter,
  view a suggestion on, and acknowledge a finding). **[P2]**
- **FR-025**: Every P1 screen MUST have a defined empty state (no data yet) and error state
  (platform API unreachable or erroring), distinct from each other and from a loading
  state. **[P2]**
- **FR-026**: The end-to-end smoke suite MUST run in CI against the dev environment after
  each deploy to dev. **[P2]**

#### Access control

- **FR-027**: Viewing the compliance overview, inventory explorer, findings workbench (
  including any AI suggestion shown on a finding), and scan history MUST be permitted for
  all three roles — admin, operator, and viewer.
- **FR-028**: Acknowledging a finding and triggering an on-demand scan MUST be restricted
  to the admin and operator roles; a viewer MUST NOT be able to perform either action,
  consistent with account onboarding and discovery's existing operator-may-act,
  viewer-read-only precedent.
- **FR-028a**: Attaching a demo/QA test suggestion to a finding (FR-020a) MUST be
  restricted to the admin role — an operator or viewer MUST NOT have this control
  available, consistent with tag compliance and ownership's existing precedent that
  configuration-shaped actions are admin-only.

### Key Entities *(include if feature involves data)*

- **Finding Acknowledgment**: a record of who acknowledged an open finding and when,
  attached to the existing `Finding` entity (tag compliance and ownership) as metadata
  parallel to its existing resolved-at timestamp — orthogonal to the finding's own
  open/resolved lifecycle, never itself changing that lifecycle or any compliance score.
- **Remediation Suggestion**: the fix suggestion and blast-radius note for one finding.
  In its real, permanent form it is produced and populated by the AI-insights capability
  (a later spec) and merely displayed here. Until that capability exists, this spec also
  lets an admin attach a suggestion directly (FR-020a) — the same entity and display path,
  visibly marked as test data rather than a genuine platform recommendation (Clarifications,
  Session 2026-08-31) — so this spec does not depend on that later spec to prove its own
  suggestion-display behavior. Modeled as its own entity tied to one finding, the same way
  an attributed owner is its own entity tied to one resource rather than columns bolted
  onto the resource itself.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A viewer, an operator, and an admin, each signed in separately, each see
  exactly the screens and controls their role permits — no role sees a control it cannot
  use, and no role is missing a view it is entitled to.
- **SC-002**: The full demo path — onboard an account, scan it, review findings including
  at least one showing a populated suggestion (real or admin-seeded test data per
  FR-020a), acknowledge one — is walkable end-to-end through the dashboard alone, with no
  AWS console access and no raw API client.
- **SC-003**: The compliance overview loads within 2 seconds for an account with up to
  5,000 resources.
- **SC-004**: Every score and count the dashboard displays exactly matches the
  corresponding platform API response for the same query, on every check.
- **SC-005**: A "missing owner tag" inventory filter returns exactly the resources that
  genuinely lack an attributed owner, verified against a hand-counted test account.
- **SC-006**: Acknowledging a finding is reflected in the findings workbench within the
  same interaction — no manual page refresh needed to see the updated state.
- **SC-007**: A finding with no remediation suggestion yet available always shows a clear,
  non-error "no suggestion available" state — never an error, a blank space, or a
  perpetual loading indicator.
- **SC-008**: An on-demand scan triggered from the dashboard shows a status that updates
  through to a final state without a manual page reload.

## Assumptions

- **The platform identity service is the one specs 1–3 already established** (sessions
  carrying admin/operator/viewer roles); this spec adds no new identity provider,
  credential type, or role.
- **"Navigation guard" means a role never sees a screen or control it has no permitted use
  for, not a second, coarser access-control layer on top of specs 2–3's existing
  per-endpoint role rules.** Where an existing endpoint already permits all-role read
  (compliance scores, findings, ownership, findings' suggestions), the corresponding
  dashboard screen is visible to every role; where an endpoint is already admin- or
  operator-only, only the dashboard control that calls it is restricted — the same
  disabled-not-hidden precedent tag compliance and ownership's own admin screens
  established, applied consistently rather than inventing a stricter rule here.
- **Acknowledging a finding is a human triage signal, not a resolution**, deliberately
  orthogonal to the deterministic open/resolved lifecycle and scoring formula tag
  compliance and ownership already built and tested — keeping compliance scoring
  reproducible from account state alone (Principle IV) rather than letting a subjective
  "someone looked at it" flag participate in it.
- **A finding's real, AI-generated remediation suggestion legitimately does not exist for
  any finding until the AI-insights capability (a later spec) is built and has run** —
  FR-019's "no suggestion available" state is the normal, expected case for most findings
  even after this spec ships. Resolved by Clarifications (Session 2026-08-31): this spec
  does not sit idle waiting on that later spec for its own demo path to be provable —
  FR-020a's admin-seeded test suggestion exercises the exact same display path (FR-018)
  now, visibly marked as test data so it is never confused with a genuine recommendation.
- **"5,000 resources" (SC-003) is a single connected account's resource count**, matching
  tag compliance and ownership's own established demo-scale framing (a handful of
  connected accounts, tens of thousands of resources in the largest one).
- **A scan's "live status" (User Story 5) is delivered by polling the existing scan-status
  API at a short interval, not a new push/streaming channel** — no part of the platform's
  stack (specs 1–3) uses one today, and polling is a standard, sufficient default at this
  demo scale.
- **Mobile support means a responsive layout that remains usable on a phone-width
  viewport, not a separately built native or mobile-optimized experience.**

## Dependencies

- Account onboarding and discovery's connected-account, resource-inventory, on-demand-scan,
  and scan-history APIs are what the inventory explorer and scan-operations screens read
  from and act on — this spec adds no new scanning, discovery, or scan-triggering
  capability of its own, only the screens that surface what already exists.
- Tag compliance and ownership's rule/finding/compliance-score/SDA/ownership APIs are what
  the compliance overview, inventory detail panel, and findings workbench read from — this
  spec introduces no new validation, scoring, or attribution logic.
- Platform foundation's identity service, role model, and OpenAPI-generated frontend
  client are reused directly for authentication, role gating, and every API call this
  dashboard makes.
- The AI-insights capability (a later spec) is what will populate the Remediation
  Suggestion entity's content for real, at scale, across every finding; this spec depends
  on it only for that — its own P1 demo path is fully provable without it, via FR-020a's
  admin-seeded test suggestion (Clarifications, Session 2026-08-31).

## Out of Scope

- A notification bell or activity feed — cut from this spec's scope entirely.
- Any approval workflow or execution of a remediation — this spec displays a suggested fix
  and lets a person acknowledge a finding; it never applies a change to a scanned account.
- Cost or utilization pages of any kind — owned by a later spec.
- Any agent chat interface — this spec surfaces an already-produced suggestion inline with
  its finding, never an interactive conversation with an agent.
