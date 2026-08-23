# Feature Specification: Account Onboarding and Discovery

**Feature Branch**: `pods/pod73-002-account-onboarding-and-discovery`

**Created**: 2026-08-23

**Status**: Draft

**Input**: User description: "Enable an operator to connect AWS accounts to CloudPulse AI using roles only, and give the platform a complete, continuously refreshed inventory of everything that exists in those accounts — without maintaining a hardcoded service list. Functional scope (backlog S8–S17, S47 + AI-ready coverage): roles-only access (same-account and cross-account with ExternalId, no access keys); account registration with dry-run verification; an accounts admin page; a normalized, provider-agnostic resource model and connector contract; whole-account discovery via generic discovery surfaces (not a hand-picked service list); deep enrichment for governance-critical services (P1: EC2, EBS, EIP, S3, RDS, Lambda; P2: EKS, DynamoDB, ELB, IAM); coverage-as-data; scan orchestration (fan-out, retries, concurrency limits, daily schedule plus on-demand); persistence with lifecycle (raw snapshots, current-state diffing, first-seen/last-seen/deleted markers, auto-close on disappearance); scan history (P2). Success criteria: onboard a fresh account in under 5 minutes; a scan lands over 95% of actual resources including untagged ones; deleting a resource in AWS closes it in inventory on the next scan; cross-account access fails closed without the ExternalId. Out of scope: tag validation (spec 3), any write access to scanned accounts, non-AWS providers (interface only)."

## Clarifications

### Session 2026-08-23

- Q: When an operator removes a connected account, should the platform keep its historical
  resource, scan, and finding data as a read-only record, or delete it outright? → A: Deactivate
  only — stop scanning, keep all historical data read-only and visible. Matches spec 1's
  precedent (audit events retained indefinitely, nothing silently purged).
- Q: Should the platform generate the cross-account external-id value itself, or should the
  operator supply their own? → A: Platform-generated, unique per account, high-entropy, shown to
  the operator to paste into the cross-account template. An operator-chosen value could be weak,
  reused, or guessed, undermining the exact protection FR-003 depends on.
- Q: Can an operator bring a deactivated account back into active scanning, and if so, how? → A:
  Yes, via a direct reactivate action — no re-registration needed. Without this, FR-009's
  duplicate-registration refusal and FR-009a's deactivation would have left no path back in.

## User Scenarios & Testing *(mandatory)*

<!--
  Priority labels below use the CloudPulse AI constitution's tier semantics (Principle VIII):
  P1 = demo-critical, frozen scope; P2 = stretch, must never block or destabilise a P1 path.
  Stories are listed in dependency order within each tier, not in order of relative importance.
-->

### User Story 1 - Connect an account without ever handling a credential (Priority: P1)

An operator wants CloudPulse AI to see into an AWS account — the one the platform already
runs in, or a separate one entirely. They register the account by pointing the platform at a
role, never an access key. For a separate account, they first deploy a small, platform-provided
template that creates a scanner role trusting only CloudPulse AI's own identity and a
platform-issued secret value; for the platform's own account, no separate deployment is needed.
Registration itself proves the role actually works before it is accepted.

**Why this priority**: Nothing else in this spec — or in specs 3, 4, and 5, all of which depend on
inventory existing — can happen until at least one account is connected. It is also the
platform's first and most consequential trust boundary: a credential model that can be gotten
wrong here is wrong everywhere downstream.

**Independent Test**: Register the account the platform itself runs in, confirm it is accepted
and marked verified. Separately, attempt to register an account using a role with no trust
condition guarding it, or an access key instead of a role, and confirm both are rejected before
they are stored.

**Acceptance Scenarios**:

1. **Given** an operator with the platform's own AWS account, **When** they register it in
   same-account mode, **Then** the platform verifies read access using its own execution identity
   and marks the account verified, with no separate role or template involved.
2. **Given** an operator with a separate AWS account, **When** they deploy the platform-provided
   template into that account and register it in cross-account mode with the resulting role,
   **Then** the platform verifies it can assume the role and marks the account verified.
3. **Given** a cross-account role whose trust policy does not require the platform-issued secret
   value, **When** registration is attempted, **Then** it is refused before the account is stored,
   with a message identifying the missing condition.
4. **Given** an operator who supplies an access key pair instead of a role reference, **When** they
   attempt registration, **Then** the platform refuses it — access keys are not an accepted input
   at all, not merely an unverified one.
5. **Given** a role reference that does not exist or cannot be assumed, **When** registration is
   attempted, **Then** it is refused with a message distinguishing "role not found" from "role
   found but assumption failed" wherever the underlying error makes that possible.
6. **Given** a verified account, **When** the role behind it is later deleted or its trust policy
   is changed outside the platform, **Then** the next scan attempt fails verification and the
   account's status reflects that failure rather than silently reporting zero resources.

---

### User Story 2 - See and manage every connected account in one place (Priority: P1)

An operator manages the fleet of connected accounts from a single screen: which accounts exist,
whether each is currently verified, what regions each scans, and when each last scanned
successfully. Adding an account, deactivating one that is no longer wanted and reactivating it
later, and seeing why one has stopped working, all happen here — never by going into the AWS
console except to deploy the cross-account template itself.

**Why this priority**: Registration alone is not manageable at scale without visibility into it.
This is also the only P1 surface this spec's frontend work delivers, so it is priority alongside
registration rather than after it.

**Independent Test**: With one account registered, load the accounts view and confirm its identity,
mode, region list, verification status, and last-scan summary are all visible and correct without
querying the API or the database directly.

**Acceptance Scenarios**:

1. **Given** one or more registered accounts, **When** an operator opens the accounts view,
   **Then** each account's mode, connection identity, region list, verification status, and most
   recent scan outcome are all visible.
2. **Given** the accounts view, **When** an operator adds a new account, **Then** the same
   registration and verification flow from User Story 1 runs without leaving this screen (aside
   from deploying a cross-account template, which happens in the target AWS account).
3. **Given** an account whose verification has failed, **When** an operator views it, **Then** the
   failure reason is shown in language that tells them what to fix, not just that something broke.
4. **Given** an account's region list, **When** an operator edits it, **Then** the change takes
   effect from the next scan onward without re-registering the account.
5. **Given** a connected account an operator no longer wants scanned, **When** they deactivate it,
   **Then** it stops appearing in future scan runs while its historical resources, scans, and
   findings remain visible and browsable exactly as before.
6. **Given** a deactivated account, **When** an operator reactivates it, **Then** it resumes its
   normal scan schedule from the next cycle without needing to be re-registered.

---

### User Story 3 - Discover everything in an account, not a curated subset (Priority: P1)

Once an account is connected, the platform finds every resource in it — every AWS service the
account actually uses, not a hand-picked list the platform's authors happened to anticipate.
Resources with no tags at all are found exactly as reliably as tagged ones. What comes back is
one consistent shape regardless of which AWS service a resource belongs to, so everything
downstream (compliance, dashboards, cost) can work against inventory without knowing AWS's
service-by-service API differences.

**Why this priority**: This is the spec's namesake capability and the one every later spec reads
from. A platform that finds only a preset service list is not meaningfully different from a
static asset spreadsheet, and specs 3–5 would inherit that same blind spot silently.

**Independent Test**: Introduce a resource type into a test account that the platform's authors
did not specifically anticipate, alongside a deliberately untagged resource of a well-known type.
Run a scan and confirm both appear in inventory with the same shape and completeness as an
anticipated, tagged resource.

**Acceptance Scenarios**:

1. **Given** a connected account containing resources across many AWS services, **When** a scan
   runs, **Then** the resulting inventory includes resources from services the platform's
   authors did not enumerate in advance, discovered through the account's general resource
   listing rather than a fixed per-service list.
2. **Given** a resource with no tags, **When** it is discovered, **Then** it appears in inventory
   with the same completeness as a fully tagged resource of the same type.
3. **Given** any two resources from different AWS services, **When** both are returned in
   inventory, **Then** both conform to the same normalized shape: provider, owning account,
   a stable unique identifier, service, native resource type, region, name, tags, current state,
   creation time, and a service-specific detail payload.
4. **Given** a resource belonging to one of the governance-critical service categories (compute,
   storage, database, or serverless), **When** it is discovered, **Then** its enrichment detail
   additionally includes that category's state, size or class, attachment, and runtime
   information — not just the identity fields every resource carries.
5. **Given** which resource types receive deep enrichment and how, **When** that configuration
   changes, **Then** the next scan reflects it without any code change or redeployment.

---

### User Story 4 - Keep inventory current without anyone asking (Priority: P1)

Every connected account is scanned on a regular schedule with no operator action, and an operator
can also trigger an immediate scan when they need current data right now. A resource that
disappears from AWS is reflected as gone in inventory on the very next scan — not left behind as
a stale, misleading record.

**Why this priority**: Inventory that goes stale is worse than no inventory, because it is
trusted by default. This is the P1 story that makes every other P1 story's data trustworthy on
an ongoing basis rather than only at the moment of first discovery.

**Independent Test**: After an initial scan, delete a resource directly in AWS. Trigger a scan
and confirm the resource is marked gone in inventory without any manual intervention.

**Acceptance Scenarios**:

1. **Given** a connected, verified account, **When** its scheduled scan time arrives, **Then**
   a scan runs automatically with no operator action.
2. **Given** a connected account, **When** an operator requests an immediate scan, **Then** it
   starts without waiting for the schedule and its progress is visible.
3. **Given** a resource present in a prior scan, **When** a new scan no longer finds it,
   **Then** it is marked deleted in current inventory rather than removed outright, and any
   finding still open against it closes automatically.
4. **Given** a resource seen for the first time, **When** it is discovered, **Then** its
   first-seen time is recorded and preserved across every later scan that still finds it.
5. **Given** a scan that fails before completing (for example, because access to the account was
   lost), **When** the failure is detected, **Then** no resource is marked deleted on the basis of
   that scan, and the failure is visibly distinguishable from "the account legitimately has no
   resources."
6. **Given** two scans of different accounts, **When** both are due at the same time, **Then**
   they run without one blocking or corrupting the other's results.

---

### Edge Cases

- **Cross-account role deleted or re-trusted after verification**: the next scan attempt must fail
  closed and mark the account's status accordingly (US1 scenario 6) — it must never be
  misinterpreted as "the account now has zero resources."
- **A scan that partially completes**: some regions or service groups succeed and others fail
  within one scan run. Resources found in the succeeded portions are recorded normally; the
  failed portions must not cause resources they were responsible for to be marked deleted, and
  the scan's own record must reflect a partial, not full, success.
- **The same account registered twice**, once same-account and once by mistake as cross-account
  (or vice versa): the platform must detect the duplicate identity and refuse the second
  registration rather than scanning the same account twice under two records.
- **A resource that changes identity-relevant fields between scans** (for example, a resource
  moved between regions, where the underlying platform represents that as delete-then-recreate
  rather than update): must not be misread as one resource silently vanishing while an unrelated
  new one silently appears — the normalized model's unique identifier is what a later spec's
  history/audit trail depends on being trustworthy.
- **A region added to an account's scan list after resources already exist there**: the next scan
  must discover the region's existing resources as newly first-seen, not backdate their
  first-seen time to before the region was in scope.
- **Coverage-as-data configuration is edited while a scan is in progress**: the in-progress scan
  completes under whichever configuration was in effect when it started, and only the next scan
  picks up the change — a scan must not read a moving target mid-run.
- **A very large account** (tens of thousands of resources): registration and the first scan's
  progress must remain visible and the scan must not appear "stuck" with no feedback, even if it
  legitimately takes longer than a small account's scan.
- **A reactivated account whose role was deleted or changed while it was deactivated**: reactivation
  does not itself re-verify the role — the same scan-failure handling that covers a role going bad
  on an active account (US1 scenario 6) applies identically to a reactivated one on its next scan
  attempt, rather than needing a separate reactivation-time verification path.

## Requirements *(mandatory)*

### Functional Requirements

#### Roles-only access (S8) [P1]

- **FR-001**: The platform MUST connect to an AWS account using an IAM role only. Access keys or
  any other long-lived credential MUST be rejected as a registration input, not merely left
  unverified.
- **FR-002**: The platform MUST support exactly two connection modes: same-account, where the
  platform reaches the account it already runs in using its own execution identity granted a
  read-only policy, and cross-account, where the platform assumes a role in a separate account
  that trusts the platform's identity and a platform-issued external-id value.
- **FR-003**: A cross-account role MUST be usable only by the platform's own identity, and only
  when the caller supplies the specific external-id value the platform issued for that account.
  A role missing this condition MUST be refused at registration (Edge Cases; constitution
  Principle III).
- **FR-003a**: The external-id value MUST be generated by the platform, unique per account, and of
  sufficient entropy that it cannot be practically guessed. The platform MUST NOT accept an
  operator-supplied external-id (Clarifications session 2026-08-23) — the whole point of the value
  is to be something only the platform knows in advance, and an operator-chosen value could be
  weak, reused across accounts, or guessed.
- **FR-004**: The platform MUST provide a ready-to-deploy template that creates a correctly
  scoped, read-only cross-account role, so an operator's only manual AWS-console step for
  cross-account onboarding is deploying that template.
- **FR-005**: Every permission the platform holds against a scanned account MUST be read-only.
  No functional requirement in this spec authorizes writing to, modifying, or deleting anything
  in a scanned account.

#### Account registration (S9) [P1]

- **FR-006**: Registering an account MUST require, at minimum: connection mode, a role reference,
  and a list of regions to scan, defaulting to a single region when none is supplied.
- **FR-007**: Registration MUST verify the supplied role by attempting a real, read-only action
  against the target account before the account is accepted. A role reference that cannot be
  assumed, or that can be assumed but grants no usable read access, MUST be refused with a
  message distinguishing those two failure kinds wherever the underlying provider error allows.
- **FR-008**: An account's region list MUST be editable after registration without requiring the
  account to be re-registered.
- **FR-009**: The platform MUST refuse to register the same underlying AWS account twice,
  regardless of which connection mode is used for either attempt (Edge Cases).
- **FR-009a**: An operator MUST be able to deactivate a connected account. Deactivation MUST stop
  future scheduled and on-demand scans of that account, but MUST NOT delete its historical
  resource, scan, or finding data — that data remains read-only and visible (Clarifications
  session 2026-08-23).
- **FR-009b**: A scan already in progress when an account is deactivated MUST be allowed to
  complete normally; deactivation prevents the *next* scan from starting, not the current one
  from finishing.
- **FR-009c**: An operator MUST be able to reactivate a deactivated account directly, without
  re-registering it, resuming its normal scan schedule from the next cycle onward (Clarifications
  session 2026-08-23). FR-009's duplicate-registration refusal governs *registering a new
  account record*; it does not apply to reactivating an existing one, and reactivation MUST NOT
  require a role reference or region list to be re-supplied unless the operator chooses to change
  them.

#### Accounts admin surface (S10) [P1]

- **FR-010**: The platform MUST expose a view listing every registered account together with its
  connection mode, region list, current verification status, active/deactivated status, and most
  recent scan outcome.
- **FR-011**: An operator MUST be able to register a new account, trigger an on-demand scan of an
  existing one, and deactivate or reactivate an existing one, from this view without leaving it.
- **FR-012**: When an account's verification has failed, this view MUST show the reason in terms
  an operator can act on (Acceptance Scenario US2.3) — not only a generic failure indicator.

#### Normalized resource model and connector contract (S11) [P1]

- **FR-013**: Every discovered resource, regardless of which AWS service it belongs to, MUST
  conform to one normalized shape: provider, owning account, a stable unique identifier, service,
  native resource type, region, name, tags, current state, creation time, and a
  service-specific detail payload for enrichment data that does not generalize across services.
- **FR-014**: The mechanism used to reach a cloud provider and translate its resources into the
  normalized shape MUST be isolated behind one interface, so that a second cloud provider could
  be added later by implementing that interface without changing any code that consumes
  normalized resources (constitution Principle V; spec 1's FR-054 reserves the package this
  interface lives in and forbids provider SDK types leaking past it — this spec defines the
  interface itself).
- **FR-015**: A resource's unique identifier MUST remain stable across scans for as long as the
  same underlying cloud resource exists, so that first-seen tracking and later specs' history and
  audit trails can rely on it (Edge Cases).

#### Whole-account discovery (S12, evolved) [P1]

- **FR-016**: A scan MUST enumerate resources using the cloud provider's general-purpose,
  service-agnostic discovery surfaces, rather than a fixed, hand-maintained list of services the
  platform's authors anticipated in advance.
- **FR-017**: Discovery MUST find resources regardless of whether they carry any tags. An
  untagged resource MUST appear in inventory with the same completeness as a tagged resource of
  the same type (Acceptance Scenario US3.2).
- **FR-018**: A resource that exists once but is visible from a provider's global (not
  region-specific) surface MUST be recorded once per account, not once per scanned region.

#### Deep enrichment for governance-critical services (S13, S14, S47) [P1 core, P2 extended]

- **FR-019**: For compute, storage, database, and serverless resources — at minimum EC2 instances,
  EBS volumes, Elastic IPs, S3 buckets, RDS instances, and Lambda functions — enrichment MUST
  additionally capture that resource's state, size or class, attachment relationships, and
  runtime or creation details beyond the fields every resource carries. **[P1]**
- **FR-020**: Enrichment for container orchestration, additional database types, load balancing,
  and account-level IAM inventory (at minimum EKS, DynamoDB, ELB, and IAM) MAY be added without
  being required for the P1 demo path. **[P2]**

#### Coverage-as-data [P1 foundation]

- **FR-021**: Which resource types receive deep enrichment, and what that enrichment captures,
  MUST be configuration the platform reads rather than logic compiled into it — extending
  coverage to a new resource type MUST NOT require a code change or a redeployment (Acceptance
  Scenario US3.5).
- **FR-022**: A change to coverage configuration MUST take effect starting with the next scan
  that begins after the change, and MUST NOT alter the behavior of a scan already in progress
  when the change is made (Edge Cases).

#### Scan orchestration (S15) [P1]

- **FR-023**: A scan MUST be broken into independent units of work — at minimum, one unit per
  combination of account, region, and service group — each able to succeed, fail, or retry
  without requiring every other unit of the same scan to be re-run.
- **FR-024**: A failed unit of work within a scan MUST be retried a bounded number of times before
  the scan records that unit as failed; retrying MUST NOT be unbounded.
- **FR-025**: The number of scans and units of work running at once MUST be limited, so that
  scanning many accounts concurrently cannot overwhelm either the platform or the cloud
  provider's own request limits.
- **FR-026**: Every connected, verified account MUST be scanned automatically on a recurring daily
  schedule with no operator action, and MUST also be scannable on demand at an operator's request
  (Acceptance Scenarios US4.1, US4.2).
- **FR-027**: Two scans of the same account MUST NOT run concurrently; two scans of different
  accounts MUST be able to run concurrently without interfering with each other (Edge Cases).

#### Persistence with lifecycle (S16) [P1]

- **FR-028**: Every scan MUST store the raw, unmodified result of that scan as an immutable
  record, separate from the current-state view that later scans update.
- **FR-029**: A resource seen for the first time MUST record when it was first seen; a resource
  seen again in a later scan MUST have its last-seen time updated while its first-seen time is
  preserved unchanged (Acceptance Scenario US4.4).
- **FR-030**: A resource present in a prior scan but absent from a new, successfully completed
  scan MUST be marked deleted rather than removed from the record, and any open finding
  referencing it MUST close automatically as a consequence (Acceptance Scenario US4.3; findings
  themselves are spec 3's concern — this spec is responsible for the resource-level deleted
  marker and the trigger, not the finding-closure mechanics).
- **FR-031**: A scan that fails before completing MUST NOT cause any resource to be marked
  deleted on the basis of that scan, and MUST be distinguishable in the scan's own record from a
  scan that completed and legitimately found nothing new missing (Edge Cases; Acceptance
  Scenario US4.5).
- **FR-032**: A scan that completes only partially (some units of work succeeded, others
  exhausted their retries and failed) MUST record resources found by the succeeded units
  normally, MUST NOT mark anything deleted on the basis of the failed units, and MUST record
  itself as partially, not fully, successful (Edge Cases).

#### Scan history (S17) [P2]

- **FR-033**: Every scan MUST have a retrievable record of what triggered it, when it ran, how
  long it took, how many resources it found, and its outcome (succeeded, partially succeeded, or
  failed). **[P2]**

### Key Entities *(include if feature involves data)*

This spec populates entities whose *shape and lifecycle* spec 1 already defined (its Key Entities
section names `Account`, `Resource`, and `Scan` as populated by this spec) and adds the
configuration concept coverage-as-data introduces.

- **Account**: a registered AWS account belonging to a tenant, holding its connection mode, role
  reference, scan-region list, and active/deactivated status — never a credential (spec 1's
  schema; behavior specified here, including deactivation per Clarifications session
  2026-08-23).
- **Resource**: a normalized, provider-agnostic record of one thing discovered in an account —
  identity, type, location, tags, parent relationship, and lifecycle markers (first-seen,
  last-seen, deleted) (spec 1's schema; behavior specified here).
- **Scan**: one execution of discovery against an account — trigger, timing, counts, and outcome,
  including the partial-success case this spec adds (spec 1's schema; behavior specified here).
- **Coverage Definition**: which resource types receive deep enrichment and what that enrichment
  captures, held as data an operator or a later spec's AI coverage advisor can change without a
  code deployment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator connects a fresh AWS account — same-account or cross-account — and sees
  it marked verified in under 5 minutes, not counting the time to deploy a cross-account template
  in the target account.
- **SC-002**: A scan of a connected account discovers more than 95% of that account's actual
  resources, verified by manual sampling against the AWS console, including resources carrying no
  tags at all.
- **SC-003**: A resource deleted directly in AWS is marked deleted in inventory after the next
  completed scan of that account, with no manual step.
- **SC-004**: An attempt to assume a cross-account role without the correct external-id value is
  refused, 100% of attempts, and no such attempt results in a verified account.
- **SC-005**: Adding a new enrichable resource type, or changing what an existing one captures,
  takes effect on the next scan with zero code changes and zero redeployment.
- **SC-006**: A scan that fails partway through never results in a resource being marked deleted
  on the basis of the portion that failed — verified by forcing a partial failure and confirming
  the unaffected resources' deleted markers are unchanged.
- **SC-007**: Two accounts' scans, triggered at the same time, both complete with correct,
  non-interleaved results.
- **SC-008**: Deactivating an account stops it being included in the next scheduled or on-demand
  scan cycle, while every resource, scan, and finding it already produced remains fully browsable
  with no loss of data. Reactivating it resumes scanning from the next cycle with no
  re-registration step.

## Assumptions

- **Same-account mode reuses the platform's own execution identity.** Rather than an
  AssumeRole hop within the same account, the platform's own compute is granted a dedicated
  read-only policy for same-account scanning — there is no meaningful trust boundary to cross
  when the account is already the platform's own, so the cross-account AssumeRole+ExternalId
  mechanism (FR-002, FR-003) is reserved for genuinely separate accounts.
- **The cross-account template is a standard AWS-native deployment artifact** an operator applies
  in the target account through their own AWS access — this spec provides and verifies against
  it, but does not extend to giving the platform any access to deploy it on the operator's
  behalf, which would itself require credentials to the target account before that account is
  ever connected.
- **Deactivation is a status change, not deletion, and full deregistration remains out of scope.**
  FR-009a/FR-009b resolve *whether* an account can be taken out of active scanning and what
  happens to its data (Clarifications session 2026-08-23); permanently erasing an account's
  record and its cascading effect on spec 3's findings lifecycle is a separate, harder question
  deliberately left for spec 3 to define when it exists, not invented here on its behalf.
- **Global-surface resources are recorded once per account** (FR-018) using whichever scanned
  region's unit of work reaches them first; which region that is is an implementation detail, not
  a behavior a caller should depend on.
- **Retry counts, per-scan concurrency limits, and the exact scan schedule's time of day** are
  operational tuning values, not requirements — a reasonable default is set in
  implementation and adjusted if the P1 timing/reliability success criteria are not met in
  practice.
- **"Governance-critical services" for P1 enrichment is the fixed list in FR-019** (EC2, EBS, EIP,
  S3, RDS, Lambda) — this is deliberately narrower than "every service," because whole-account
  discovery (FR-016) already guarantees every resource is *found*; P1 enrichment depth is reserved
  for the services specs 3–5's governance, compliance, and cost stories actually need detail from.
- **Cost-consciousness (playbook §0.5.3) applies to this spec's own infrastructure**: scan
  orchestration, retries, and concurrency limits must be sized for demo-scale accounts, not
  production fleets, and any live-verification session against a real AWS account follows the
  same live-verify-then-teardown-and-cost-sweep discipline spec 1 established.

## Dependencies

- Spec 1's `Account`, `Resource`, and `Scan` tables exist with the shape this spec's Key Entities
  section builds on; this spec does not create new tables for those three entities, only defines
  their behavior.
- Spec 1's `backend/connectors/` package boundary (FR-054) is where this spec's connector
  interface (FR-014) is implemented; this spec must not let a provider SDK type cross out of it.
- Spec 1's read-only, tenant-scoped agent access path (FR-056) is what a future spec 6 coverage
  advisor will read inventory through — this spec does not itself grant spec 6 any access, but
  must not introduce a second, competing path to the same data.
- An AWS account is available for same-account verification, and a second, separate AWS account
  is available for cross-account verification (mirroring spec 1's dev/prod account pair).

## Out of Scope

- Tag validation, compliance rule evaluation, SDA grouping, and ownership attribution — owned by
  spec 3, which consumes this spec's inventory as input.
- Any write, modify, or delete access to a scanned account, under any connection mode.
- Support for any cloud provider other than AWS at runtime — the connector interface (FR-014) is
  built provider-agnostic, but only an AWS connector is implemented by this spec.
- Permanently deregistering (erasing) a connected account — deactivation (FR-009a) is in scope;
  permanent deletion is not (see Assumptions).
- The AI coverage advisor that proposes coverage-as-data extensions — owned by spec 6, which
  reads this spec's coverage configuration as data but does not have its proposal mechanism built
  here.
