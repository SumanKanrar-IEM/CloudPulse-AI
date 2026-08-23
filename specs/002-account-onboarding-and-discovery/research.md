# Research: Account Onboarding and Discovery

Ten decisions, following spec 1's format: Decision / Rationale / Alternatives considered. Two carry
**VERIFY** markers — genuine unknowns to confirm during implementation, not guessed defaults.
R-207/R-208 exist because the plan input explicitly requires a cost profile and a live-verification
discipline statement, mirroring spec 1's R-003 and playbook §0.5.3.

## R-201 — Whole-account discovery: no single AWS API covers "every resource type, untagged included"

**Decision**: Two discovery surfaces, combined, behind one connector interface. **Resource Groups
Tagging API** (`GetResources`) is the primary sweep — it returns resources across most AWS services
in one paginated call per region, *including untagged ones* (its per-type coverage is broad, not
tag-gated), which is why FR-016/017 can be satisfied without a per-service describe call for the
common case. **AWS Cloud Control API** (`ListResources`, iterated over the CloudFormation
resource-type registry) fills the gap for resource types Tagging API's index doesn't cover. Both
feed into one connector implementation (`backend/connectors/aws.py`) behind the protocol
`backend/connectors/base.py` defines, so a consumer (the diffing/persistence layer, FR-014) never
knows which surface found a given resource.

**Rationale**: Neither surface alone satisfies FR-016 ("service-agnostic discovery surfaces, not a
hand-picked list") plus FR-017 ("regardless of whether they carry tags"). Resource Groups Tagging
API is fast and cheap (one call sweeps dozens of services) but its supported-resource-type list is
not exhaustive. Cloud Control API's coverage is growing but has real gaps for older/niche resource
types as of this writing — **VERIFY** the exact current gap list against the six FR-019 P1 types
(EC2, EBS, EIP, S3, RDS, Lambda) before implementation; if Cloud Control genuinely lacks coverage
for one of those six, R-206's enrichment describe call for that type doubles as its discovery path
too, so P1 completeness (SC-002's >95%) does not depend on Cloud Control's coverage for exactly
those six.

**Alternatives considered**: Cloud Control API alone — simpler (one surface), but its coverage gaps
would directly fail FR-016/SC-002 for types it doesn't support, and there is no fallback without
building one anyway. Resource Groups Tagging API alone — same problem in the other direction, plus
a documented (if narrow) risk that some resource types are tag-index-eligible but not
tag-index-complete in every region. A hand-maintained per-service list of `list_*`/`describe_*`
boto3 calls — this is precisely what FR-016 forbids ("not a fixed, hand-maintained list of
services the platform's authors anticipated in advance"); rejected on the requirement's own terms,
not on convenience grounds.

## R-202 — Deep enrichment (FR-019): targeted describes, not extending the generic sweep

**Decision**: The six P1 governance-critical types (EC2, EBS, EIP, S3, RDS, Lambda) each get one
targeted boto3 describe call (`describe_instances`, `describe_volumes`, `describe_addresses`,
`get_bucket_*` calls, `describe_db_instances`, `get_function`) run *after* the generic sweep
identifies the resource exists, merging enrichment detail into the same normalized record rather
than replacing it.

**Rationale**: The generic surfaces (R-201) return identity fields (ARN, type, region, tags) but
not the state/size/attachment/runtime detail FR-019 requires, because that detail is inherently
service-specific — there is no generic API for "give me the instance type of this EC2 instance."
Coverage-as-data (FR-021) is exactly the seam that makes this extensible: the mapping from resource
type to enrichment function is a data-driven registry (`backend/app/scan/coverage.py`), not an
if/elif chain, so adding a P2 type (FR-020: EKS, DynamoDB, ELB, IAM) later is a data change plus
one new function, not a rewrite of the sweep.

**Alternatives considered**: Skip the generic sweep for these six types and rely on the describe
calls alone for both discovery and enrichment — rejected because it reintroduces the
hand-maintained-list problem R-201 exists to avoid; the generic sweep must still be the source of
truth for *which* resources exist, with describes layered on for detail only.

## R-203 — Coverage-as-data storage: versioned repository data, not a live admin-editable table

**Decision**: Coverage Definitions (which resource types get deep enrichment, and how) live as a
versioned JSON/YAML file in the repository (`backend/app/scan/coverage_definitions.json` or
equivalent), deployed through the normal CI/CD pipeline — not a database table with an admin UI to
edit it.

**Rationale**: The spec's own language is precise about this: "ships without code changes," not
"is admin-editable" (contrast with spec 3's S18 tagging rules, whose backlog description
explicitly says "admin-editable store" — coverage-as-data's description deliberately doesn't).
FR-021/FR-022 only require that adding coverage doesn't need a *code* change and that a scan
mid-flight isn't affected by a change — both are satisfied by "edit the file, open a PR, it's live
on the next deploy," which is also more auditable (every coverage change has a PR, an AI review,
and a git history) than a live-editable table would be, and needs no new admin-surface FR this
spec's spec.md doesn't already have. Spec 6's future coverage advisor (Out of Scope) proposes
changes to this same file as a PR, not through a runtime API — consistent with this decision.

**Alternatives considered**: A database table with an admin UI — rejected as unnecessary scope: it
would need its own FR (none exists), its own role-authorization question (another clarify round),
and duplicates what git already provides for free. Hardcoded Python dict — rejected, that *is* "a
code change" to extend, which FR-021 explicitly forbids.

## R-204 — Scan status machine: `partial` is a first-class outcome, not an error

**Decision**: `scan.status` is `running → succeeded | partial | failed`, not the binary
`succeeded/failed` spec 1's `deployment.status` enum uses. Deleted-marker diffing (FR-030) runs
against `succeeded` and `partial` scans alike, scoped only to the units of work that actually
completed; it never runs against a `failed` scan.

**Rationale**: FR-031 and FR-032 both describe this exact three-way split as a hard requirement,
not an implementation detail — a scan that fails outright must not diff at all (FR-031), while a
scan that partially completes must diff only its successful portion (FR-032). A two-state enum
cannot represent "some units succeeded, some didn't, and that's a legitimate terminal state" —
collapsing `partial` into `succeeded` would incorrectly mark resources deleted in the regions/
services that failed; collapsing it into `failed` would incorrectly skip diffing the regions that
did succeed.

**Alternatives considered**: Track partial success only at the unit-of-work level, leaving
`scan.status` binary and deriving "was this partial" by querying the unit-of-work records —
rejected: FR-033 (scan history, P2) needs the scan's own outcome to be directly queryable without
a join, and SC-006's test ("verified by forcing a partial failure and confirming the unaffected
resources' deleted markers are unchanged") is much harder to assert cleanly against a derived value
than a stored one.

## R-205 — Role authorization: reuse `require_role`, no new mechanism

**Decision**: Every new route in `backend/app/api/routers/accounts.py` declares its role
requirement via spec 1's existing `require_role(*roles)` dependency — `require_role(Role.ADMIN)`
for register/deactivate/reactivate, `require_role(Role.ADMIN, Role.OPERATOR, Role.VIEWER)` for
viewing, `require_role(Role.OPERATOR)` for triggering an on-demand scan (spec 2 Clarifications
session 2026-08-23, FR-010a/FR-011a/FR-026a).

**Rationale**: Spec 1 built this specifically so specs 2–6 would not need to reinvent
authorization — `require_role` already re-derives the caller's role from Cognito claims
independently on every request (R-004's two-layer design) and raises the uniform 403 envelope on
mismatch. There is nothing left to design here; the only spec-2-specific work is choosing the
right role set per route, which the Clarifications session already settled.

**Alternatives considered**: None seriously — building a second authorization mechanism would
violate the plan's own "consume `require_role`, don't stand up a second Cognito pool or API
Gateway" instruction and playbook §0.5.4's explicit guidance.

## R-206 — Cross-account role assumption: `boto3.client('sts').assume_role`, cached per scan

**Decision**: A scan worker Lambda assumes the target account's scanner role once at the start of
its unit of work (one account × region × service group), using the ExternalId stored as a Secrets
Manager reference, and reuses the resulting temporary credentials for every discovery/enrichment
call within that unit — not re-assuming per API call.

**Rationale**: `AssumeRole` has its own (generous but real) rate considerations, and temporary
credentials are valid for the assumed session duration (default 1 hour, comfortably longer than one
unit of work's expected runtime at demo scale) — assuming once per unit of work is the standard
pattern and avoids any risk of hitting STS throttling during a large sweep.

**Alternatives considered**: Assume once per whole scan (all regions/service groups sharing one set
of credentials) — rejected: FR-023 requires units of work to be independent, and sharing one
credential set across parallel Step Functions Map iterations couples them in a way that
complicates the Map fan-out's natural per-branch isolation for no benefit.

## R-207 — Cost profile for this spec's new AWS resources (playbook §0.5.3)

This account has no free tier; every new billable resource gets the same pricing-floor-level
reasoning as spec 1's R-003, not an assertion of "cheap."

| Resource | Dev/prod choice | Reasoning |
|---|---|---|
| Step Functions (Standard) | Standard workflow, not Express | Standard is priced per state transition (~$0.025 per 1,000), not per GB-second-of-duration like Express — at demo scale (a handful of accounts, tens of scans/day) this is pennies either way, but Standard's per-state execution history (needed for FR-023's independent-unit-of-work record and FR-033's P2 scan-history detail) is the deciding factor, not price. Express would be marginally cheaper only at a volume this platform is nowhere near. |
| EventBridge Scheduler (daily scan trigger) | One rule, dev and prod both | Scheduler rules are billed per invocation at a rate that rounds to zero at one trigger/day; no cost-profile decision needed beyond "don't add more schedules than FR-026 requires." |
| Scan-worker Lambda invocations | arm64, sized like spec 1's API Lambda (1024MB) | Same reasoning as spec 1: arm64 is ~20% cheaper than x86 per GB-second for equivalent performance, and Lambda's free-tier-adjacent per-request pricing at demo-scale invocation counts (a handful of accounts × a handful of regions × a handful of service groups × once/day plus occasional on-demand) is negligible regardless of architecture choice. |
| No RDS Proxy, no new Aurora capacity | Reuses spec 1's existing dev/prod clusters at their existing `min_acu=0.5` | This spec adds columns and rows to existing tables; it provisions no new database capacity. Spec 1's R-003 reasoning (RDS Proxy's 8-ACU pricing floor costs roughly double the cluster it pools for) still applies unchanged — still not adopting a proxy at this scale. |
| S3 (raw scan snapshots) | Reuses spec 1's already-provisioned, currently-empty snapshot bucket | No new bucket. Storage cost is proportional to snapshot size × retention, both demo-scale; no lifecycle policy decision needed beyond what spec 1 already deferred to this spec (spec 1's Assumptions: "leaving its lifecycle policy to spec 2") — **this spec sets one**: raw snapshots follow the same 30-day-class retention spec 1 applied to structured logs (FR-046a precedent), via an S3 lifecycle rule, not indefinite retention like `audit_event` — snapshots are operational data for diffing, not an audit trail. |

**Live-verification discipline (playbook §0.5.3, §0.5.5)**: any session that deploys this spec's
scan orchestration against a real AWS account for verification must end with the full resource
sweep from playbook §0.5.3 — including the Step Functions/EventBridge-specific additions
(`aws stepfunctions list-state-machines`, already in that sweep) — and a full teardown before the
session ends, exactly as spec 1's T107–T109 sessions did. `DEV_AUTO_DEPLOY` must be confirmed
`true` before dispatching a verification deploy and should be set back to `false` afterward if dev
is torn down, per the same toggle discipline spec 1 established.

## R-208 — Live-verification and teardown plan for this spec specifically

Beyond the generic sweep, this spec's verification needs two AWS-account-specific checks the
generic sweep doesn't cover, because they're cross-account rather than in-account:

1. **A real second AWS account for cross-account verification** (spec.md Dependencies — mirrors
   spec 1's dev/prod pair). The cross-account template must actually be deployed there and torn
   down there too, not just in the primary account — an orphaned scanner role in a second AWS
   account is exactly the kind of thing the generic single-account sweep would miss.
2. **The ExternalId Secrets Manager reference** must be deleted alongside the `cloud_account` row
   it belongs to during teardown — Secrets Manager secrets have their own (small but real, and
   non-zero during a 7-30 day recovery window) storage cost if left behind after the referencing
   database row is gone via `terraform destroy`.

## R-209 — VERIFY: moto's coverage of Cloud Control API and Resource Groups Tagging API

Spec 1's R-007 established the testing split (moto for AWS API mocking, Testcontainers for
PostgreSQL, LocalStack only where it genuinely covers a service). **VERIFY** before writing
`backend/tests/unit/test_discovery.py`: does moto mock `cloudcontrol` (Cloud Control API) and
`resourcegroupstaggingapi` (Tagging API) with enough fidelity to exercise R-201's discovery logic,
or does one or both need a hand-built fixture/stub instead? If moto's coverage is thin, the
fallback is the same pattern spec 1's R-007 used for Cognito — a locally-constructed fixture that
tests the code actually written rather than testing moto's simulation fidelity.

## R-210 — VERIFY: LocalStack's Step Functions coverage for integration tests

Spec 1's R-007 noted LocalStack's free tier covers neither Cognito nor RDS, using Testcontainers
and moto instead for those. **VERIFY** whether LocalStack's free tier covers Step Functions Standard
workflows well enough for `backend/tests/integration/test_scan_orchestration.py`, or whether
integration testing for the state machine itself needs to happen via a real (torn-down-after)
`dev` deploy instead, with the Lambda-level logic covered by moto-based unit tests as the primary
gate. Either answer is workable; this only needs resolving before that specific test file is
written, not before implementation starts broadly.
