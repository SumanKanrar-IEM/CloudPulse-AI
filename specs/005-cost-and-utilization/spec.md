# Feature Specification: Cost, Utilization, and Notifications

**Feature Branch**: `005-cost-and-utilization`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Add the financial-control dimension: what is each SDA/project
spending, are budgets being respected, how well utilized are sandbox accounts, where is IAM
hygiene rotting — and make sure a human actually hears about it when a finding needs their
attention, not just when they happen to look at the dashboard. Functional scope (backlog
S39–S42, S54–S56, S24, S25): spend ingestion, cost dashboard, owner email notification,
notification cadence, auto-budgets, overrun findings, sandbox utilization, IAM hygiene."

## Clarifications

### Session 2026-09-02

- Q: For sandbox utilization (User Story 6), what should "used" mean, given that CloudWatch-style
  metrics collection (backlog S50) is explicitly R3 and not in this spec's scope? → A: Used =
  resource in an active/running state (existing `Resource.state` data from spec 002); no new
  metrics dependency.
- Q: When a day's spend ingestion fails outright, what should happen? → A: Retry automatically;
  a day still missing after retries shows as an explicit gap on the dashboard, never guessed or
  zeroed.
- Q: When a project's spend crosses its 80% budget warning threshold, does that trigger a
  notification? → A: No — 80% is dashboard-visible only; only crossing 100% (the overrun finding,
  User Story 5) triggers the email/cadence machinery.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See where the money is actually going (Priority: P1)

An admin or finance stakeholder needs to know what every project/SDA is spending, broken down
by account and service, without pulling it by hand from the cloud provider's own console. Daily
spend is ingested into the governance store and surfaced on a cost dashboard with trend charts
and drill-down from an org-wide total down to a single resource's own spend.

**Why this priority**: Nothing else in this spec — budgets, overrun findings, utilization — means
anything without a trustworthy spend feed underneath it. It's the foundation the rest of this
spec's P2 scope builds on, and it's independently valuable on day one even with nothing else
built yet.

**Independent Test**: Let a day's spend ingest for a test account, then confirm the cost
dashboard's total for that account/day matches the cloud provider's own cost console within the
success-criteria tolerance, and that drilling from the org total down to one resource lands on a
number consistent with the total.

**Acceptance Scenarios**:

1. **Given** a registered account with tagged resources, **When** a day completes, **Then** that
   day's spend, broken down by project tag, account, and service, is ingested into the
   governance store.
2. **Given** ingested spend data, **When** an admin opens the cost dashboard, **Then** they see
   spend by project/SDA/environment with a trend chart and a table matching the ingested totals.
3. **Given** the org-wide cost total on the dashboard, **When** an admin drills down through a
   project to an account to a single resource, **Then** the resource-level figure they land on is
   consistent with (a real contributor to) the totals above it at every level of the drill-down.

---

### User Story 2 - A resource owner learns their resource has a compliance problem (Priority: P1)

An engineer owns a resource that a scan just flagged (spec 003's finding types — missing tag,
invalid value, non-standard format; this spec's own budget-overrun finding, User Story 5). Today
that finding is visible only if someone goes looking on the dashboard (spec 003 deliberately cut
owner notification from its own MVP). This story closes that gap: the owner receives an email
the same day the finding opens, naming the resource, the problem, and a link straight into the
dashboard's finding detail.

**Why this priority**: Without this, every finding this platform can open or display is invisible
until someone happens to look — the entire compliance and cost-control program depends on owners
finding out. Nothing else in this feature's notification scope matters if the first email never
arrives.

**Independent Test**: Open a finding on a resource with a resolved owner email (spec 003's
attribution chain) and confirm one email arrives at that address within the success-criteria
window, containing the resource identifier, the violation, and a link that opens directly to that
finding.

**Acceptance Scenarios**:

1. **Given** a resource with a resolved owner email, **When** a scan (or this spec's own
   overrun-finding check) opens a new finding against it, **Then** the owner receives an email
   that day naming the resource, the specific violation, and a deep link to the finding's detail
   page.
2. **Given** a finding's owner email could not be resolved (spec 003's unattributed queue, or an
   SDA with no registered owner), **When** the finding opens, **Then** no email is sent and the
   finding is recorded as unnotifiable rather than silently dropped or retried forever.
3. **Given** an owner with two separate open findings on two different resources, **When** both
   findings open the same day, **Then** the owner receives two distinct emails, each naming its
   own resource and violation, not a single ambiguous combined message.
4. **Given** the deep link in a notification email, **When** the owner (already signed in) clicks
   it, **Then** the dashboard opens directly to that finding's detail view, not the general
   findings list.

---

### User Story 3 - Reminders keep pressure on an unresolved finding, then flag it for attention (Priority: P1)

A finding that got emailed on day 0 is still open two days later. The owner gets a second
reminder on day 2, and a third on day 4 if it's still open. The moment the owner acknowledges the
finding or fixes the underlying problem (spec 003/004's existing mechanics), reminders for that
finding stop. A finding still open after its day-4 reminder is flagged escalated — a distinct,
visible state an admin can find and act on by whatever means makes sense outside this feature (a
direct conversation, a manager escalation). This story ships the flag and its visibility only;
automated escalation delivery is a later release (backlog S38).

**Why this priority**: A single day-0 email is easy to miss or deprioritize. The cadence is what
turns "we told them once" into "we made sure it couldn't be ignored," and the escalation flag is
what keeps a finding email genuinely isn't reaching (wrong address, ignored inbox) from going
invisible again after the cadence exhausts itself. Both ship together as one story because the
backlog itself (S25) scopes them as one: a cadence with no terminal state is just reminders
forever.

**Independent Test**: Advance a finding through its open lifetime with a clock-forwarded test:
confirm reminder emails fire at day 2 and day 4 while it stays open, confirm no reminder fires for
a day whose scheduled send falls after the finding was acknowledged/resolved/suppressed, and
confirm a finding still open after day 4 is visible as escalated.

**Acceptance Scenarios**:

1. **Given** a finding still open two days after its day-0 email, **When** day 2 arrives,
   **Then** the owner receives a reminder email referencing the same finding.
2. **Given** a finding still open four days after its day-0 email, **When** day 4 arrives,
   **Then** the owner receives a third reminder.
3. **Given** an owner acknowledges a finding between day 0 and day 2, **When** day 2 arrives,
   **Then** no reminder is sent for that finding.
4. **Given** a finding resolves (tag fixed and re-scan confirmed, or a budget overrun brought back
   under threshold) before a scheduled reminder, **When** that reminder's scheduled time arrives,
   **Then** no email is sent.
5. **Given** a finding still open after its day-4 reminder was sent, **When** no further owner
   action occurs, **Then** the finding is marked escalated and is visible as such wherever
   findings are already surfaced (dashboard, API), distinguishable from a finding still mid-cadence
   and from an acknowledged one.
6. **Given** an escalated finding, **When** it is subsequently acknowledged, resolved, or
   suppressed, **Then** it no longer displays as escalated.
7. **Given** a finding that was resolved and later reopens (a fresh violation on the same
   resource, or a budget overrun that recurs), **When** it reopens, **Then** it starts a new
   day-0/2/4 cycle of its own, independent of the cycle its prior occurrence already completed.

---

### User Story 4 - A new project gets a spending guardrail without anyone asking for one (Priority: P2)

The moment a project is registered (spec 003's SDA registry), a budget is created for it
automatically, with alerts at 80% and 100% of both actual and forecast spend — nobody has to
remember to set one up by hand.

**Why this priority**: Valuable, but the platform functions without it — an admin can still see
overspend by watching the cost dashboard (User Story 1). It's a convenience that prevents a
guardrail being forgotten, not a capability that unlocks anything else.

**Independent Test**: Register a new project/SDA and confirm a budget exists for it, with the
correct 80%/100% actual-and-forecast thresholds, within the success-criteria window.

**Acceptance Scenarios**:

1. **Given** a newly registered project/SDA, **When** registration completes, **Then** a budget
   already exists for it (created synchronously, no later than the end of that calendar day),
   with 80% and 100% actual-spend and forecast-spend alert thresholds.
2. **Given** a project's spend crosses 80% of its budget, **When** the next spend ingestion runs,
   **Then** an alert condition is recorded and shown on the cost dashboard, distinct from the
   100% threshold — this alone does not send any notification (only crossing 100% opens a finding
   and triggers User Stories 2/3's email/cadence machinery, per User Story 5).

---

### User Story 5 - An overrun budget becomes a finding, not a surprise at month's end (Priority: P2)

When a project's spend crosses its 100% budget threshold, that overrun becomes a finding in the
same pipeline spec 003 already built for tag violations — same open/acknowledge/resolve
lifecycle, same visibility on the findings workbench, and (via User Stories 2/3) the same
owner-email notification any other finding gets.

**Why this priority**: Depends on User Story 4's budgets existing first, and depends on User
Stories 2/3 for its own notification behavior — it's additive polish on top of already-functional
budgets and cost visibility (User Story 1 already lets an admin see an overrun by looking).

**Independent Test**: Push a test project's ingested spend past its 100% threshold and confirm a
finding opens for it, visible on the findings workbench with the same fields any other finding
carries, and that fixing the overrun (spend drops back under threshold) resolves it.

**Acceptance Scenarios**:

1. **Given** a project's spend crosses its 100% budget threshold, **When** the next spend
   ingestion runs, **Then** a finding opens identifying the overrun, visible on the findings
   workbench alongside tag-compliance findings.
2. **Given** an open overrun finding, **When** the project's spend drops back under its threshold,
   **Then** the finding resolves the same way a fixed tag violation does.
3. **Given** an open overrun finding with a resolvable project owner email, **When** it opens,
   **Then** the owner is notified exactly as User Story 2 describes for any other finding type.

---

### User Story 6 - See how well a sandbox account or project is actually being used (Priority: P2)

An admin wants to know, per account and per project, how much of what's provisioned is actually
in use — not just what exists, but what's idle. A documented utilization percentage (resources
in an active/running state vs. all provisioned resources — spec 002's existing `Resource.state`
data, not a CPU/memory metric) is available with drill-down from an account down to project down
to resource.

**Why this priority**: A real capability, but it depends on nothing else in this spec working
first and nothing else in this spec depends on it — it's independently deferrable without
weakening any P1 story.

**Independent Test**: Compute utilization for a test account with a known count of active vs.
stopped/idle resources and confirm the dashboard's number matches a hand calculation, then
confirm drill-down reaches a single resource in the success-criteria's click budget.

**Acceptance Scenarios**:

1. **Given** an account with a known count of active and stopped/idle provisioned resources,
   **When** an admin views its utilization page, **Then** the displayed percentage (active ÷
   total provisioned) matches a manual calculation using the same documented formula.
2. **Given** the account-level utilization view, **When** an admin drills down to a project and
   then a resource, **Then** they reach the resource-level view in no more than three clicks.

---

### User Story 7 - Find unused IAM roles and keys without risking a false flag (Priority: P2)

An admin wants visibility into IAM roles, users, and keys that look unused — based on last-used
analysis and access patterns — so cleanup can be considered deliberately. Nothing is auto-deleted;
this only produces flagged recommendations, and an active role must never be flagged as unused.

**Why this priority**: A safety-oriented, read-only visibility feature — valuable but strictly
additive; nothing else in this spec or the platform depends on IAM hygiene flags existing.

**Independent Test**: Run the analysis against a test account with both active and genuinely
unused IAM roles/keys and confirm only the genuinely unused ones are flagged, with zero false
flags on the active ones.

**Acceptance Scenarios**:

1. **Given** an IAM role with no recent use and no recent access pattern, **When** the analysis
   runs, **Then** it appears as a flagged cleanup recommendation, not an automatic action.
2. **Given** an actively-used IAM role, **When** the analysis runs, **Then** it is never flagged
   as unused.

---

### Edge Cases

- What happens when a finding opens for a resource whose owner email previously bounced (spec
  003's bounce flagging)? No email is sent and the finding is recorded as unnotifiable, the same
  as an unresolved owner — a bounced address is not a working delivery target either.
- What happens when many findings open across many resources at once (a large scan, or a spend
  ingestion that pushes several projects over threshold the same day)? Every eligible finding
  gets its own day-0 email; an owner with many findings from one event gets one email per finding
  (User Story 2, Scenario 3), not one bundled message.
- What happens if the acknowledging action and a scheduled reminder's send happen at nearly the
  same moment? The reminder is suppressed if the finding is already acknowledged, resolved, or
  suppressed at the moment the send actually executes — not guaranteed to fire strictly before an
  acknowledgment, only guaranteed not to fire after one has taken effect.
- What happens to a finding's cadence if the resource itself (or its account) is deleted or
  deactivated mid-cycle? Remaining scheduled reminders for that finding are not sent.
- What happens when spend data for a day arrives late or is corrected after ingestion? A
  correction updates that day's stored total rather than creating a second, conflicting record for
  the same account/day/service.
- What happens when a day's spend ingestion fails outright (upstream cost data unavailable)? It
  retries automatically; if the day is still missing after retries, the dashboard shows an
  explicit gap for that day rather than interpolating, zeroing, or silently omitting it from
  totals.
- What happens when a project has no registered owner at budget-overrun time? The overrun finding
  still opens and is visible on the dashboard (User Story 5); it simply has no notification target
  (User Story 2's Scenario 2 applies the same way).
- What happens when utilization can't be computed for an account with zero provisioned capacity
  (nothing to divide by)? The account shows an explicit "not enough data" state rather than a
  divide-by-zero error or a misleading 0%/100%.

## Requirements *(mandatory)*

### Functional Requirements

**Spend and cost visibility**

- **FR-001** `[P1]`: The system MUST ingest daily spend, broken down by project tag, account, and
  service, into the governance store.
- **FR-002** `[P1]`: Ingested spend totals MUST reconcile with the cloud provider's own cost
  reporting within the success-criteria tolerance.
- **FR-002a** `[P1]`: A day's failed spend ingestion MUST be retried automatically; if it remains
  missing after retries, the system MUST display that day as an explicit gap rather than
  interpolating, zeroing, or silently omitting it from totals.
- **FR-003** `[P1]`: The system MUST expose spend by project/SDA/environment with trend
  visualization and drill-down from an org-wide total to a single resource's own spend.

**Notification**

- **FR-004** `[P1]`: The system MUST send an email to a finding's resolved owner the same
  calendar day a new finding opens against their resource, naming the resource and the specific
  violation.
- **FR-005** `[P1]`: Every notification email MUST include a deep link that opens the dashboard
  directly to that finding's detail view for a signed-in recipient.
- **FR-006** `[P1]`: The system MUST send a reminder email for a finding still open two days after
  its day-0 notification, and a second reminder for a finding still open four days after its
  day-0 notification.
- **FR-007** `[P1]`: The system MUST NOT send a scheduled reminder for a finding that has been
  acknowledged, resolved, or suppressed by the time that reminder is due to send.
- **FR-008** `[P1]`: The system MUST mark a finding as escalated when it is still open after its
  day-4 reminder has been sent, and MUST NOT take any automated action beyond that flag (no
  further emails, no external escalation) as part of this feature.
- **FR-009** `[P1]`: An escalated finding MUST be visible as escalated wherever findings are
  already exposed to users (dashboard, API), distinguishable from open-and-in-cadence and from
  acknowledged findings, and MUST no longer display as escalated once it is acknowledged,
  resolved, or suppressed.
- **FR-010** `[P1]`: A finding whose owner email cannot be resolved, or whose only resolved
  address has previously bounced, MUST NOT receive any notification, and MUST be recorded as
  unnotifiable rather than retried or silently dropped.
- **FR-011** `[P1]`: A finding that reopens after a prior resolution MUST start its own
  independent day-0/2/4 cadence, unaffected by reminders already sent or suppressed for its
  earlier occurrence.
- **FR-012** `[P1]`: Each notification email MUST correspond to exactly one finding — findings
  are never bundled into a single combined email, even when the same owner has multiple findings
  opening on the same day.
- **FR-013** `[P1]`: The system MUST record, per finding, which notifications were sent (or why
  one was withheld) in a form an admin can audit.
- **FR-014** `[P1]`: Every outbound notification MUST originate from a single,
  consistently-branded sending identity recipients can recognize and safelist.

**Budgets and overrun findings**

- **FR-015** `[P2]`: The system MUST create a budget for a project/SDA no later than the end of
  the calendar day of its registration — in practice immediately, as part of the same
  registration request, not a separately-scheduled or delayed step — with 80% and 100%
  actual-spend and forecast-spend alert thresholds. Crossing 80% MUST be visible on the cost
  dashboard only and MUST NOT send any notification; only crossing 100% triggers FR-016.
- **FR-016** `[P2]`: When a project's spend crosses its 100% budget threshold, the system MUST
  open a finding for it in the same findings pipeline and lifecycle spec 003 already defines
  (open/acknowledge/resolve/suppressed — a budget-overrun finding is eligible for every status a
  tag-violation finding is, including `suppressed`, not only open/resolved), notified the same
  way any other finding is (FR-004–FR-014).
- **FR-017** `[P2]`: An overrun finding MUST resolve when the project's spend drops back under
  its threshold.

**Utilization and IAM hygiene**

- **FR-018** `[P2]`: The system MUST compute a utilization percentage per account and per project
  as the count of resources in an active/running state divided by the count of all provisioned
  resources (spec 002's existing per-resource state data — no new metrics collection), with
  drill-down from account to project to resource reachable in no more than three navigation
  steps.
- **FR-019** `[P2]`: The system MUST identify IAM roles, users, and keys that appear unused based
  on last-used analysis and access patterns, and present them as flag-only cleanup
  recommendations — never an automatic deletion or deactivation.
- **FR-020** `[P2]`: An IAM hygiene analysis MUST NOT flag an actively-used role, user, or key as
  unused.

### Key Entities *(include if feature involves data)*

- **Spend Record**: One account/service/day's ingested spend amount, tagged to the project it
  belongs to (via the same tag-value mapping spec 003's SDA registry already resolves resources
  by). Corrections update the existing record for that account/service/day rather than creating a
  duplicate. A day that failed ingestion after retries is recorded as an explicit gap, never a
  guessed or zero amount.
- **Budget**: A spend ceiling attached to one project/SDA, carrying its 80%/100%
  actual-and-forecast alert thresholds and whether each has been crossed. Crossing 80% is a
  dashboard-visible flag only; crossing 100% additionally opens a Finding.
- **Notification**: One outbound email tied to exactly one finding and one point in its cadence
  (day 0, day 2, or day 4). Records what was sent, to whom, when, and whether it succeeded, was
  withheld (no resolvable/working owner email), or was suppressed because the finding left the
  open state before the send executed.
- **Finding** *(spec 003, extended here)*: Gains an escalated state (set at day-4 if still open,
  cleared on leaving the open state) and a new violation kind — a budget overrun — alongside spec
  003's existing tag-violation kinds, sharing the same lifecycle in full: a budget-overrun finding
  can be open, acknowledged, resolved, or suppressed exactly like a tag-violation finding, not a
  narrower subset of those states.
- **Utilization Record**: A computed ratio (active-state resource count ÷ total provisioned
  resource count) for one account or project at a point in time, derived from spec 002's existing
  per-resource state data.
- **IAM Hygiene Flag**: A recommendation (never an action) against one IAM role, user, or key,
  carrying the evidence (last-used date, access pattern) that produced it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

**P1 (User Stories 1–3) — provable without any P2 work existing:**

- **SC-001**: Ingested spend totals reconcile with the cloud provider's own cost reporting within
  ±1%.
- **SC-002**: The cost dashboard loads and reflects the current day's ingested totals within the
  same standard the platform's other dashboard pages already meet (spec 004's 2-second budget at
  up to 5,000 resources, its own stated scale).
- **SC-003**: Measured over a rolling 30-day window of day-0 notification attempts, at least 95%
  of owners with a resolvable email receive their notification the same calendar day the finding
  opened.
- **SC-004**: 100% of findings that reach day 4 still open are visible as escalated by the end of
  the same calendar day their day-4 reminder was sent.

**P2 (User Stories 4–7) — depend on that tier's own work; dropping P2 leaves SC-001–SC-004 fully
provable, SC-005–SC-008 inapplicable rather than failing:**

- **SC-005**: Every newly registered project has a budget with correct thresholds by the end of
  its registration day — in practice immediately, since budget creation is synchronous with
  registration (no sampling; this is a per-event guarantee, not a rate).
- **SC-006**: A budget overrun surfaces as a finding within a day of crossing its threshold.
- **SC-007**: Utilization figures match a hand calculation using the documented formula exactly
  (integer counts, no rounding tolerance needed), and account-to-resource drill-down completes in
  three clicks or fewer.
- **SC-008**: Zero active IAM roles, users, or keys are flagged as unused in the test account used
  to validate this feature — reproducible by seeding that account with at least one deliberately
  active and one deliberately unused role/user/key before running the analysis.

## Assumptions

- **Sending infrastructure and delivery mechanics are an implementation concern**, not specified
  here beyond FR-014's "one consistent identity" — this spec defines what gets sent, to whom, and
  when, not how mail is transmitted (Principle II already fixes the runtime as AWS-native; the
  backlog's own naming of a specific email service is an implementation choice for the plan
  phase, not a user-facing requirement).
- **Notification templates are out of this spec's scope in detail** — FR-004/FR-005 fix the
  required content (resource, violation, deep link); exact wording, branding, and layout are a
  plan/implementation decision.
- **"Day" means a calendar day boundary in a single, system-wide reference timezone (UTC)**,
  consistent with how spec 002's scheduling already reasons about scan cadence. The spec's three
  same-day-shaped bounds are related but not interchangeable, stated explicitly here to prevent
  conflation: FR-004/SC-003's "the same day" is a freshness bound on the daily notification
  worker (a finding opened today gets emailed today); FR-015/SC-005's "no later than the end of
  the day" is a loose outer bound that budget creation (synchronous with registration, R-502)
  satisfies trivially, not a same-worker-run guarantee; SC-004's "by the end of the same day" ties
  to the day the day-4 reminder itself sends, not the day the finding originally opened four days
  earlier.
- **One email per finding, never bundled per owner or per event** — the backlog's own "day-0/2/4
  sends per finding" phrasing, and User Story 2's Scenario 3, both point at this as the only
  unambiguous reading; a digest view is not part of this feature.
- **Escalation in this release is a visibility flag only** — no automated escalation delivery is
  in scope; the backlog explicitly defers that (S38) to a later release.
- **In-app notifications (the backlog's separate S26/S32 bell/feed) are out of scope** — this
  feature is email-only; a bell/feed UI is a distinct, later backlog item.
- **The four mandatory tags, rule/finding lifecycle, and SDA registry are entirely spec 003's**;
  this feature only observes and extends finding state transitions already defined there (adding
  the escalated flag and the budget-overrun finding kind), and reuses its project-tag-to-SDA
  mapping for spend attribution — it does not redefine either mechanism.
- **"Project" and "SDA" are the same registered entity** (spec 003's SDA registry) — spend,
  budgets, and utilization are all attributed the same way resources already are.
- **Auto-budget thresholds (80%/100%, actual and forecast) are fixed, platform-wide defaults for
  this release** — per-project custom thresholds are not in scope; the backlog names exactly these
  two thresholds and gives no indication they should be configurable yet.
- **Rightsizing and spend/capacity forecasting are spec 6's job** (Bedrock Agent insights, backlog
  S51–S53) — this spec ingests the raw spend and utilization data those features will eventually
  consume, but does not itself forecast or recommend instance changes.
- **Viewer-role and non-owner visibility of cost, utilization, and escalated-finding data follows
  the existing platform visibility model** (spec 003/004: this class of governance data is visible
  to every role) — no new permission tier is introduced by this feature.
