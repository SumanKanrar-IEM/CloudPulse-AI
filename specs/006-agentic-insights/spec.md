# Feature Specification: Agentic Insights

**Feature Branch**: `006-agentic-insights`

**Created**: 2026-09-05

**Status**: Draft

**Input**: User description: "Build the platform's intelligence layer as Amazon Bedrock Agents: AI that observes the governance data, explains it, predicts it, and proposes improvements — while never executing changes or touching cloud credentials. This is the AWS-native agentic showcase of the MVP."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An operator reads one paragraph instead of five dashboards (Priority: P1)

Every morning an operator opens the dashboard and finds a short, plain-language digest of what
changed overnight: which findings matter most right now, whether compliance moved up or down, and
where spend went unexpectedly. Every resource and number the digest names is real — they can click
through and land on the exact finding or project it referenced.

**Why this priority**: This is the feature's whole premise. Specs 002–005 built five surfaces
(inventory, findings, compliance, cost, utilization) each answering one question well; nobody
reads five surfaces daily. The digest is the first thing that answers "what should I care about
today?" in one place, and it is the showcase capability of the platform.

**Independent Test**: Trigger a digest run against a governance store with known findings, a known
compliance movement, and a known spend delta. Confirm the digest is produced, renders as a
dashboard card, and that every resource identifier and figure it contains exists in the store.

**Acceptance Scenarios**:

1. **Given** a tenant with open findings, a compliance score that changed since yesterday, and at
   least one project whose spend moved, **When** the nightly digest run completes, **Then** a
   digest is available on the dashboard naming the top findings, the direction and size of the
   compliance movement, and the notable spend change.
2. **Given** a digest draft that references a resource identifier absent from the governance
   store, **When** it is validated before display, **Then** the digest is rejected and not shown,
   and the rejection is recorded for an admin to inspect.
3. **Given** a digest draft whose figures all match the governance store, **When** it is
   validated, **Then** it is stored and displayed with the timestamp of the run that produced it.
4. **Given** a tenant with no findings, no compliance movement, and no spend, **When** the digest
   run completes, **Then** the dashboard states plainly that there was nothing notable, rather
   than displaying an empty card or a fabricated summary.
5. **Given** yesterday's digest is on the dashboard and today's run has not completed, **When** a
   user opens the dashboard, **Then** the digest shown is clearly labelled with the run it came
   from, so a stale digest is never mistaken for a current one.

---

### User Story 2 - A finding arrives with a proposed fix already attached (Priority: P1)

An operator opens the findings workbench and each open finding carries a drafted fix and a note on
what else that fix could affect. They decide whether to act; the platform never acts for them.

**Why this priority**: Spec 004 built the suggestion surface and reserved the `ai_generated`
source, but nothing has ever written one — every suggestion to date is admin-seeded test data.
This closes that loop, and it is the difference between a findings list and a findings *workbench*.

**Independent Test**: With open findings spanning every finding class the platform can produce,
run the suggester and confirm each class receives a suggestion carrying both a recommended fix and
a blast-radius note, and that no code path exists by which the platform applies one.

**Acceptance Scenarios**:

1. **Given** an open finding, **When** the suggester has run for it, **Then** the findings
   workbench shows a recommended fix and a blast-radius note beside that finding, marked as
   AI-generated so a reader can tell it apart from an admin-seeded one.
2. **Given** a finding whose suggestion references a resource or rule absent from the governance
   store, **When** the suggestion is validated, **Then** it is rejected and the finding shows no
   suggestion rather than an unverified one.
3. **Given** a suggestion is displayed, **When** a user reads it, **Then** the interface offers no
   control that applies, executes, or schedules the fix.
4. **Given** a finding that already carries an admin-seeded suggestion, **When** the suggester
   runs, **Then** the admin-seeded suggestion is not overwritten.

---

### User Story 3 - An admin extends coverage without writing code (Priority: P2)

An admin reviews proposals describing resource types present in their accounts that the platform
discovers but does not yet enrich or govern. They accept a proposal, and the next scan applies it —
no deployment, no code change.

**Why this priority**: P2 stretch. It depends on the coverage-as-data and rules-as-data mechanisms
specs 002 and 003 already built, and it is the clearest demonstration that the platform's own
configuration is data rather than code. Valuable, but the P1 stories stand without it.

**Independent Test**: Seed an account containing a resource type present in the inventory but
absent from the coverage definitions. Run the advisor, confirm a proposal appears, accept it as an
admin, and confirm the next scan enriches or governs that type without any code deployment.

**Acceptance Scenarios**:

1. **Given** an inventory containing a resource type not present in the coverage definitions,
   **When** the advisor runs, **Then** a proposal appears describing the gap and the configuration
   change that would close it.
2. **Given** a pending proposal, **When** an admin accepts it, **Then** the configuration change
   takes effect on the next scan without a code deployment.
3. **Given** a pending proposal, **When** an admin rejects it, **Then** it is not applied and does
   not reappear on the next advisor run.
4. **Given** a proposal is pending, **When** any non-admin views it, **Then** they can see it but
   cannot accept or reject it.
5. **Given** a proposal that would alter existing governed behaviour rather than extend it,
   **When** the advisor produces it, **Then** it is still subject to the same human acceptance
   step — no proposal takes effect without review.

---

### User Story 4 - Utilization figures gain history (Priority: P2)

Utilization metrics for compute and database resources are collected over time into a metrics
store, giving the platform a deterministic history to reason about rather than a single snapshot.

**Why this priority**: P2, and a prerequisite for User Stories 5 and 7 rather than valuable alone.
Spec 005's utilization answers "how much is in use right now"; forecasting and rightsizing both
need "how much has been in use over time".

**Independent Test**: Run collection against an account with known resources, confirm metrics land
in the store attributed to the right resource and period, and confirm a second run neither
duplicates nor overwrites earlier periods.

**Acceptance Scenarios**:

1. **Given** compute and database resources in a scanned account, **When** metrics collection
   runs, **Then** utilization measurements are stored per resource and period.
2. **Given** a period already collected, **When** collection runs again, **Then** the existing
   measurement is not duplicated.
3. **Given** a resource for which no metrics are available, **When** collection runs, **Then** the
   absence is recorded as unknown rather than as zero.

---

### User Story 5 - A project owner sees where spend is heading (Priority: P2)

A project owner sees a forecast of where their project's spend and capacity are trending, with a
stated accuracy they can judge it by.

**Why this priority**: P2. Depends on User Story 4's history. Spec 005 answers "what did we
spend"; this answers "what will we spend", which is what makes a budget actionable before the
month ends rather than after.

**Independent Test**: Backtest forecasts against held-out historical periods for test projects and
confirm the measured error meets the stated accuracy target.

**Acceptance Scenarios**:

1. **Given** a project with sufficient spend history, **When** a forecast is produced, **Then** it
   states the projected figure and the period it covers.
2. **Given** a project with insufficient history, **When** a forecast is requested, **Then** the
   platform states that there is not enough data rather than projecting from too few points.
3. **Given** forecasts and the actuals that followed them, **When** accuracy is backtested,
   **Then** the measured error is reported and comparable against the target.

---

### User Story 6 - A rightsizing recommendation arrives with its evidence (Priority: P2)

An operator sees which resources are provisioned larger than their measured use, what to change
them to, and roughly what that would save each month — with the measurements that justify it.

**Why this priority**: P2. Depends on User Story 4's metrics history. This is the most directly
monetary output of the intelligence layer, but it is worthless — and actively harmful — without
the evidence beside it.

**Independent Test**: With resources whose collected metrics show sustained low use, confirm a
recommendation is produced naming a smaller instance class, the evidence behind it, and an
estimated monthly saving.

**Acceptance Scenarios**:

1. **Given** a resource whose collected utilization is persistently low, **When** recommendations
   are produced, **Then** a smaller instance class is recommended with the supporting measurements
   and an estimated monthly saving.
2. **Given** a resource whose utilization is high or variable, **When** recommendations are
   produced, **Then** no downsizing recommendation is made for it.
3. **Given** a recommendation, **When** an operator views it, **Then** no control exists to apply
   the change.

---

### User Story 7 - The narrative matches the chart (Priority: P2)

Cost and forecast pages carry a short written explanation of what the chart shows, and its figures
are exactly the chart's figures.

**Why this priority**: P2, lowest of the set. It is presentation atop User Stories 5 and 6 — real
value for a reader skimming, no new capability, and the last thing to drop if time runs short.

**Independent Test**: Render a narrative alongside a chart with known values and confirm every
figure in the prose matches the corresponding chart value exactly.

**Acceptance Scenarios**:

1. **Given** a cost or forecast page with a chart, **When** the narrative is displayed, **Then**
   every figure it states matches the chart's own values.
2. **Given** a narrative whose figures do not match the underlying data, **When** it is validated,
   **Then** it is not displayed.

---

### Edge Cases

- What happens when the model is unavailable or a run fails partway? The previous digest or
  suggestion remains, clearly labelled with the run it came from; the failure is recorded, and
  nothing partial or fabricated is displayed.
- What happens when an agent output passes validation but contains no useful content? An empty or
  contentless result is treated as "nothing notable" and stated plainly, never padded.
- What happens when a run would exceed its cost cap? The run stops at the cap and records that it
  was truncated, rather than continuing unbounded or silently producing a partial result presented
  as complete.
- What happens when a finding is resolved between the suggestion being drafted and displayed? The
  suggestion is not shown for a finding that is no longer open.
- What happens when the governance store is empty — a newly provisioned tenant? Every agent
  surface states there is not enough data yet, rather than producing content from nothing.
- What happens when two runs overlap? Only one run's output per surface per period is retained;
  a concurrent second run does not produce a duplicate or interleaved digest.
- What happens when a coverage proposal is accepted but the underlying resource type disappears
  before the next scan? The accepted configuration applies harmlessly and governs nothing.
- What happens when a prompt or agent definition changes? The output records which version
  produced it, so a change in behaviour is traceable to a change in definition.

## Requirements *(mandatory)*

### Functional Requirements

**Grounding and safety (apply to every agent output in this feature)**

- **FR-001** `[P1]`: Every agent output displayed to a user MUST be validated against the
  governance store before display, and MUST be rejected rather than shown when it references a
  resource identifier, project, finding, or figure that does not exist there.
- **FR-002** `[P1]`: Agents MUST NOT execute, schedule, or trigger any change against a cloud
  account, and no user-facing control may offer to apply an agent's recommendation.
- **FR-003** `[P1]`: Agents MUST NOT hold, receive, or be able to resolve cloud credentials, and
  MUST reach platform data only through a read-only, tenant-scoped interface.
- **FR-004** `[P1]`: Every agent run MUST enforce a cost cap, and a run reaching its cap MUST stop
  and record that it was truncated rather than continue or present partial output as complete.
- **FR-005** `[P1]`: Agent prompts and definitions MUST be versioned in the repository, and every
  stored output MUST record which version produced it.
- **FR-006** `[P1]`: A rejected agent output MUST be recorded with the reason for rejection, so
  the rejection rate is inspectable rather than invisible.
- **FR-007** `[P1]`: Deterministic platform behaviour — discovery, validation, scoring, spend
  ingestion — MUST remain free of any model call, and MUST produce identical results whether or
  not this feature is enabled.

**Insight digest (User Story 1)**

- **FR-008** `[P1]`: The system MUST produce a digest on a daily schedule covering the top open
  findings, the direction and magnitude of compliance movement, and notable spend changes.
- **FR-009** `[P1]`: The digest MUST be displayed on the dashboard, labelled with the run that
  produced it so a stale digest is distinguishable from a current one.
- **FR-010** `[P1]`: When there is nothing notable to report, the digest MUST say so plainly
  rather than display an empty card or padded content.

**Remediation suggester (User Story 2)**

- **FR-011** `[P1]`: The system MUST produce, for each open finding, a recommended fix and a
  blast-radius note describing what else the fix could affect.
- **FR-012** `[P1]`: An agent-produced suggestion MUST be distinguishable in the interface from an
  admin-seeded one.
- **FR-013** `[P1]`: An agent-produced suggestion MUST NOT overwrite an existing admin-seeded
  suggestion for the same finding.
- **FR-014** `[P1]`: A suggestion MUST NOT be displayed for a finding that is no longer open.

**Coverage advisor (User Story 3)**

- **FR-015** `[P2]`: The system MUST detect resource types present in a tenant's inventory that
  are not covered by existing enrichment or governance configuration, and propose the
  configuration change that would cover them.
- **FR-016** `[P2]`: A proposal MUST require explicit admin acceptance before taking effect, and
  MUST be visible to non-admin roles without being actionable by them.
- **FR-017** `[P2]`: An accepted proposal MUST take effect on the next scan as configuration, with
  no code deployment.
- **FR-018** `[P2]`: A rejected proposal MUST NOT be applied and MUST NOT be re-proposed on the
  next run.

**Metrics, forecasting, rightsizing, narratives (User Stories 4–7)**

- **FR-019** `[P2]`: The system MUST collect utilization measurements for compute and database
  resources into a metrics store, per resource and period, without duplicating a period already
  collected.
- **FR-020** `[P2]`: A resource with no available measurement MUST be recorded as unknown, never
  as zero.
- **FR-021** `[P2]`: The system MUST produce per-project spend and capacity forecasts, and MUST
  state that there is not enough data rather than forecast from insufficient history.
- **FR-022** `[P2]`: Forecast accuracy MUST be backtested against held-out actuals and the
  measured error reported.
- **FR-023** `[P2]`: The system MUST produce instance-class recommendations for resources whose
  measured utilization is persistently low, each carrying its supporting measurements and an
  estimated monthly saving, and MUST NOT recommend downsizing a resource whose utilization is high
  or variable.
- **FR-024** `[P2]`: Narratives displayed alongside a chart MUST state figures that match that
  chart's values exactly, and MUST NOT be displayed when they do not.

### Key Entities *(include if feature involves data)*

- **Insight Digest**: One daily summary for a tenant — its content, the run and definition version
  that produced it, the period it covers, and whether it was displayed or rejected.
- **Agent Run**: One execution of an agent capability — what it was for, when it ran, which
  definition version it used, what it cost, whether it completed or was truncated at its cap, and
  its outcome.
- **Grounding Rejection**: A record of an agent output refused before display — which run produced
  it, and which identifier or figure could not be validated.
- **Coverage Proposal**: A proposed configuration extension — the gap detected, the change
  proposed, its review state (pending, accepted, rejected), and who decided.
- **Resource Metric**: One utilization measurement for one resource over one period, or an
  explicit record that no measurement was available.
- **Forecast**: A projected spend or capacity figure for a project and period, with the history it
  was derived from and, once actuals exist, its measured error.
- **Rightsizing Recommendation**: A proposed instance class for a resource, the measurements
  justifying it, and an estimated monthly saving.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of resource identifiers and figures displayed in a digest exist in the
  governance store — zero fabricated references reach a user.
- **SC-002**: Every open finding class has a suggestion available, covering 100% of the classes
  the platform can produce.
- **SC-003**: An admin can accept a coverage proposal and see it take effect on the next scan
  without any code change or deployment.
- **SC-004**: A reader can identify the platform's most urgent governance issue from the digest
  alone, without opening another screen.
- **SC-005**: No user-facing control anywhere in the platform applies, schedules, or executes an
  agent recommendation.
- **SC-006**: Forecast error measured by backtesting is under 15% (MAPE) on test projects with
  sufficient history.
- **SC-007**: Every figure in a displayed narrative matches its chart exactly — zero mismatches.
- **SC-008**: Agent runs stay within their configured cost cap 100% of the time, and any truncated
  run is identifiable as truncated.

## Assumptions

- **"Agent" means an Amazon Bedrock Agent**, per constitution Principle II, which fixes the
  product GenAI layer to Bedrock Agents — agents, action groups, and guardrails. This spec does
  not revisit that choice.
- **The read-only, tenant-scoped interface agents use is the one spec 001's FR-056 reserved.**
  This feature implements against it and does not bypass it.
- **`source = ai_generated` on a finding's remediation suggestion is this feature's to write.**
  Spec 003 defined the value and spec 004 rendered it, but no code path has ever produced one —
  the seam was left open deliberately for this spec.
- **Coverage-as-data and rules-as-data already exist** (specs 002 and 003). The advisor proposes
  changes to those existing mechanisms rather than introducing a parallel configuration system.
- **Daily is the digest cadence**, matching the existing daily scan, spend-ingestion, and
  notification schedules rather than introducing a new rhythm.
- **Visibility follows the existing platform model**: this class of governance data is readable by
  every role, and only admins may accept or reject a proposal — consistent with specs 003–005.
- **Grounding validation is deterministic**, not another model call. A validator that itself
  hallucinated would defeat its own purpose.
- **Forecasting is a deterministic calculation over collected metrics**, not a model prediction.
  The agent narrates forecasts; it does not compute them. This keeps FR-007's deterministic-core
  rule intact and makes the accuracy target in SC-006 meaningful.
- **Every AWS-facing capability here is read-only by requirement**, not merely by current
  implementation — consistent with every spec before it.
- **The digest covers one tenant at a time.** Cross-tenant aggregate insight is not in scope and
  would violate the tenant-scoping every prior spec enforces.

## Out of Scope

- Natural-language question-and-answer chat against the governance data.
- Weekly or emailed digests — the digest is a dashboard surface; spec 005 owns email.
- Remediation execution of any kind, including one-click apply of an agent suggestion. This is
  excluded platform-wide, not merely deferred.
- Agent-initiated configuration changes that take effect without human acceptance.
- Cross-tenant or fleet-wide benchmarking.
