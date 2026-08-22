# Feature Specification: Platform Foundation

**Feature Branch**: `pods/pod73-001-platform-foundation`

**Created**: 2026-08-22

**Status**: Draft

**Input**: User description: "Build the engineering and operational foundation of CloudPulse AI, an internal cloud governance platform operated by a small platform team, so that all product features can be developed, deployed, and observed safely by a 6-person POD. Users and roles: platform users sign in with organizational identity and hold exactly one role — admin (manage accounts, rules, SDAs), operator (run scans, work findings), or viewer (read-only dashboards). Unauthenticated users see nothing. Functional scope (backlog S1–S7): reproducible environments (S1) [P1]; continuous integration (S2) [P1]; continuous delivery (S3) [P1]; governance data store (S4) [P1]; identity (S5) [P1]; API skeleton (S6) [P1]; observability (S7) [P2]. Success criteria: a brand-new cloud account reaches a working dev environment in under one hour using only the repo; a broken test provably blocks a merge; a forced failure raises an alert. Out of scope: any product feature behavior (owned by specs 2–6), email notifications to resource owners (cut from MVP)."

## Clarifications

### Session 2026-08-22

- Q: What happens to prod's governance data when FR-005 says every environment must be fully destroyable and re-creatable — is prod's data store genuinely disposable, or protected? → A: Teardown is a dev-only capability. Prod's data store carries deletion protection and destroying prod requires a deliberate out-of-band step; automated daily backups are retained, restore drills remain out of scope.
- Q: How long should the platform keep audit events, structured logs, and prod backups before they expire? → A: Per data class — audit events retained indefinitely, structured logs 30 days, prod backups 7 days.
- Q: When six people are adding endpoints to one shared API contract in parallel, what stops someone's change from breaking an endpoint another spec's frontend code already depends on? → A: No version prefix; the contract is one evolving additive-only document, and a CI check diffs it against the trunk and fails the PR on any breaking change.
- Q: Should the web frontend have to meet any accessibility standard, and if so, is it enforced automatically or left to review? → A: A stated baseline — semantic markup, keyboard operability, visible focus — plus automated accessibility linting inside the frontend build check that fails the pull request on violations.

## User Scenarios & Testing *(mandatory)*

<!--
  Priority labels below use the CloudPulse AI constitution's tier semantics (Principle VIII):
  P1 = demo-critical, frozen scope; P2 = stretch, must never block or destabilise a P1 path.
  Stories are listed in dependency order within each tier, not in order of relative importance.
-->

### User Story 1 - Provision a working environment from scratch (Priority: P1)

The maintainer is handed nothing but access to an empty cloud account and
the repository. Following documented steps, they provision a complete, working dev environment —
data store, service runtime, identity, and web entry point — without hand-crafting anything in a
cloud console and without asking a teammate for a hidden value.

**Why this priority**: Every other story in this spec, and every feature in specs 2–6, needs a
place to run. It is also the single loudest piece of evidence that the platform is reproducible
rather than hand-assembled.

**Independent Test**: Take an empty cloud account, run the documented provisioning procedure from
a clean clone, and confirm a reachable, healthy environment exists at the end. Tear it all down
and repeat to confirm the result is the same both times.

**Acceptance Scenarios**:

1. **Given** an empty cloud account and a clean clone of the repository, **When** an engineer
   follows the documented provisioning procedure for the dev environment, **Then** a working
   environment exists and reports itself healthy, with no manual console changes required.
2. **Given** a provisioned dev environment, **When** the same procedure is run a second time with
   no changes to the definitions, **Then** no unexpected changes are applied and the environment
   remains healthy.
3. **Given** a provisioned dev environment, **When** it is torn down completely and provisioned
   again, **Then** the resulting environment is functionally identical to the first.
3a. **Given** the routine teardown procedure, **When** it is pointed at prod, **Then** it refuses
   and prod is left untouched.
4. **Given** the dev environment definitions, **When** the prod environment is provisioned from
   the same versioned definitions, **Then** prod comes up with only its documented per-environment
   differences and no separate, divergent definition set.
5. **Given** a change made directly in the cloud console, **When** the provisioning procedure is
   run again, **Then** the drift is reported and the environment is returned to its defined state.

---

### User Story 2 - Block a bad change before it reaches the trunk (Priority: P1)

The maintainer opens a pull request. Automated checks run without anyone asking, and the result is
visible on the pull request. If any check fails, the pull request cannot be merged — by anyone,
including its author.

**Why this priority**: The trunk must stay releasable at all times because six people merge into
it daily. Enforcement that can be talked past is not enforcement.

**Independent Test**: Open a pull request that deliberately breaks one check at a time (style,
typing, backend test, frontend build, environment-definition validation, API contract
compatibility, accessibility linting) and confirm each one independently turns the pull request red
and prevents merge.

**Acceptance Scenarios**:

1. **Given** a pull request targeting the trunk, **When** it is opened or updated, **Then** the
   full check suite runs automatically and its pass/fail result is visible on the pull request.
2. **Given** a pull request containing a deliberately failing backend test, **When** the checks
   finish, **Then** the pull request is marked failed and the merge control is unavailable.
3. **Given** a pull request that violates the agreed code style or fails static type checking,
   **When** the checks finish, **Then** the pull request is marked failed with the offending
   file and line identified.
4. **Given** a pull request that breaks the web frontend build or contains invalid environment
   definitions, **When** the checks finish, **Then** the pull request is marked failed.
4a. **Given** a pull request that removes or renames a field, removes an endpoint, makes an
   existing parameter required, or narrows a type in the API contract, **When** the checks finish,
   **Then** the pull request is marked failed and the specific breaking change is named.
4b. **Given** a pull request that only adds endpoints, adds optional fields, or widens types in the
   API contract, **When** the checks finish, **Then** the contract check passes.
4c. **Given** a pull request adding a frontend control with no accessible label, **When** the checks
   finish, **Then** the pull request is marked failed by the accessibility linting.
5. **Given** a pull request whose checks are red, **When** its own author attempts to merge it,
   **Then** the merge is refused.
6. **Given** backend code that talks to cloud provider services, **When** its unit tests run in
   the check suite, **Then** they pass without any real cloud credentials and without contacting
   a real cloud account.

---

### User Story 3 - Ship to dev automatically, to prod deliberately (Priority: P1)

When a pull request merges to the trunk, the change reaches the dev environment on its own,
including any data schema change it carries. Reaching prod requires a named human to approve
first.

**Why this priority**: Automatic dev delivery is what makes same-day merging safe and gives the
a continuously demonstrable environment. The prod gate is what stops a fast pipeline from
becoming a dangerous one.

**Independent Test**: Merge a visible, harmless change to the trunk and confirm it appears in dev
with no human action; then attempt a prod release and confirm it halts until approved.

**Acceptance Scenarios**:

1. **Given** a pull request merged to the trunk, **When** the delivery process runs, **Then** the
   change is deployed to dev with no manual intervention and the deployment outcome is recorded.
2. **Given** a merged change that includes a data schema migration, **When** dev is deployed,
   **Then** the migration is applied automatically before the new service version serves traffic.
3. **Given** a release targeting prod, **When** the delivery process reaches the prod stage,
   **Then** it pauses and waits for an explicit approval from an authorised approver.
4. **Given** a paused prod release, **When** an authorised approver approves it, **Then** the
   release proceeds and the approver's identity and time of approval are recorded.
5. **Given** a paused prod release, **When** no approval is given, **Then** prod is left entirely
   unchanged.
6. **Given** a deployment that fails partway, **When** the failure is detected, **Then** the
   environment is left in a known, serviceable state and the failure is surfaced to the maintainer.

---

### User Story 4 - Store governance data under a versioned schema (Priority: P1)

The platform holds the shared governance record — which accounts are onboarded, what was found in
them, who owns what, and what happened. That record has one defined shape, changes to it are
versioned and applied in order, and the shape is documented in the repository so every later spec
builds against the same picture.

**Why this priority**: Specs 2–6 all read and write this record. Without one agreed, migratable
schema, five parallel workstreams will invent five incompatible ones.

**Independent Test**: Apply every schema version in order to an empty store and confirm the
resulting shape matches the documented diagram; then apply the newest version to a populated
store and confirm no data is lost.

**Acceptance Scenarios**:

1. **Given** an empty data store, **When** all schema migrations are applied in order, **Then**
   the store contains the full governance shape: tenants, accounts, resources, rules, findings,
   owners, service-delivery areas, scans, and audit events.
2. **Given** a populated data store on an older schema version, **When** the newest migrations are
   applied, **Then** they succeed and no existing record is lost or corrupted.
3. **Given** the current schema, **When** the maintainer consults the repository, **Then** an
   entity-relationship diagram matching the current schema is present and current.
4. **Given** a schema change proposed in a pull request, **When** the diagram has not been updated
   to match, **Then** reviewers can detect the mismatch before merge.
5. **Given** an audit event that has been written, **When** any component attempts to modify or
   delete it, **Then** the attempt is refused and the original record remains intact.

---

### User Story 5 - Sign in and act only within your role (Priority: P1)

The maintainer signs in with their organisational identity. The platform reads their group
membership from that identity and recognises them as exactly one of admin, operator, or viewer —
it never asks them to register and never lets anyone assign a role from inside the platform. Every
action they attempt is permitted or refused according to that role. Someone who is not signed in,
or who belongs to no mapped group, sees nothing at all.

**Why this priority**: This is the platform's entire access-control surface. Every screen and
endpoint in specs 2–6 depends on the caller's identity and role being trustworthy.

**Independent Test**: Exercise a matrix of the three roles against representative admin-only,
operator-only, and read-only actions, plus an unauthenticated caller and a signed-in person in no
mapped group, and confirm every cell gives the expected allow or refuse.

**Acceptance Scenarios**:

1. **Given** an unauthenticated visitor, **When** they request any application screen or any
   non-public endpoint, **Then** access is refused and no governance data of any kind is returned.
2. **Given** a valid organisational identity belonging to exactly one mapped group, **When** the
   person signs in, **Then** they reach the application carrying exactly the role that group maps
   to, without ever registering or being assigned a role inside the platform.
3. **Given** a valid organisational identity belonging to no mapped group or to more than one,
   **When** the person signs in, **Then** access is refused and no governance data is returned.
4. **Given** a signed-in viewer, **When** they attempt to change any configuration or start any
   scan, **Then** the action is refused with a clear message and nothing is changed.
5. **Given** a signed-in operator, **When** they attempt to manage accounts, rules, or
   service-delivery areas, **Then** the action is refused; **When** they run a scan or work a
   finding, **Then** the action is permitted.
6. **Given** a signed-in admin, **When** they perform any administrative action, **Then** it is
   permitted and an audit record identifying them is written.
7. **Given** a signed-in operator whose directory group changes to viewer, **When** their session
   is next renewed, **Then** they carry the viewer role and operator actions are refused.
8. **Given** an expired or tampered session, **When** it is used against any endpoint, **Then**
   the request is refused and the person is asked to sign in again.
9. **Given** a signed-in person, **When** they sign out, **Then** their session can no longer be
   used for any subsequent request.
10. **Given** any signed-in person, **When** they look for a way to change their own or another
    person's role, **Then** the platform offers none — no screen and no endpoint exists.

---

### User Story 6 - Reach a healthy, consistently-behaved service (Priority: P1)

The web frontend talks to a single service that reports its own health, describes every failure
in the same shape, and records what it did in a form the maintainer can search when something goes
wrong.

**Why this priority**: Specs 2–6 add endpoints and screens to this service. Fixing the health,
error, and logging contract once, up front, is what stops six people from inventing six different
error formats.

**Independent Test**: Call the health endpoint, force several different kinds of failure, and
confirm every failure comes back in the identical envelope and appears in the logs under a
traceable identifier.

**Acceptance Scenarios**:

1. **Given** a deployed environment, **When** the service health endpoint is called, **Then** it
   reports overall health together with the health of its data store dependency.
2. **Given** the service is unable to reach its data store, **When** health is checked, **Then**
   it reports unhealthy rather than reporting healthy or failing to answer.
3. **Given** any failing request — invalid input, refused permission, missing record, or internal
   error — **When** the response is returned, **Then** it uses one uniform error envelope carrying
   a machine-readable code, a human-readable message, and a correlation identifier.
4. **Given** any request, **When** it is handled, **Then** a structured log entry is recorded
   carrying the same correlation identifier, so one request can be followed end to end.
5. **Given** any log entry, **When** it is inspected, **Then** it contains no credentials, no
   secrets, and no raw customer tag values.
6. **Given** the deployed web frontend, **When** it calls the service, **Then** the call succeeds
   from the browser without the user configuring anything by hand.

---

### User Story 7 - Find out something is wrong without being told (Priority: P2)

The project has one place that shows whether the platform is healthy, and it raises an email alert
when errors spike, a scan fails, or work piles up unprocessed.

**Why this priority**: Stretch tier. Valuable for operating the platform and for demonstrating
operational maturity, but the demo path can be walked and every P1 story verified without it.
Per the constitution it must never block or destabilise any P1 path.

**Independent Test**: Deliberately force each alarm condition in turn and confirm the dashboard
reflects it and an alert email is delivered.

**Acceptance Scenarios**:

1. **Given** a deployed environment, **When** the maintainer opens the service dashboard, **Then**
   they see current service error rates, scan outcomes, and unprocessed-work depth in one place.
2. **Given** service errors exceed the agreed threshold, **When** the condition persists past the
   agreed window, **Then** an alert is raised and an email reaches the alert address.
3. **Given** a scan fails, **When** the failure is recorded, **Then** an alert is raised and an
   email reaches the alert address.
4. **Given** work items land in the dead-letter holding area, **When** the count exceeds zero,
   **Then** an alert is raised and an email reaches the alert address.
5. **Given** an alarm condition clears, **When** the metric returns to normal, **Then** the alarm
   returns to a healthy state without anyone resetting it by hand.

---

### Edge Cases

- **Provisioning into a non-empty account**: what happens when a name the definitions want is
  already taken by a pre-existing resource? Provisioning must fail clearly rather than adopt or
  overwrite the existing resource.
- **Teardown aimed at prod**: an engineer runs the routine destroy procedure against prod, whether
  by mistake or by copying a dev command. It must refuse before touching anything, not partially
  destroy and then stop at the protected data store.
- **Necessary breaking change to the contract**: a field genuinely has to become required, or an
  endpoint has to go. The additive-then-remove path must be workable within a two-week build rather
  than leaving no route forward but bypassing the check.
- **Two pull requests add the same contract path**: both pass the check independently against the
  trunk, but conflict once both are merged. The second to merge must fail rather than silently
  overwrite the first.
- **Concurrent deployments**: two pull requests merge to the trunk within seconds of each other —
  deployments must not interleave and leave dev running a mixture of two versions.
- **Failed migration mid-flight**: a schema migration fails partway through a dev deploy. The
  store must not be left in an unknown shape, and the previous service version must keep serving.
- **Irreversible migration**: a migration that cannot be automatically reversed is proposed. It
  must be identified as such before merge rather than discovered during a prod release.
- **Approval never arrives**: a prod release waits indefinitely. It must expire in a defined,
  visible way rather than sit forever or silently self-approve.
- **Approver is the author**: the only available approver for a prod release is the person who
  wrote the change.
- **Identity provider unavailable**: nobody can sign in. The platform must say so plainly rather
  than appear empty or broken, and must not fall back to unauthenticated access.
- **Person removed from the organisation**: their access must stop working, and any session they
  still hold must stop being accepted.
- **Person's role changes while signed in**: their group membership changes in the directory. The
  new role must take effect at the next session renewal rather than persisting for the life of the
  session.
- **Person belongs to no mapped group, or to two of them**: neither may resolve to a working
  session. No group means no access; two groups is an ambiguous identity and must be refused rather
  than resolved by picking one.
- **First administrator**: a freshly provisioned environment has no admin until someone is added to
  the admin group in the directory. The platform must present this state honestly — signed-in but
  unauthorised — and must not offer any in-platform way to grant the first role.
- **Directory group claims missing from a sign-in**: the identity is valid but carries no group
  information at all. This must be refused as unauthorised, never treated as an empty group list
  that quietly matches a default.
- **Correlation identifier absent**: a caller supplies no correlation identifier, or supplies a
  malformed one. The service must generate a trustworthy one rather than log a caller-controlled
  value unchecked.
- **Alerting is itself down**: the alerting path fails. Its own failure must be visible rather
  than presenting as silence, which is indistinguishable from health.

## Requirements *(mandatory)*

### Functional Requirements

#### Reproducible environments (S1) [P1]

- **FR-001**: The entire platform MUST be provisionable into a fresh, empty cloud account using
  only versioned definitions held in the repository. Exactly one manual step is permitted — the
  bootstrap of FR-001a — and no other manual console configuration may be required at any point.
- **FR-001a**: A single documented bootstrap step MAY be performed by a human with account-level
  credentials, limited to creating the Terraform state backend and the CI federation trust. It
  MUST be expressed as versioned definitions in the repository, MUST be applied once per account,
  MUST NOT create any long-lived credential, and MUST be counted in the FR-006 runbook and the
  SC-001 budget.
- **FR-002**: The system MUST support exactly two named environments, dev and prod, provisioned
  from a single shared set of definitions with per-environment values supplied as configuration.
- **FR-003**: Provisioning MUST be repeatable: applying unchanged definitions to an
  already-provisioned environment MUST report no changes at all. A non-empty plan is a defect in
  the definitions, not an acceptable diff to review away.
- **FR-004**: Provisioning MUST detect and report drift between the defined state and the actual
  state of an environment.
- **FR-005**: The dev environment MUST be fully destroyable and re-creatable from the repository as
  a routine, documented operation.
- **FR-005a**: The prod data store MUST carry deletion protection. Destroying prod MUST require a
  deliberate step outside the normal provisioning procedure, and the routine teardown path MUST
  refuse to act on prod **before invoking anything** — a partial teardown that stops at the
  protected resource does not satisfy this.
  *Implementation note (corrected 2026-08-22):* this is enforced by two layers, not three.
  Terraform's `prevent_destroy` cannot be made conditional on environment, and FR-002 requires one
  shared module set for dev and prod, so it is unavailable here. See research.md R-010.
- **FR-005b**: The prod data store MUST be backed up automatically at least daily, and backups MUST
  be retained for 7 days before expiring automatically. Rehearsing a restore is out of scope for
  this spec.
- **FR-006**: The repository MUST document the provisioning procedure, including every prerequisite
  and every value an operator must supply, sufficient for a first-time engineer to follow it
  unaided.
- **FR-007**: Environment definitions MUST NOT contain credentials, secrets, or long-lived access
  keys of any kind.

#### Continuous integration (S2) [P1]

- **FR-008**: Every pull request targeting the trunk MUST automatically trigger the full check
  suite without any human action.
- **FR-009**: The check suite MUST include code style checking, static type checking, backend unit
  tests, the frontend build, validation of the environment definitions, the API contract
  compatibility check of FR-048b, and the accessibility linting of FR-047b.
- **FR-010**: Backend unit tests covering cloud-provider interactions MUST run against simulated
  cloud responses and MUST NOT require or accept real cloud credentials.
- **FR-011**: A failing check MUST block merge for all users, with no bypass and no administrative
  override.
- **FR-012**: Check results MUST be visible on the pull request. A failure MUST name the check
  that failed and, where the failure is attributable to a location in the repository, the file
  path and line number — so no local re-run is needed to know where to look.
- **FR-013**: The check suite MUST also detect committed credentials or secrets and fail the pull
  request when any are found.
- **FR-013a**: The check suite MUST verify that no dependency manifest introduces a non-AWS
  inference, model-hosting, or agent-framework SDK, and MUST fail the pull request when one
  appears. This is the automated enforcement of constitution Principle II; a README statement is
  not sufficient.
- **FR-014**: The check suite MUST report a result within 10 minutes of a pull request being
  opened or updated, which is what makes same-day merging achievable.

#### Continuous delivery (S3) [P1]

- **FR-015**: A merge to the trunk MUST automatically deploy the merged change to dev with no
  manual intervention.
- **FR-016**: Deployment MUST apply any pending data schema migrations before the new service
  version begins serving traffic.
- **FR-017**: Deployment to prod MUST NOT proceed without an explicit approval recorded by an
  authorised approver.
- **FR-018**: The identity of the approver and the time of approval MUST be recorded as an
  immutable audit record.
- **FR-019**: A prod release awaiting approval MUST leave prod completely unchanged until approved.
- **FR-020**: Deployments MUST be serialised per environment so two deployments cannot apply
  concurrently to the same environment.
- **FR-021**: A failed deployment MUST leave the environment in a known, serviceable state and MUST
  surface the failure to the maintainer. "Known, serviceable" means all three of: the previously
  deployed service version is still serving traffic; the data store is at a schema revision that
  version supports; and the recorded deployment status is `failed` rather than left `running`.
- **FR-022**: The delivery process MUST authenticate to the cloud provider using short-lived
  federated credentials only, never stored access keys.
- **FR-023**: Every deployment MUST record what version was deployed, to which environment, when,
  and triggered by whom.

#### Governance data store (S4) [P1]

- **FR-024**: The platform MUST provide a relational store holding tenants, accounts, resources,
  rules, findings, owners, service-delivery areas, scans, and audit events.
- **FR-025**: All schema changes MUST be expressed as ordered, versioned migrations applied
  automatically as part of deployment.
- **FR-026**: Migrations MUST apply successfully to both an empty store and a populated store
  without data loss.
- **FR-027**: Each migration MUST declare whether it is reversible, and irreversible migrations
  MUST be identifiable before merge.
- **FR-028**: An entity-relationship diagram matching the current schema MUST be maintained in the
  repository and updated in the same pull request as any schema change.
- **FR-029**: Audit events MUST be append-only: once written, a record can never be modified or
  deleted by any component or user.
- **FR-029a**: Audit events MUST be retained indefinitely — no expiry, no purge job, and no
  retention setting that could remove them. Any future change to this MUST be a constitution-level
  decision, not a configuration change.
- **FR-030**: Every entity that belongs to a tenant MUST carry its tenant association so that data
  can never be read across tenant boundaries.

#### Identity and access (S5) [P1]

- **FR-031**: People MUST sign in using their organisational identity only. The platform MUST NOT
  hold passwords, MUST NOT expose any self-service registration path, and MUST NOT create accounts
  on request.
- **FR-031a**: The organisational identity provider MUST be the sole authority for a person's role.
  The platform MUST derive the role from the person's group membership and MUST NOT provide any
  means to assign, edit, or override a role within the platform.
- **FR-032**: Every person MUST resolve to exactly one role — admin, operator, or viewer — derived
  from exactly one mapped group. The mapping from group to role MUST be configuration, not code.
- **FR-032a**: A person whose identity maps to no group MUST receive no access at all; there is no
  default role. A person mapping to more than one group MUST be refused access rather than silently
  granted the higher or lower of the two.
- **FR-033**: Admin MUST be able to manage accounts, rules, and service-delivery areas; operator
  MUST be able to run scans and work findings; viewer MUST be able to read dashboards only. These
  capabilities are implemented by specs 2–5; this spec defines the roles they are checked against
  and MUST NOT implement the capabilities themselves.
- **FR-033a**: For the endpoints this spec ships, the role matrix MUST be: `/health` reachable
  without authentication; `/me` reachable by any caller with exactly one resolved role and by no
  one else. Every endpoint added by a later spec MUST declare its required role explicitly — there
  is no default-permit.
- **FR-034**: Every request to every non-public endpoint MUST be rejected unless it carries a valid
  identity, and MUST be rejected when the caller's role does not permit the action.
- **FR-035**: Unauthenticated callers MUST receive no governance data of any kind, and error
  responses MUST NOT reveal whether a given record exists.
- **FR-036**: Sessions MUST expire after a bounded period, and an expired or tampered session MUST
  be refused.
- **FR-037**: Signing out MUST render the session unusable for all subsequent requests.
- **FR-038**: A person's role MUST be re-derived from their current group membership each time
  their session is renewed, so that a group change made in the directory takes effect within one
  documented, bounded interval without any action inside the platform.
- **FR-038a**: Removal of a person from the organisation, or from all mapped groups, MUST end their
  access within the same bounded interval, and any session they still hold MUST stop being accepted
  at or before that point.
- **FR-039**: Establishing the first administrator MUST be an act performed in the identity
  provider — adding a person to the admin group — and MUST be documented as a step of the
  provisioning procedure (FR-006). The platform MUST NOT contain a bootstrap path, seeded account,
  or break-glass credential of any kind.
- **FR-039a**: The three group-to-role mappings MUST be part of the versioned environment
  definitions, so a freshly provisioned environment is governed identically to an existing one.
- **FR-040**: Every administrative and state-changing action MUST write an audit record naming the
  acting person, the action, the target, and the time.

#### API skeleton (S6) [P1]

- **FR-041**: The service MUST expose a health endpoint reporting its own health and the health of
  its data store dependency.
- **FR-042**: The health endpoint MUST report unhealthy when a dependency is unreachable, rather
  than reporting healthy or failing to respond.
- **FR-043**: Every error response from every endpoint MUST use one uniform envelope containing a
  machine-readable code, a human-readable message, and a correlation identifier.
- **FR-044**: Every request MUST be assigned a correlation identifier that appears in both the
  response and every log entry produced while handling it.
- **FR-045**: The service MUST emit structured, machine-parsable logs for every request, including
  outcome and duration.
- **FR-046**: Logs MUST NOT contain credentials, secrets, session tokens, or raw customer tag
  values.
- **FR-046a**: Structured logs MUST expire automatically 30 days after they are written. Log
  retention MUST be declared in the versioned environment definitions rather than configured by
  hand.
- **FR-047**: The deployed web frontend MUST be able to call the service successfully from a
  browser without any manual configuration by the user.
- **FR-047a**: The web frontend MUST meet an accessibility baseline: semantic markup with correct
  roles and labels, every interactive control reachable and operable by keyboard alone, and a
  visible focus indicator on the focused control. This baseline binds every screen added by
  specs 2–6.
- **FR-047b**: Automated accessibility linting MUST run inside the frontend build check, and
  violations MUST fail the pull request. Automated rules catch only a subset of accessibility
  problems, so passing them MUST NOT be treated as evidence that FR-047a is fully met — keyboard
  operability and focus visibility remain a reviewer's responsibility.
- **FR-048**: The service MUST publish a machine-readable description of its interface that the
  frontend consumes as the binding contract, per constitution Principle V.
- **FR-048a**: The contract MUST be a single unversioned document with no version prefix in
  endpoint paths. Changes to it MUST be additive: adding endpoints, adding optional fields, and
  widening types are permitted.
- **FR-048b**: The check suite MUST compare the contract in a pull request against the version on
  the trunk and MUST fail the pull request on any breaking change — a removed or renamed field, a
  removed endpoint, a newly-required parameter, or a narrowed type.
- **FR-048c**: When a breaking change is genuinely necessary, it MUST be made as an additive
  replacement plus removal of the old shape in a later pull request, once no consumer references
  it — never as a single breaking edit.

#### Architectural boundaries for downstream specs (S1) [P1]

These requirements exist so that five later specs build against one settled set of seams. This
spec MUST create and constrain each boundary; it MUST NOT implement what lies behind it.

- **FR-054**: The repository MUST reserve a connector package for the provider-agnostic connector
  interface and normalized resource model defined by spec 2 (backlog S11). This spec MUST NOT
  define that interface. The boundary constraint it MUST enforce is that no cloud-provider SDK
  type may cross out of the connector package into core code, and CI MUST fail a pull request that
  violates it.
- **FR-055**: The finding lifecycle states and the service-delivery-area grouping and roll-up
  semantics are spec 3's to define. This spec MUST provide schema that accommodates them and MUST
  record the delegation explicitly, so that specs 3 and 4 cannot each assume a different meaning.
- **FR-056**: Agent action groups introduced by spec 6 MUST reach platform data only through the
  platform API, authenticated as a read-only, tenant-scoped principal. This spec MUST provide that
  access path and MUST NOT permit any agent to hold cloud credentials, reach the data store
  directly, or invoke a state-changing operation — enforcing constitution Principle IV at the
  foundation rather than trusting each later spec to re-derive it.
- **FR-057**: When a breaking change to the API contract is genuinely necessary, the
  additive-then-remove path of FR-048c MUST be documented as a procedure in the repository, so the
  route forward is known before someone is tempted to bypass the FR-048b gate.

#### Observability (S7) [P2]

- **FR-049**: The platform MUST provide a single dashboard showing service error rates, scan
  outcomes, and unprocessed-work depth for an environment.
- **FR-050**: Alarms MUST be raised when service errors exceed an agreed threshold, when a scan
  fails, and when items accumulate in the dead-letter holding area.
- **FR-051**: A raised alarm MUST send an email alert to the configured alert address.
- **FR-052**: An alarm MUST return to a healthy state automatically when its condition clears.
- **FR-053**: Failure of the alerting path itself MUST be detectable rather than presenting as
  silence.

### Key Entities *(include if feature involves data)*

This spec defines the *shape and lifecycle* of these entities. The behaviour that fills them is
owned by specs 2–6.

- **Tenant**: the organisational boundary that owns all other records. Every tenant-scoped entity
  carries its tenant association; data is never readable across tenants.
- **User**: a projection of a person's organisational identity, associated with a tenant. Holds no
  password and no locally authoritative role — the role is derived from directory group membership
  on each session renewal. A local record exists only to attribute audit events and to display a
  human-readable name.
- **Account**: a registered cloud account belonging to a tenant, with the connection details needed
  to scan it — never credentials. Populated by spec 2.
- **Resource**: a normalised, provider-agnostic record of something discovered in an account, with
  its identity, type, location, tags, and parent relationship. Populated by spec 2.
- **Rule**: a governance rule expressed as data rather than code, versioned so a finding can be
  traced to the rule version that produced it. Populated by spec 3.
- **Finding**: an instance of a resource failing a rule, with severity, status, and lifecycle over
  time. Populated by spec 3.
- **Owner**: the human attributed as accountable for a resource, with the evidence and confidence
  behind the attribution. Populated by spec 3.
- **Service Delivery Area (SDA)**: a named delivery unit with a responsible owner, used to group
  resources and roll up compliance. Populated by spec 3.
- **Scan**: one execution of discovery against an account, with trigger, timing, counts, and
  outcome. Populated by spec 2.
- **Audit Event**: an append-only record of a privileged or state-changing action — actor, action,
  target, time. Written by every spec; never modified or deleted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person with no prior knowledge of the platform takes an empty cloud account to a
  working dev environment in under 60 minutes using only the repository and its documentation.
- **SC-002**: Provisioning the same definitions twice produces zero unintended changes on the
  second run, and a full teardown of dev followed by re-provisioning yields a functionally
  identical environment. The same teardown attempted against prod is refused, 100% of attempts.
- **SC-003**: A pull request containing a deliberately failing check cannot be merged — 100% of
  attempts refused, including by the author, across all seven check categories tested
  independently.
- **SC-004**: The full check suite reports a result on a pull request within 10 minutes, fast
  enough that a change opened in the morning can merge the same day.
- **SC-005**: A merge to the trunk is live in dev, migrations included, within 15 minutes with zero
  human actions in between.
- **SC-006**: 100% of prod releases record a named approver before any prod change occurs; a
  release with no approval leaves prod byte-for-byte unchanged.
- **SC-007**: Applying every migration in order to an empty store yields a shape matching the
  committed diagram exactly, and applying the newest migrations to a populated store loses zero
  records.
- **SC-008**: Across a full role matrix — admin, operator, viewer, unauthenticated, no-mapped-group,
  and multiple-mapped-groups — against representative administrative, operational, and read-only
  actions, 100% of cells produce the expected allow or refuse, with zero governance data returned to
  any caller lacking a resolved role.
- **SC-013**: A person's group membership changed in the directory takes effect in the platform
  within 1 hour with zero actions performed inside the platform, and the platform exposes no
  endpoint or screen through which any role can be assigned.
- **SC-014**: Retention behaves as declared: no audit event is ever removed by any automated
  process, structured logs older than 30 days are absent, and prod backups older than 7 days are
  absent — each verifiable by inspecting the environment without reading implementation code.
- **SC-016**: A pull request adding a non-AWS inference, model-hosting, or agent-framework SDK to
  any dependency manifest is refused by CI, 100% of attempts — and a pull request leaking a
  cloud-provider SDK type out of the connector package is refused on the same terms.
- **SC-017**: The read-only, tenant-scoped access path that agent action groups will use exists and
  is demonstrably incapable of state-changing operations: every attempt to mutate through it is
  refused, and the path holds no cloud credential.
- **SC-015**: Every screen the platform ships can be operated end to end using the keyboard alone,
  with the focused control visible at every step, and the automated accessibility check reports
  zero violations on the trunk.
- **SC-009**: 100% of error responses across all endpoints and all failure kinds conform to the
  single error envelope.
- **SC-010**: Any single request can be traced from response to complete log record using only its
  correlation identifier, in under 2 minutes.
- **SC-011**: A deliberately forced failure — service errors, a failed scan, or a dead-lettered
  item — produces an email alert within 5 minutes of the condition being met.
- **SC-012**: A repository-wide scan finds zero credentials, secrets, or long-lived access keys in
  source or environment definitions, and zero delivery workflows authenticating with stored keys.

## Assumptions

- **Federated sign-in only; roles come from directory groups** (clarified 2026-08-22). Three groups
  in the organisational identity provider map one-to-one to admin, operator, and viewer. There is no
  registration UI, no user-management screen, and no platform-side role store — role management is
  entirely a directory concern, which keeps the platform free of a second, drifting source of truth
  and removes a whole class of privilege-escalation surface.
- **Single tenant at runtime, tenant-aware schema.** The platform is described as internal and
  operated by one small team, so exactly one tenant is seeded in the MVP. Every entity is
  nonetheless tenant-scoped from day one (FR-030) so multi-tenancy needs no schema rewrite later.
- **The trunk is `pods/pod73`.** Per constitution Principle VII this is the only long-lived branch
  and the target of every pull request; all working branches follow `pods/pod73-XXX`.
- **Two environments only.** Dev and prod. No staging, QA, or per-developer environment is in scope.
- **The maintainer is the sole authorised prod approver** (constitution v2.0.0, Principle VII).
  With a single maintainer, every prod approval is by definition a self-approval; it is permitted
  and MUST be explicitly recorded as such in the audit trail, so the merge history stays honest
  about what kind of gate it was.
- **Automated AI review replaces the second-human review.** Every pull request carries at least one
  recorded AI review before merge; there is no second human. This is the constitution v2.0.0
  position and is what SC-003's "including by the author" clause is testing.
- **Alerts go to a single configured email address**, not to individual per-person subscriptions
  and not to resource owners — owner notification is explicitly cut from the MVP.
- **Session lifetime and role-change propagation are bounded at 1 hour.** Because roles are
  re-derived on session renewal (FR-038), this interval is also the worst-case delay before a
  directory group change takes effect. A standard, defensible default satisfying FR-036 and FR-038.
- **Simulated cloud responses in tests are maintained alongside the connector contract** defined by
  spec 2; this spec establishes the requirement, spec 2 supplies the normalised model.
- **Load is demo-scale.** Roughly ten concurrent users and a handful of onboarded accounts; no
  capacity or scale target beyond "does not degrade during the demo" is in scope.
- **Cost guardrails are not in scope for this spec.** Keeping environment spend low is an
  operational concern, not a foundation requirement.

## Dependencies

- An organisational identity provider is available, the maintainer can be represented in it, and
  it emits group membership as part of the signed-in identity.
- The maintainer holds the directory rights to create the three role groups and manage their
  membership — a prerequisite for FR-039 and for any role change during the build.
- A cloud account is available for dev, and a separate one for prod.
- The source repository supports required status checks on the trunk, and the maintainer holds the
  administrative rights to configure that protection (a prerequisite for SC-003).
- An alert email address exists to receive notifications (S7).

## Out of Scope

- Any product feature behaviour: account onboarding and discovery, tag compliance and ownership,
  the governance dashboard, cost and utilisation, and AI insights — owned by specs 2–6.
- Email notification to resource owners — cut from the MVP.
- Staging or per-developer environments.
- Multi-tenant onboarding flows, tenant self-service, and billing.
- Disaster recovery, cross-region failover, and rehearsed backup restore drills. Automated prod
  backups are in scope (FR-005b); exercising a restore from them is not.
