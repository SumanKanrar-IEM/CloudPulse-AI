# Feature Specification: Notification Engine

**Feature Branch**: `005-notification-engine`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Notification engine (E6): SES email setup, templated finding
notifications with deep links, day-0/2/4 cadence per finding stopping on close/acknowledge,
escalation flag after the 4th interval. Backlog stories S24, S25."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A resource owner learns their resource has a compliance problem (Priority: P1)

An engineer owns a resource that a scan just flagged (a missing required tag, an invalid value, a
non-standard format — spec 003's finding types). Today that finding is visible only if someone
goes looking on the dashboard (spec 003 deliberately cut owner notification from its own MVP).
This story closes that gap: the owner receives an email the same day the finding opens, naming the
resource, the problem, and a link straight into the dashboard's finding detail.

**Why this priority**: Without this, every finding spec 003/004 can open or display is invisible
until someone happens to look — the entire compliance program depends on owners finding out.
Nothing else in this feature matters if the first email never arrives.

**Independent Test**: Open a finding on a resource with a resolved owner email (spec 003's
attribution chain) and confirm one email arrives at that address within the success-criteria
window, containing the resource identifier, the violation, and a link that opens directly to that
finding.

**Acceptance Scenarios**:

1. **Given** a resource with a resolved owner email, **When** a scan opens a new finding against
   it, **Then** the owner receives an email that day naming the resource, the specific violation,
   and a deep link to the finding's detail page.
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

### User Story 2 - Reminders keep pressure on an unresolved finding without nagging forever (Priority: P1)

A finding that got emailed on day 0 is still open two days later — the tag still isn't fixed. The
owner gets a second reminder on day 2, and a third on day 4 if it's still open. The moment the
owner acknowledges the finding or fixes the tag and it auto-closes (spec 003/004's existing
mechanics), the reminders for that finding stop — no email arrives after the state that made it
irrelevant.

**Why this priority**: A single day-0 email is easy to miss or deprioritize. The cadence is what
turns "we told them once" into "we made sure it couldn't be ignored" — the actual behavior change
this feature exists to produce. It ships alongside Story 1 because a notification system with no
follow-through is not meaningfully different from the dashboard-only status quo it replaces.

**Independent Test**: Advance a finding through its open lifetime with a clock-forwarded test:
confirm reminder emails fire at day 2 and day 4 while it stays open, and confirm no reminder fires
for a day whose scheduled send falls after the finding was acknowledged or resolved.

**Acceptance Scenarios**:

1. **Given** a finding still open two days after its day-0 email, **When** day 2 arrives,
   **Then** the owner receives a reminder email referencing the same finding.
2. **Given** a finding still open four days after its day-0 email, **When** day 4 arrives,
   **Then** the owner receives a third reminder.
3. **Given** an owner acknowledges a finding (spec 004's acknowledge action) between day 0 and day
   2, **When** day 2 arrives, **Then** no reminder is sent for that finding.
4. **Given** a finding auto-closes because the tag was fixed and a re-scan confirmed it (spec
   003's existing mechanic) before a scheduled reminder, **When** that reminder's scheduled time
   arrives, **Then** no email is sent.
5. **Given** a finding that was resolved and later reopens (a fresh violation on the same
   resource-rule pair, spec 003's re-open semantics), **When** it reopens, **Then** it starts a new
   day-0/2/4 cycle of its own, independent of the cycle its prior occurrence already completed.

---

### User Story 3 - An unresolved finding becomes visible as needing attention beyond email (Priority: P1)

A finding that got all three reminders (day 0, 2, 4) and is still open four days later has proven
email alone isn't moving it. Rather than continuing to send reminders indefinitely, the finding is
flagged as escalated — a distinct, visible state an admin can find and act on by whatever means
makes sense (a direct conversation, a manager escalation) outside this feature. This story ships
the flag and its visibility; it does not ship any automated escalation action — the backlog
[S25] explicitly scopes automated escalation (S38) to a later release.

**Why this priority**: Without an escalation signal, a finding that email genuinely isn't reaching
(wrong address, ignored inbox, owner on leave) stays invisible again, just one layer down — the
same problem Story 1 exists to solve, recurring silently after the cadence exhausts itself. It's
P1 because leaving that gap open defeats Story 1 and 2's purpose for exactly the findings that
need the most attention.

**Independent Test**: Advance a finding past its day-4 reminder while it stays open, and confirm
it is queryable/visible as escalated, distinguishable from a finding still mid-cadence or one that
was acknowledged.

**Acceptance Scenarios**:

1. **Given** a finding still open after its day-4 reminder was sent, **When** no further owner
   action occurs, **Then** the finding is marked escalated and is visible as such wherever findings
   are already surfaced (dashboard, API).
2. **Given** a finding marked escalated, **When** an admin views it, **Then** it's visually
   distinguishable from an open finding still within its cadence and from an acknowledged finding.
3. **Given** an escalated finding, **When** its tag is subsequently fixed and it auto-closes,
   **Then** the escalated flag is superseded by the closed state, not left showing "escalated" on
   a resolved finding.

---

### Edge Cases

- What happens when a finding opens for a resource whose owner email previously bounced (spec
  003's bounce flagging, S23a)? No email is sent and the finding is recorded as unnotifiable, the
  same as an unresolved owner — a bounced address is not a working delivery target either.
- What happens when the same scan opens many findings across many resources at once? Every
  eligible finding gets its own day-0 email; sending is not throttled below what a scan can
  produce, but a single owner with many findings from one scan gets one email per finding (Story
  1, Scenario 3), not one bundled per scan.
- What happens if the acknowledging action and a scheduled reminder's send happen at nearly the
  same moment? The reminder is suppressed if the finding is already acknowledged or resolved at
  the moment the send actually executes — no reminder is guaranteed to fire strictly before an
  acknowledgment, only guaranteed not to fire after one has taken effect.
- What happens to a finding's cadence if the resource itself is deleted or its account is
  deactivated mid-cycle? Remaining scheduled reminders for that finding are not sent — there's
  nothing left to report on.
- What happens if a finding is suppressed (spec 003's reserved `suppressed` status) mid-cycle?
  Suppression stops the cadence the same way acknowledgment or resolution does — a suppressed
  finding is not actionable by the owner either.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST send an email to a finding's resolved owner the same day a new
  finding opens against their resource, naming the resource and the specific violation.
- **FR-002**: Every notification email MUST include a deep link that opens the dashboard directly
  to that finding's detail view for a signed-in recipient.
- **FR-003**: The system MUST send a reminder email for a finding still open two days after its
  day-0 notification, and a second reminder for a finding still open four days after its day-0
  notification.
- **FR-004**: The system MUST NOT send a scheduled reminder for a finding that has been
  acknowledged, resolved, or suppressed by the time that reminder is due to send.
- **FR-005**: The system MUST mark a finding as escalated when it is still open after its day-4
  reminder has been sent, and MUST NOT take any automated action beyond that flag (no further
  emails, no external escalation) as part of this feature.
- **FR-006**: An escalated finding MUST be visible as escalated wherever findings are already
  exposed to users (dashboard, API), distinguishable from open-and-in-cadence and from
  acknowledged findings.
- **FR-007**: An escalated finding that is subsequently acknowledged, resolved, or suppressed
  MUST no longer display as escalated.
- **FR-008**: A finding whose owner email cannot be resolved, or whose only resolved address has
  previously bounced (spec 003, S23a), MUST NOT receive any notification, and MUST be recorded as
  unnotifiable rather than retried or silently dropped.
- **FR-009**: A finding that reopens after a prior resolution MUST start its own independent
  day-0/2/4 cadence, unaffected by reminders already sent or suppressed for its earlier occurrence.
- **FR-010**: Each notification email MUST correspond to exactly one finding — findings are never
  bundled into a single combined email, even when the same owner has multiple findings opening on
  the same day.
- **FR-011**: The system MUST record, per finding, which notifications were sent (or why one was
  withheld) in a form an admin can audit — the same event-attributed-evidence discipline spec 003
  already applies to ownership attribution.
- **FR-012**: Every outbound notification MUST originate from a single, consistently-branded
  sending identity recipients can recognize and safelist.

### Key Entities *(include if feature involves data)*

- **Notification**: One outbound email tied to exactly one finding and one point in its cadence
  (day 0, day 2, or day 4). Records what was sent, to whom, when, and whether it succeeded, was
  withheld (no resolvable/working owner email), or was suppressed because the finding left the
  open state before the send executed.
- **Finding** *(spec 003, extended here)*: Gains an escalated state, set when its day-4
  reminder has been sent and it is still open, cleared when it leaves the open state by any means
  (acknowledged, resolved, or suppressed).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An owner with a resolvable email receives a notification for a newly-opened finding
  the same day it opens, at least 95% of the time.
- **SC-002**: Clicking a notification's deep link, while signed in, lands on the correct finding's
  detail view in under 3 seconds, 100% of the time.
- **SC-003**: A finding's reminder cadence (day 2, day 4) is verified correct against a
  clock-forwarded test suite covering both the "still open, reminder fires" and "resolved before
  the send, reminder suppressed" cases, with zero cadence-timing defects found in that suite.
- **SC-004**: 100% of findings whose owner email cannot be resolved or has bounced are recorded as
  unnotifiable rather than causing a delivery attempt, a retry loop, or a silent gap with no
  record at all.
- **SC-005**: 100% of findings that reach day 4 still open are visible as escalated within the
  same day, with zero escalated findings left un-flagged past that point.

## Assumptions

- **Sending infrastructure and delivery mechanics are an implementation concern**, not specified
  here beyond FR-012's "one consistent identity" — this spec defines what gets sent, to whom, and
  when, not how mail is transmitted or which AWS service does it (Principle II already fixes the
  runtime as AWS-native; the backlog's own naming of SES is an implementation choice for the plan
  phase, not a user-facing requirement).
- **Templates are out of this spec's scope in detail** — FR-001/FR-002 fix the required content
  (resource, violation, deep link); exact wording, branding, and layout are a plan/implementation
  decision, not a spec-level requirement.
- **"Day" means a calendar day boundary in a single, system-wide reference timezone** (UTC),
  consistent with how spec 002's scheduling already reasons about scan cadence — not the
  recipient's local timezone, which this feature does not track.
- **One email per finding, never bundled per owner or per scan** — the backlog's own "day-0/2/4
  sends per finding" phrasing, and Story 1's Scenario 3, both point at this as the only
  unambiguous reading; a digest view is not part of this feature.
- **Escalation in this release is a visibility flag only** — no automated escalation delivery
  (a distinct notification to a project owner, a manager, or any party besides the resource's own
  owner) is in scope. The backlog explicitly defers that behavior to a later release (S38);
  building it here would be scope creep past what S24/S25 describe.
- **The four mandatory tags and rule/finding lifecycle are entirely spec 003's**; this feature
  only observes finding state transitions (opened, acknowledged, resolved, suppressed) already
  defined there and in spec 004 — it defines and changes none of them itself, beyond adding the
  escalated flag (FR-005/FR-006/FR-007, Key Entities).
- **In-app notifications (the backlog's separate S26 "bell" story) are out of scope** — this
  feature is email-only; a bell/feed UI is a distinct, later backlog item building on the same
  underlying notification records.
- **Viewer-role and non-owner visibility of the escalated flag follows the existing findings
  visibility model** (spec 003/004: findings are visible to every role) — no new permission tier
  is introduced by this feature.
