# Feature Specification: Tag Compliance and Ownership

**Feature Branch**: `pods/pod73-003-tag-compliance-and-ownership`

**Created**: 2026-08-24

**Status**: Draft

**Input**: User description: "Turn the raw inventory into governance signal: validate every resource against the organization's tagging standards, group resources by the SDA (internal project) they belong to, attribute a human owner to every resource, and score compliance. Functional scope (backlog S18, S18a, S18b, S19, S20, S21, S22, S23a): Rules-as-data (S18) [P1]: tagging rules (case-insensitive keys, required set, allowed values) live in an admin-editable store seeded with the four mandatory tags — project_name, owner, project_id, created_by (environment optional). A rule change takes effect on the next scan with no deployment. SDA registry (S18a) [P1]: admins register SDAs (name, owner email, team, and the tag values that map to them); resources attach to their SDA at load time; unmatched resources land in a visible \"No SDA\" bucket. SDA admin UI (S18b) [P2]: CRUD, tag-value mapping editor, and a \"No SDA\" triage list; registering an SDA reclassifies matching resources on the next scan. Validation engine (S19) [P1]: evaluates rules on parent resources only; opens findings for missing tags, invalid values, and non-standard formats; dedupes; auto-closes a finding when a re-scan shows the tag fixed. Compliance scoring (S20) [P1]: score per account and per SDA = compliant parents / total parents, exposed via API and matching a hand count on a test account. Ownership attribution (S21) [P1]: for each resource, mine 90 days of cloud audit events for the creator; when the creator is a human principal, record them as owner with evidence. Attribution fallback (S22) [P2]: when the creator is a pipeline/automation identity, fall back to the most frequent human modifier (≥3 write events) with a confidence level and stored evidence; otherwise queue as unattributed. Owner identity resolution (S23a) [P2]: resolve owners to an email via a chain — owner tag if it is an email, else a configurable pattern over the audit-trail user id, else a manual override table; the pattern is configuration, not code. Success criteria: a rule edit changes findings on the next scan without redeploy; a fixed tag auto-closes its finding; compliance score matches a manual count; creator attribution succeeds for console-created test resources and the fallback chain is exercised by an IaC-created resource. Out of scope: notifying owners (cut from MVP — findings are visible on the dashboard only), remediation execution, AI suggestions (spec 6)."

## Clarifications

### Session 2026-08-25

- Q: When an admin edits a tagging rule, what happens to a finding that's already open against
  the previous version of that same rule? → A: The finding follows the rule's stable identity
  across edits, not one specific versioned row — it is re-evaluated against whichever version is
  currently enabled and can auto-close under the new version, rather than being permanently pinned
  to the exact version that first opened it.

## User Scenarios & Testing *(mandatory)*

<!--
  Priority labels below use the CloudPulse AI constitution's tier semantics (Principle VIII):
  P1 = demo-critical, frozen scope; P2 = stretch, must never block or destabilise a P1 path.
  Stories are listed in dependency order within each tier, not in order of relative importance.
-->

### User Story 1 - Define what "compliant" means, as data an admin controls (Priority: P1)

An admin defines the organization's tagging standard without anyone touching code: which tags
every resource must carry, what values are acceptable for a tag, and what format a value must
follow. The platform ships already seeded with the four mandatory tags every resource is expected
to carry — project name, owner, project ID, and who created it — with an environment tag
recognized but not required. When the admin changes a rule, nothing is redeployed; the very next
scan simply evaluates resources against the new rule.

**Why this priority**: Every other story in this spec — validation, scoring, the findings a
dashboard will eventually show — has nothing to evaluate against until a rule exists. This is the
foundation the rest of the spec reads from.

**Independent Test**: With no scan yet run, edit a rule (change a required tag's allowed values),
then run a scan and confirm the resulting findings reflect the new rule, not the old one — with no
code change or deployment between the edit and the scan.

**Acceptance Scenarios**:

1. **Given** the platform's first deployment, **When** an admin views the tagging rules, **Then**
   the four mandatory tags — project name, owner, project ID, created by — already exist as
   required rules, and environment exists as a recognized but non-required tag.
2. **Given** an existing rule, **When** an admin edits its allowed values or required status,
   **Then** the change is stored immediately but does not alter the outcome of a scan already in
   progress.
3. **Given** a rule changed after a scan started, **When** the next scan begins, **Then** it
   evaluates every resource against the edited rule, not the version in effect when the previous
   scan ran.
4. **Given** a tag key that differs only in letter case from a rule's key (for example `Owner`
   versus `owner`), **When** validation runs, **Then** the two are treated as the same tag.

---

### User Story 2 - Group resources into the internal projects that actually own them (Priority: P1)

An admin registers each Service Delivery Area (SDA) — an internal project or team — along with the
tag values that identify resources belonging to it. From the next scan onward, every resource
whose tags match an SDA's mapping is grouped under that SDA automatically; nothing needs manual
sorting. A resource whose tags match no registered SDA is not lost — it lands in a clearly visible
"No SDA" bucket so it can be triaged rather than silently uncounted.

**Why this priority**: Compliance scoring (User Story 4) is reported per SDA as well as per
account, and ownership context throughout the rest of the platform assumes resources are grouped.
Without this, every later story's "per SDA" view has nothing to group by.

**Independent Test**: Register one SDA with a tag-value mapping, run a scan against an account
containing both matching and non-matching resources, and confirm the matching resources are
grouped under that SDA while the rest appear in the "No SDA" bucket.

**Acceptance Scenarios**:

1. **Given** a registered SDA and its tag-value mapping, **When** a scan runs, **Then** every
   resource whose tags satisfy that mapping is attached to that SDA.
2. **Given** a resource whose tags match no registered SDA, **When** a scan runs, **Then** the
   resource appears in a visible "No SDA" bucket rather than being silently excluded from any view.
3. **Given** resources already scanned and sitting in the "No SDA" bucket, **When** an admin
   registers a new SDA whose mapping matches some of them, **Then** those resources move out of
   "No SDA" and into the new SDA starting with the next scan.
4. **Given** an admin registering a new SDA, **When** its tag-value mapping would match resources
   an existing SDA's mapping also matches, **Then** registration is refused rather than silently
   creating an ambiguous, order-dependent classification.
5. **Given** an SDA with resources currently attached to it, **When** an admin removes that SDA,
   **Then** every resource that was attached to it reverts to the "No SDA" bucket immediately —
   not waiting for the next scan, since there is no longer any SDA row left to re-match against —
   and none of those resources' scan or finding history is affected.

---

### User Story 3 - See exactly which resources fail the standard, and know when they're fixed (Priority: P1)

Once rules and inventory both exist, the platform evaluates every top-level resource against every
active rule and opens a finding for each violation — a missing required tag, a value outside the
allowed set, or a value that doesn't match the expected format. A resource is never flagged twice
for the same violation across repeated scans; the same open finding simply persists until it's
fixed. When a later scan shows the tag corrected, the finding closes itself — no one has to notice
and close it by hand.

**Why this priority**: This is the spec's namesake capability. Compliance scoring (User Story 4)
is a straightforward rollup of these findings' state, so nothing downstream is meaningful without
this running correctly first.

**Independent Test**: Run a scan against a resource missing a required tag, confirm a finding
opens; fix the tag directly in AWS, run a second scan, and confirm the same finding auto-closes
with no manual action.

**Acceptance Scenarios**:

1. **Given** a resource missing a required tag, **When** a scan evaluates it, **Then** a finding
   opens identifying the missing tag.
2. **Given** a resource whose tag value is outside a rule's allowed set, **When** a scan evaluates
   it, **Then** a finding opens identifying the invalid value, distinct from a missing-tag finding.
3. **Given** a resource whose tag value doesn't match a rule's expected format, **When** a scan
   evaluates it, **Then** a finding opens identifying the format problem, distinct from an
   invalid-value finding.
4. **Given** a resource with an already-open finding for a specific rule, **When** a later scan
   evaluates the same still-violating resource against the same rule, **Then** no second finding
   for that resource-rule pair is created.
5. **Given** a resource with an open finding, **When** its tag is corrected and a scan completes
   afterward, **Then** the finding closes automatically, with no admin action.
6. **Given** a resource that is itself attached to or a component of another discovered resource
   (for example, a volume attached to a compute instance), **When** validation runs, **Then** the
   attached resource is not independently evaluated — only the top-level resource it belongs to is.

---

### User Story 4 - See compliance at a glance, per account and per project (Priority: P1)

An admin, operator, or viewer sees, at any time, what fraction of resources are actually compliant
with the tagging standard — both for a whole account and broken down by SDA. The number is exact
enough to match what someone would get counting by hand, so it can be trusted as a governance
signal rather than treated as an estimate.

**Why this priority**: This is the metric the rest of the platform's story about "governance
signal, not just an inventory" rests on. It has no value independent of User Stories 1–3, which is
why it sits after them, but a P1 platform without a trustworthy number to show has not actually
demonstrated governance.

**Independent Test**: On a small test account with a known, hand-countable mix of compliant and
non-compliant resources, retrieve the compliance score and confirm it exactly matches the manual
count.

**Acceptance Scenarios**:

1. **Given** a connected account with some compliant and some non-compliant resources, **When**
   the account's compliance score is retrieved, **Then** it equals the count of resources with no
   open findings divided by the total count of top-level resources.
2. **Given** resources spread across multiple SDAs, **When** a specific SDA's compliance score is
   retrieved, **Then** it reflects only that SDA's resources, not the whole account's.
3. **Given** a freshly registered SDA with no resources matched to it yet, **When** its compliance
   score is retrieved, **Then** the result is well-defined (not an error) rather than a
   divide-by-zero failure.

---

### User Story 5 - Know who to talk to about any resource (Priority: P1)

For every discovered resource, the platform determines who is accountable for it by mining the
account's own audit trail for the identity that created it. When that identity is a real person,
they are recorded as the resource's owner, along with the evidence the platform used to reach that
conclusion — never a guess presented as fact.

**Why this priority**: A finding with no accountable owner is governance theater — someone has to
be reachable about it, even though this spec deliberately stops short of notifying them (Out of
Scope). This is P1 because ownership is meant to be present for every resource from the first scan
onward, not bolted on later.

**Independent Test**: Create a test resource directly in the AWS console (a human action), run a
scan, and confirm the resource's recorded owner is that console user, with evidence citing the
specific creation event.

**Acceptance Scenarios**:

1. **Given** a resource created by a human IAM principal within the last 90 days, **When**
   ownership attribution runs, **Then** that principal is recorded as the owner with evidence
   citing the creation event.
2. **Given** a resource whose creation event falls outside the last 90 days, **When** attribution
   runs, **Then** the resource is queued as unattributed rather than the platform inventing an
   owner from incomplete evidence.
3. **Given** an already-attributed resource, **When** a later scan re-evaluates it, **Then** the
   existing attribution is not overwritten by a lower-confidence result.

---

### User Story 6 - Manage projects and triage unmatched resources from a screen, not the API (Priority: P2)

An admin manages the SDA registry — creating, editing, and removing SDAs, and editing each one's
tag-value mapping — from a dedicated screen, without needing to call the API directly. The same
screen surfaces the "No SDA" bucket as a working triage list, not just a filter.

**Why this priority**: User Story 2's registry and matching behavior is fully functional through
the API alone; this story is the convenience layer on top of it; dropping it does not remove any
P1 capability, only the UI for reaching it.

**Independent Test**: From the SDA admin screen, create an SDA, edit its tag-value mapping, and
confirm the change is reflected in the "No SDA" triage list on the next scan — without touching the
API directly.

**Acceptance Scenarios**:

1. **Given** the SDA admin screen, **When** an admin creates, edits, or removes an SDA, **Then**
   the change takes effect the same way it would through the API (User Story 2).
2. **Given** the "No SDA" bucket, **When** an admin opens its triage view, **Then** every currently
   unmatched resource is listed with enough identifying detail to decide whether a new SDA mapping
   is needed.

---

### User Story 7 - Attribute ownership even when a pipeline created the resource (Priority: P2)

When a resource's creator is a pipeline, CI/CD role, or other automation identity rather than a
person, the platform falls back to the human who has modified that resource most often, provided
they've done so at least a handful of times — a weaker but still useful signal, recorded with a
lower confidence level and its own evidence trail rather than being conflated with a direct
creator attribution.

**Why this priority**: Automation-created resources are common in any real AWS estate; without
this fallback, a large share of resources would sit permanently unattributed. It is P2 because User
Story 5's direct-creator path already delivers the demonstrable, higher-confidence version of this
capability.

**Independent Test**: Create a test resource via infrastructure-as-code (a non-human creator),
have a specific person modify it at least three times, run a scan, and confirm that person is
recorded as the owner at a lower confidence level than a direct creator attribution would carry.

**Acceptance Scenarios**:

1. **Given** a resource created by a pipeline or automation identity, **When** attribution runs,
   **Then** the platform looks for the human who modified it most often instead of recording the
   automation identity as owner.
2. **Given** a human modifier who touched the resource at least three times in the lookback
   window, **When** the fallback applies, **Then** they are recorded as owner at a reduced
   confidence level, with evidence distinguishing this from a direct creation attribution.
3. **Given** no human meets the modification threshold, **When** the fallback is exhausted,
   **Then** the resource is queued as unattributed rather than attributed to a low-confidence
   guess below the threshold.

---

### User Story 8 - Resolve any attributed owner to a real email address (Priority: P2)

Whoever is attributed as a resource's owner (User Stories 5 or 7) is resolved to an email address
through a defined, configurable chain: use the resource's own owner tag if it already looks like an
email; otherwise apply an admin-configurable pattern to the audit-trail identity; otherwise consult
a manual override table an admin maintains for identities the pattern can't resolve. The pattern
itself is data an admin edits, not something requiring a code change.

**Why this priority**: An attributed owner with no resolvable contact address is only marginally
more useful than no attribution at all; this story is what makes attribution actionable. It is P2
because User Stories 5 and 7 already deliver a demonstrable, evidenced attribution without it —
this refines *how* that attribution becomes a usable email, it doesn't change whether attribution
happens.

**Independent Test**: Attribute a resource to an identity with no owner tag and no matching manual
override, confirm the configured pattern produces its email; then add a manual override for a
different identity the pattern gets wrong, and confirm the override takes precedence.

**Acceptance Scenarios**:

1. **Given** an attributed owner whose resource carries an `owner` tag that is a syntactically
   valid email, **When** identity resolution runs, **Then** that tag value is used directly.
2. **Given** an attributed owner with no usable owner tag, **When** identity resolution runs,
   **Then** the admin-configured pattern is applied to the audit-trail identity to produce an
   email.
3. **Given** an identity present in the manual override table, **When** identity resolution runs,
   **Then** the override takes precedence over the configured pattern.
4. **Given** an admin changes the configured pattern, **When** identity resolution next runs,
   **Then** it uses the new pattern with no code change or deployment.

---

### Edge Cases

- **A rule is edited while a scan is in progress**: the in-progress scan finishes evaluating under
  whichever rule version was in effect when it started; only the next scan reflects the edit — the
  same "next scan, never mid-scan" discipline spec 002 established for coverage-as-data.
- **An SDA's tag-value mapping would overlap an existing SDA's**: registration is refused outright
  (User Story 2, Acceptance Scenario 4) rather than leaving classification order-dependent and
  silently nondeterministic.
- **An SDA with resources currently attached to it is removed**: every attached resource reverts
  to the "No SDA" bucket immediately, not on the next scan (User Story 2, Acceptance Scenario 5)
  — removal deletes the SDA row itself, so there is nothing left to re-match against at scan time
  the way an edited mapping has. Removal is never refused because resources are attached to it;
  the "No SDA" bucket exists precisely to be a safe landing zone for exactly this case, not a
  failure state that blocks the admin action that created it.
- **A resource's creation event is outside the 90-day lookback window**: it is queued unattributed,
  not attributed on the basis of a guess (User Story 5, Acceptance Scenario 2).
- **A resource's only creator identity is automation, and no human meets the fallback's modification
  threshold**: it is queued unattributed rather than attributed to someone below the confidence
  threshold (User Story 7, Acceptance Scenario 3).
- **A resource attached to or dependent on another discovered resource is deleted, but the resource
  it was attached to remains**: only the attached resource's own record reflects deletion (spec
  002's existing deleted-marker mechanism); the finding and score impact is confined to whichever
  resource actually carries the tags being evaluated.
- **The same identity qualifies as both this resource's direct creator and, separately, its most
  frequent modifier**: the direct-creator attribution (User Story 5) always wins; the fallback
  path (User Story 7) is only ever consulted when no direct creator attribution exists.
- **An admin edits the manual override table for an identity that already has a resolved email
  via the pattern**: the override takes effect from the next resolution onward, without requiring
  every already-resolved resource to be manually re-triggered.
- **A tag value is technically present but empty or whitespace-only**: treated the same as a
  missing required tag, not as a value satisfying the "tag exists" requirement.

## Requirements *(mandatory)*

### Functional Requirements

#### Rules-as-data (S18) [P1]

- **FR-001**: Tagging rules MUST be stored as admin-editable data the platform reads, never logic
  compiled into it — the same coverage-as-data discipline spec 002 established for enrichment
  configuration.
- **FR-002**: A rule's tag key MUST be matched case-insensitively against a resource's actual tags
  (Acceptance Scenario US1.4).
- **FR-003**: The platform MUST ship pre-seeded with rules requiring four tags on every resource —
  project name, owner, project ID, and created-by — and a fifth, environment, recognized by the
  rule store but not included in the required set (Acceptance Scenario US1.1).
- **FR-004**: A rule MUST be able to express, independently: whether a tag is required at all,
  which values are acceptable for it (an allowed-values check), and what format its value must
  follow (a format check) — distinct enough that a violation of one produces a different finding
  kind than a violation of another (User Story 3, Acceptance Scenarios 1–3).
- **FR-005**: A change to a rule MUST take effect starting with the next scan that begins after the
  change, and MUST NOT alter the behavior of a scan already in progress when the change is made
  (Edge Cases; Acceptance Scenario US1.2, US1.3).
- **FR-006**: Every rule change MUST be versioned. A finding is tied to the rule's stable identity
  (its key), not to one specific version — an already-open finding continues to be re-evaluated
  against whichever version of that rule is currently enabled, and records which version most
  recently evaluated it, rather than being permanently pinned to the version that first opened it
  (Clarifications session 2026-08-25). This is what makes FR-016's auto-close guarantee hold across
  a rule edit: a finding opened under one version and fixed under a later, edited version still
  closes, instead of being orphaned against a superseded version no future scan will re-check.

#### SDA registry (S18a) [P1]

- **FR-007**: An admin MUST be able to register an SDA with, at minimum, a name, an owner email, a
  team, and a mapping of tag values that identify resources belonging to it.
- **FR-008**: A resource MUST be attached to an SDA by comparing its tags against every registered
  SDA's tag-value mapping at scan time, not computed on demand at query time (Acceptance Scenario
  US2.1).
- **FR-009**: A resource matching no registered SDA's mapping MUST be visibly grouped in a "No SDA"
  bucket, not silently omitted from any SDA-scoped or ownership view (Acceptance Scenario US2.2).
- **FR-010**: Registering a new SDA, or editing an existing one's tag-value mapping, MUST
  reclassify previously-unmatched or differently-matched resources starting with the next scan
  (Acceptance Scenario US2.3) — the same next-scan effective-timing rule FR-005 establishes for
  tagging rules.
- **FR-010a**: Registering or editing an SDA's tag-value mapping MUST be refused if it would
  overlap a different, already-registered SDA's mapping, so that which SDA a resource belongs to is
  never ambiguous or order-dependent (Acceptance Scenario US2.4; Edge Cases).
- **FR-010b**: An admin MUST be able to remove an SDA. Removal MUST NOT be refused on account of
  resources currently being attached to it, and MUST cause every resource that was attached to it
  to revert to the "No SDA" bucket immediately upon removal — not deferred to the next scan, since
  removal deletes the SDA itself rather than changing what it matches (Acceptance Scenario US2.5;
  Edge Cases). Removal MUST NOT alter any scan history, finding, or compliance-score history that
  already references the removed SDA's resources.

#### SDA admin UI (S18b) [P2]

- **FR-011**: The platform MUST provide a screen for creating, editing, and removing SDAs and their
  tag-value mappings, equivalent in effect to the API-level capability FR-007–FR-010b define.
  **[P2]**
- **FR-012**: The platform MUST provide a triage view listing every resource currently in the "No
  SDA" bucket, with enough identifying detail to decide whether a new or edited SDA mapping is
  needed. **[P2]**

#### Validation engine (S19) [P1]

- **FR-013**: Validation MUST evaluate rules against top-level ("parent") resources only — a
  resource that another discovered resource owns or that is attached to another discovered
  resource is not independently evaluated (User Story 3, Acceptance Scenario 6).
- **FR-013a**: The platform MUST determine which resources are top-level versus attached, using
  the attachment relationships enrichment already captures (for example, a storage volume's
  attached compute instance), and record that relationship on the resource so "top-level resource"
  has one consistent, queryable meaning rather than being re-derived differently by every caller.
- **FR-014**: A rule violation MUST open a finding identifying which kind of violation it is
  (missing required tag, disallowed value, or non-standard format) (Acceptance Scenarios US3.1–3).
- **FR-015**: A resource already carrying an open finding for a specific rule MUST NOT receive a
  second open finding for that same resource-rule combination on a later scan that still finds the
  same violation (Acceptance Scenario US3.4).
- **FR-016**: A finding MUST close automatically, with no admin action, the first time a scan
  evaluates the resource and finds the violation no longer present (Acceptance Scenario US3.5).
- **FR-017**: Validation MUST run only as part of a scan that completed successfully or partially,
  never a scan recorded as failed — the same completion gating spec 002 already applies to its own
  deleted-marker diffing.

#### Compliance scoring (S20) [P1]

- **FR-018**: A compliance score MUST be computable for an account as a whole and for each SDA
  within it, defined as the count of top-level resources with zero open findings divided by the
  total count of top-level resources in that scope (Acceptance Scenarios US4.1, US4.2).
- **FR-019**: A compliance score MUST be retrievable through the platform's API without requiring
  the caller to recompute it from raw findings themselves.
- **FR-019a**: A compliance score for a scope with zero top-level resources MUST be well-defined
  (for example, reported as "no data" or 100%, not a computation error) (Acceptance Scenario US4.3).

#### Ownership attribution (S21) [P1]

- **FR-020**: For every resource, the platform MUST attempt to determine its creator by examining
  the scanned account's own audit trail for creation activity within the preceding 90 days
  (Acceptance Scenario US5.1).
- **FR-021**: When the identified creator is a human IAM principal, that principal MUST be recorded
  as the resource's owner together with evidence identifying the specific audit event the
  attribution rests on (Acceptance Scenario US5.1).
- **FR-022**: A resource whose creation activity falls outside the 90-day lookback window, or whose
  creator cannot be determined at all, MUST be left queued as unattributed rather than assigned a
  guessed owner (Acceptance Scenario US5.2).
- **FR-023**: An existing attribution MUST NOT be silently overwritten by a later, lower-confidence
  result on a subsequent scan (Acceptance Scenario US5.3).

#### Attribution fallback (S22) [P2]

- **FR-024**: When the identified creator is a pipeline, CI/CD, or other automation identity rather
  than a human, the platform MUST fall back to identifying the human who has most frequently
  modified that resource within the lookback window. **[P2]**
- **FR-025**: The fallback attribution MUST require the identified human to have made at least
  three modifying (write) events against the resource, and MUST be recorded at a lower confidence
  level than a direct-creator attribution, with its own evidence trail distinguishing it as a
  fallback (Acceptance Scenario US7.2). **[P2]**
- **FR-026**: A resource with no human creator and no human modifier meeting the fallback threshold
  MUST be queued as unattributed rather than attributed below the confidence threshold (Acceptance
  Scenario US7.3). **[P2]**

#### Owner identity resolution (S23a) [P2]

- **FR-027**: Resolving an attributed owner to a contact email MUST follow a defined precedence:
  the resource's own owner tag if its value is a syntactically valid email address; otherwise an
  admin-configurable pattern applied to the audit-trail identity; otherwise a manual override table
  an admin maintains per identity (Acceptance Scenarios US8.1–3). **[P2]**
- **FR-028**: The identity-resolution pattern MUST be admin-editable configuration, not logic
  requiring a code change or redeployment to alter (Acceptance Scenario US8.4). **[P2]**

#### Access control

- **FR-029**: Creating or editing a tagging rule, registering or editing an SDA, and editing the
  identity-resolution pattern or its manual override table MUST be restricted to the admin role,
  consistent with spec 002's established pattern for governance-configuration actions.
- **FR-030**: Viewing findings, compliance scores, SDA groupings, and resource ownership MUST be
  permitted for all three CloudPulse roles — admin, operator, and viewer — consistent with spec
  002's precedent that read access to governance state is open to every role.

### Key Entities *(include if feature involves data)*

This spec populates entities whose *shape* spec 1 already defined and reserved for it (its Key
Entities section names `Rule`, `Finding`, `Sda`, and `ResourceOwner`) — this spec defines their
behavior, not their schema.

- **Rule**: a single tagging requirement, expressed as data — a tag key, whether it's required,
  its allowed values and/or expected format, and a version number. A rule's *key* is its stable
  identity across edits; each edit is a new version of that same key, not a new, unrelated rule
  (Clarifications session 2026-08-25).
- **Finding**: one resource's violation of one rule *key* — its kind (missing/invalid/format),
  severity, open/resolved status, and the timestamps marking when it opened and, if applicable,
  resolved. Tracks which rule version most recently evaluated it, but is not pinned to that
  version — a later edit to the same rule key continues to re-evaluate this same finding, not
  spawn a separate one (Clarifications session 2026-08-25).
- **Sda**: a registered internal project or team, with the tag-value mapping that identifies which
  resources belong to it.
- **ResourceOwner**: the human attributed as accountable for one resource, together with a
  confidence level and the evidence the attribution rests on.
- **Compliance Score**: a computed (not independently stored) ratio of compliant to total top-level
  resources, for an account or for one SDA within it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Editing a tagging rule changes which findings are open starting with the next scan
  that begins after the edit — never the scan already in progress — with zero code deployment.
- **SC-002**: A tag corrected directly in AWS causes its corresponding finding to close
  automatically after the next completed scan, with no manual step.
- **SC-003**: An account's and an SDA's compliance scores exactly match a manual, hand-counted tally
  performed against the same test account's resources and findings.
- **SC-004**: Creator attribution succeeds — records a human owner with evidence — for 100% of
  resources created through the AWS console in a test account.
- **SC-005**: The attribution fallback chain is exercised and produces a correctly lower-confidence
  attribution for at least one resource created through infrastructure-as-code in a test account.
- **SC-006**: A resource matching no registered SDA is visible in the "No SDA" bucket in every view
  that lists resources by SDA, never silently absent.
- **SC-007**: Registering a new SDA, or editing an existing one's tag-value mapping, causes every
  previously-unmatched resource it now matches to reclassify by the next regularly scheduled or
  on-demand scan — no separate reclassification trigger is needed.
- **SC-008**: An admin can create, edit, and disable a tagging rule entirely through the platform's
  existing interfaces, with no code change or redeployment at any point.

## Assumptions

- **"Parent resource" is derived from attachment relationships enrichment already captures, not a
  new discovery mechanism.** Spec 002's enrichment already records, for several P1 types, which
  other resource a resource is attached to (for example, an EBS volume's attached EC2 instance, an
  Elastic IP's associated instance). This spec treats a resource identified as attached to another
  discovered resource as a child, and everything else as a top-level ("parent") resource — the
  first spec to make use of the `parent_resource_id` relationship spec 1's schema already reserved
  but spec 002 left unpopulated (FR-013a).
- **The audit-trail source is AWS CloudTrail's always-on Event History, not a configured Trail.**
  Every AWS account has 90 days of management-event history available with zero setup and no write
  action against the account — matching this spec's stated 90-day lookback exactly, and requiring
  only one additional read-only permission (`cloudtrail:LookupEvents`) on the scanner role spec 002
  already established. Enabling or configuring a Trail resource is out of scope; if it were needed,
  it would be a write action against a scanned account, which spec 002's FR-005 forbids regardless.
- **Finding severity is chosen by the admin as part of a rule's own definition**, defaulting to
  medium when a rule doesn't specify one — the same data-not-code treatment as every other part of
  a rule (FR-001), rather than a fixed mapping from violation kind to severity hardcoded into the
  platform.
- **SDA-matching ambiguity is prevented at registration time, not resolved at match time.**
  Rejecting an overlapping tag-value mapping when an SDA is registered or edited (FR-010a) is
  simpler and more predictable than picking a tie-break rule (first-registered, most-specific,
  etc.) that would make classification depend on registration order.
- **Managing rules, the SDA registry, and identity-resolution configuration is admin-only; viewing
  findings, scores, groupings, and ownership is open to every role** — the same non-hierarchical
  role split spec 002 established for its own account-management and viewing surfaces (FR-029,
  FR-030), applied here rather than inventing a new access model for this spec's own configuration
  surfaces.
- **An empty or whitespace-only tag value is treated as equivalent to a missing tag** for a
  required-tag rule, rather than satisfying the "tag exists" check on a technicality (Edge Cases).
- **Cost-consciousness (playbook §0.5.3) applies to this spec's own infrastructure**: any scanning
  role permission additions (CloudTrail read access) and any new orchestration this spec's
  validation/scoring/attribution steps require are sized for demo-scale accounts, and any live
  verification against a real AWS account follows the same live-verify-then-teardown discipline
  specs 1 and 2 established.

## Dependencies

- Spec 1's `Rule`, `Finding`, `Sda`, and `ResourceOwner` tables, and the `FindingSeverity`,
  `FindingStatus`, and `OwnerConfidence` enums, exist with the shape this spec's Key Entities
  section builds on; this spec does not create new tables for these four entities, only defines
  their behavior.
- Spec 2's `Resource` and `Scan` tables, whole-account discovery, and AWS connector are what this
  spec reads from — this spec introduces no new discovery mechanism and consumes spec 2's inventory
  as input, exactly as spec 002's own Out of Scope section already anticipated ("Tag validation...
  owned by spec 3, which consumes this spec's inventory as input").
- Spec 2's scanner role (same-account execution identity and cross-account `AssumeRole` role) needs
  one additional read-only IAM permission — `cloudtrail:LookupEvents` — added to its policy. This
  is an extension of spec 2's existing role, not a new connection mode or trust relationship.
- Spec 2's scan orchestration (its Step Functions fan-out and per-unit-of-work lifecycle) is what
  this spec's validation, scoring, and attribution steps run inside — this spec does not invent a
  second orchestration mechanism.

## Out of Scope

- Notifying resource owners about open findings — cut from MVP; findings and ownership are visible
  on the dashboard only. A future spec may add notification.
- Executing remediation of any kind — fixing a tag, deleting a non-compliant resource, or any other
  write action against a scanned account. This spec only detects and reports.
- AI-generated suggestions for fixing findings, classifying resources into SDAs, or resolving
  ownership — owned by spec 6, which reads this spec's data as input.
- Cost or utilization-based scoring of any kind — owned by spec 5.
- Support for any cloud provider other than AWS — same provider-agnostic-interface-but-AWS-only
  precedent spec 2 established; this spec adds no new connector capability of its own.
