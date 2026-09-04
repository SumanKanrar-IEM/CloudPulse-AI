# Research: Cost, Utilization, and Notifications

Twelve decisions, in dependency order: notification delivery and its own scheduling, the three
services (Cost Explorer, IAM, and — confirmed technically avoidable but not funded — SES) this
spec calls that all inherit spec 004's own R-407 constraint identically, the budget/forecast model
and its finding-trigger semantics, the Finding schema extension a non-resource finding kind
requires, utilization's data source, and the real granularity limit on cost drill-down. R-510 is
the cost profile (playbook §0.5.3). R-511 carries R-407 forward — a standing constraint, not
re-litigated a third time per playbook §0.5.5.

## R-501 — Notification is one daily-scheduled Lambda per concern, not SQS fan-out

**Decision**: A single new Lambda, `notification-worker`, triggered by one EventBridge Scheduler
rule (`{"action": "trigger_daily"}`), mirroring spec 002's `scan-worker` daily-schedule pattern
exactly (`infra/modules/scan/scheduler.tf`): the schedule carries no per-finding knowledge, the
worker itself queries the database each run for every finding needing a day-0 email, a day-2/4
reminder, or an escalation flag today (FR-004–FR-011), sends what's due via SES, and records a
`Notification` row per attempt (sent, withheld, or suppressed) whether or not it succeeded. No
SQS queue, no DLQ, no per-finding fan-out.

**Rationale**: Spec 003's governance pipeline uses SQS (`R-303`) because it processes one message
per finalized scan, an event with real per-unit-of-work isolation needs (a scan's own governance
pass failing shouldn't touch another scan's). Notification has no equivalent per-event trigger to
react to — FR-004's "the same day a new finding opens" is satisfied by a worker that runs after
the day's scans/ingestion complete and asks "what's due today," the exact shape spec 002's own
daily-scan scheduler already established for "the worker queries what's due, the schedule stays
static." Per-finding failure isolation is handled with a plain try/except per finding inside one
invocation (logged, not raised, so one bad send never blocks the rest of the batch) — SQS's
retry/DLQ machinery buys nothing extra here that a loop with error handling doesn't already give,
at genuine added cost and complexity (a second queue pair, a second DLQ, per playbook §0.5.3's own
"every dollar spent is deliberate" standard).

**Alternatives considered**: An SQS-triggered worker, invoked by a hook in spec 003's
`finalize_scan` the moment a finding opens — rejected as unnecessary coupling into a pipeline
spec 003 owns and already documents as fully specified (`app/workers/README.md`'s own note this
package stays reserved "unless \[spec 005\] also prefers `handlers/`" — it does, matching every
worker before it, not `app/workers/`). A single combined worker doing notification AND cost
ingestion in one Lambda — rejected: different failure/retry profiles and IAM permission surfaces
(SES vs Cost Explorer vs IAM), the same reasoning R-303 already gives for keeping compliance
validation and ownership attribution as two workers, not one.

## R-502 — Budget creation is synchronous, inside the existing SDA-registration request, not a worker

**Decision**: FR-015's "within a day of registration" is satisfied by creating the `Budget` row
in the same request/response cycle as `POST /sdas` (spec 003's existing SDA-registration
endpoint) — immediately, not eventually. No new Lambda, no new schedule.

**Rationale**: "Within a day" is the spec's own outer bound, not a target; doing it synchronously
is strictly faster, needs no new infrastructure, and the registration endpoint already writes one
row (the SDA) inside one transaction — adding a second (the Budget) is a one-line extension of an
existing write path, not a new capability.

**Alternatives considered**: A daily "create budgets for any SDA registered without one" sweep —
rejected as needless indirection for something the registration request can just do.

## R-503 — Cost Explorer and IAM control-plane calls have no VPC PrivateLink support; both inherit R-407 unchanged

**Decision**: `cost-ingestion-worker` (spend ingestion + budget/overrun-finding check, one daily
Lambda, folded together per R-505 below) and `iam-hygiene-worker` (weekly, R-509) both run
VPC-attached like every other worker before them (Aurora access is private-subnet-only,
unchanged since spec 001), and both call AWS APIs that **do not support VPC interface
endpoints at all** — `ce:GetCostAndUsage` and the `iam:*` read calls this spec needs. This is a
documented AWS platform limitation for both services, not a configuration choice this plan makes:
neither Cost Explorer nor IAM publishes an interface-endpoint service name
(`aws ec2 describe-vpc-endpoint-services` against either would return nothing to attach a
`aws_vpc_endpoint` resource to even if funded). Both workers therefore inherit governance
dashboard's own **R-407** exactly — the standing, twice-declined-to-fund NAT/VPC-endpoint gap —
for every account registration, same-account mode included this time: unlike registration's
STS-specific hang (which same-account mode sidesteps entirely, per `connectors/aws.py`'s
`_build_session` returning the ambient session with no `AssumeRole` call at all), Cost Explorer
and IAM calls are inherently internet/AWS-public-endpoint-bound regardless of which connection
mode the account being analyzed uses. **This plan does not attempt to resolve that gap** — see
R-511.

**Rationale**: Stated explicitly, per playbook §0.5.5's instruction not to let a later spec
rediscover a known blocker the hard way. Building `cost-ingestion-worker`/`iam-hygiene-worker` as
VPC-attached anyway (rather than redesigning around the gap) is still correct: it's the same
shape every existing worker already has for Aurora access, it's demonstrably correct
architecture the moment R-407 is funded, and per-spec workarounds (e.g., a non-VPC Lambda that
proxies Aurora writes through the API Lambda instead of connecting directly) would be
meaningfully more complex than the gap they'd dodge, for a constraint this project has already
decided twice not to spend money resolving.

## R-504 — Resolved: SES's API is technically reachable via a VPC interface endpoint; not funded — `notification-worker` inherits R-407 like the other two workers

**Verified 2026-09-02**, against this project's real dev account (767828743440, us-east-1), not
assumed:

```
$ aws ec2 describe-vpc-endpoint-services --region us-east-1 \
    --query "ServiceNames" --output text | tr '\t' '\n' | grep -i email
com.amazonaws.us-east-1.email
com.amazonaws.us-east-1.email-fips
com.amazonaws.us-east-1.email-smtp
```

`com.amazonaws.us-east-1.email`'s private DNS name is `email.us-east-1.amazonaws.com` —
boto3's own default SES client endpoint, confirmed via
`describe-vpc-endpoint-services --service-names com.amazonaws.us-east-1.email`. So a VPC
interface endpoint for this service **would** work, technically, if funded.

**Decision**: Not funded. Presented to the user with real numbers (~$0.01/AZ/hour + ~$0.01/GB,
~$14.40/month at 2 AZs if left running continuously) — declined. `notification-worker` stays
VPC-attached with no endpoint, exactly like `cost-ingestion-worker`/`iam-hygiene-worker`, and so
inherits **R-407 unconditionally, the same as all three workers now** — R-503's "two of three"
framing is corrected by this entry; all three are bounded identically. This spec provisions no
new `aws_vpc_endpoint` resource.

**Rationale**: A real, new recurring cost is the user's call, not this plan's to decide
unilaterally, even at a small scale and even when it would cleanly unblock two P1 user stories'
live-verifiability — the same standard this project has already applied twice to the larger
NAT/VPC-endpoint package for R-407 itself. Confirming technical feasibility (this entry) without
assuming approval to spend on it were two separate questions, and only the first was this plan's
to answer alone.

**Alternatives considered**: Funding it (either 2-AZ or single-AZ) — offered to the user with
both cost and redundancy tradeoffs stated plainly; declined. Re-litigating the full R-407 package
instead — out of scope per playbook §0.5.5, unchanged.

## R-505 — Budget and overrun-finding checking run inside the same daily Lambda as spend ingestion, not a separate worker

**Decision**: `cost-ingestion-worker`'s one daily run, per registered account: (1) calls
`ce:GetCostAndUsage` grouped by service and the platform's configured project-tag key for
yesterday (UTC), (2) upserts a `SpendRecord` per (account, service, day), attributing each to an
SDA via `sda_matching.find_matching_sda` (reused as-is — a synthetic one-key tags dict built from
Cost Explorer's own tag-group key/value, R-507's data-model entry), (3) for every SDA with a
`Budget`, sums that day's (and month-to-date's) spend against the budget's cap, and opens or
resolves an overrun finding (FR-016/FR-017) in the same transaction. One worker, one schedule,
one place spend and budget state are ever computed from — never a race between two workers
disagreeing about the same day's total.

**Rationale**: Splitting ingestion and threshold-checking into two workers would need the second
to either re-derive the day's spend itself (duplicated logic) or trust the first already
committed (a real ordering dependency between two schedules, the exact kind of race spec 003's
R-303 deliberately avoided by keeping validation and ownership as independent, order-agnostic
units). Folding them keeps the dependency implicit and correct by construction: the threshold
check only ever sees a day's spend after that day's ingestion write, because it's the same
transaction.

**Alternatives considered**: A separate `budget-check-worker` on its own schedule, reading
already-committed `SpendRecord` rows — rejected for the ordering-race reason above, and because
it adds a second Lambda/schedule for work that's cheap enough (one more query, one more
conditional write) to just do inline.

## R-506 — Forecast is a simple linear trend over this spec's own ingested spend, not Cost Explorer's `GetCostForecast`

**Decision**: The "forecast" half of FR-015's 80%/100% thresholds is computed from the last 7
days of this SDA's own `SpendRecord` rows (a simple daily-average × days-remaining-in-month
extrapolation), not a second Cost Explorer API call.

**Rationale**: One data source, one thing to test, and one fewer AWS API surface to reason about
in R-503's VPC-reachability constraint (Cost Explorer's forecast endpoint is the same
non-PrivateLink service as `GetCostAndUsage`, so it inherits the identical R-503 gap regardless —
using our own already-ingested data doesn't dodge that, but it does mean this spec's own
forecasting logic is fully unit-testable with `pytest`, independent of any live AWS call, which a
`GetCostForecast`-backed version would not be). This is a deliberately lightweight forecast for a
budget *alert*, not spec 6's own S51 forecasting feature (backtested accuracy target, MAPE < 15%)
— the two are not the same claim and this spec's Assumptions section already says so.

**Alternatives considered**: `ce:GetCostForecast` — rejected per the rationale above; a naive
"forecast = last day's spend × days remaining" (no averaging) — rejected as too noisy against a
single unusual day (a one-off large charge would falsely trip a forecast-100 flag for the rest of
the month).

## R-507 — Only *actual* spend crossing 100% opens the overrun finding; forecast-100 and both 80% thresholds stay dashboard-only

**Decision**: FR-016 fires exclusively on actual month-to-date spend crossing the budget's 100%
cap. Actual-80%, forecast-80%, and forecast-100% are all recorded on `Budget` (four independent
crossed-timestamp fields) and shown on the cost dashboard, but none of the other three opens a
finding or sends any notification.

**Rationale**: The spec's own Clarifications session settled that 80% is dashboard-only
(User Story 4); this decision extends the same reasoning to forecast-100 specifically, because a
forecast is a projection, not a fact yet — opening a finding (and firing User Story 2's email)
over a projection that may not materialize would put a false-positive-prone signal into the same
pipeline this whole spec otherwise keeps strictly "a finding means something real is true right
now." Actual crossing 100% is the one unambiguous, already-happened fact among the four.

## R-508 — Finding gains a `kind` discriminator and nullable resource/rule columns; a budget-overrun finding attaches to an SDA, not a resource

**Decision**: `finding.resource_id`, `finding.rule_id`, and `finding.rule_version` become
nullable; a new `finding_kind` enum (`tag_violation` default, `budget_overrun`) and a nullable
`finding.sda_id` FK (→ `sda.id`) are added, with a CHECK constraint enforcing exactly one shape
per kind (`tag_violation`: resource_id/rule_id/rule_version NOT NULL, sda_id NULL;
`budget_overrun`: sda_id NOT NULL, the other three NULL). A second partial unique index,
`(tenant_id, sda_id) WHERE status = 'open' AND kind = 'budget_overrun'`, mirrors the existing
one-open-finding-per-resource-rule invariant at the per-project level. `findings.py`'s response
model, list query (currently an unconditional `JOIN Resource`), and detail/acknowledge paths all
need a kind-aware branch — full shape in `data-model.md` and `contracts/openapi.yaml`.

**Rationale**: FR-016 requires a budget overrun to use "the same pipeline and lifecycle spec 003
already defines" — the existing dedup, acknowledge, resolve, and (this spec's own additions)
notification-cadence and escalation machinery all operate on `Finding` rows, and duplicating that
machinery for a second, parallel "overrun" entity would mean re-solving problems (dedup, one-open-
per-X, notification wiring) `Finding` already solves, for no real benefit. The schema change is
additive (new nullable columns, new enum, new index) — no existing `tag_violation` row's shape
changes, and the existing partial unique index on `(tenant_id, resource_id, rule_id) WHERE status
= 'open'` is untouched, since a `budget_overrun` row has `resource_id`/`rule_id` both NULL and
Postgres partial/unique indexes never match a NULL key value.

**Alternatives considered**: A wholly separate `budget_overrun_finding` table with its own
acknowledge/notify endpoints — rejected for the duplication reason above, and because it would
mean User Stories 2/3's notification worker needs two independent "what's due" queries instead of
one, doubling a code path this spec otherwise keeps single. Making `sda_id` the *only* target
column (repurposing `resource_id` to point at a synthetic per-SDA "resource" row) — rejected: it
would misrepresent an SDA as a discovered cloud resource in every place that reads `Finding.
resource_id`, a correctness risk (inventory queries joining through `resource_id` would need to
know to exclude synthetic rows) for no reduction in actual schema surface versus a nullable
column plus a discriminator.

## R-509 — Utilization is computed live from `Resource.state`, scoped to resources where state is actually known

**Decision** (Clarifications session, Q1): "used" = a resource's own `state` indicating an
active/running condition; "provisioned" = every non-deleted, top-level-or-child resource in the
account/project. Computed on demand in the API route (`SELECT` + `GROUP BY`, no precomputation,
no new worker, no new schedule) — cheap enough (an indexed count over already-persisted rows) that
caching or a daily snapshot would be premature optimization for demo scale. **Resources with
`state IS NULL`** (most types — `state` is only ever populated by the six/ten P1+P2 enrichment
functions, per `connectors/aws.py`'s own discovery-time default of `state=None`) are excluded from
**both** the numerator and the denominator, not counted as either used or idle — the dashboard
states this scope explicitly (e.g., "N of M enriched resources," not a claim over the full
inventory) rather than silently understating utilization for resource types this platform hasn't
enriched at all.

**Rationale**: A resource this platform has never inspected has no evidence either way; counting
it as "idle" would systematically understate utilization for every account with unenriched
resource types, and counting it as "used" would systematically overstate it — both are worse than
being honest about the scope actually being measured. "Idle" is classified via a small,
documented set of known-idle state strings per service (`stopped`, `stopping`, `terminated`,
`deleting` for EC2/RDS-shaped states; every other known, non-null state value counts as used) —
a `dict`/`set` in `app/governance/utilization.py`, not a per-service `if/elif` chain, matching
`coverage_definitions.json`'s own data-as-config precedent elsewhere in this codebase.

**Alternatives considered**: Treating `state IS NULL` as "used" (optimistic default) — rejected,
overstates utilization silently. CloudWatch metrics-based utilization (the backlog's own original
S54→S50 dependency) — rejected per the Clarifications session; S50 is R3, out of this spec's
scope.

## R-512 — Drill-down bottoms out at the SDA/service level, not a per-resource dollar figure

**Decision**: `GET /spend` and its drill-down endpoints return spend aggregated by account,
service, and SDA/project — the granularity `ce:GetCostAndUsage`'s own grouping dimensions
actually support. The resource-level step of spec.md's own drill-down (User Story 1, Scenario 3)
is satisfied by listing which resources belong to the SDA/service line being viewed (a query
against already-persisted `resource` rows, joined by `sda_id`/`service`), not a per-resource
dollar amount — Cost Explorer's `GetCostAndUsage` API has no resource-ARN grouping dimension at
all; that granularity exists only via Cost and Usage Reports (a heavier, S3-delivered,
schema-managed export pipeline), which this spec does not adopt.

**Rationale**: Spec.md's own Acceptance Scenario wording ("the resource-level figure they land on
is consistent with — **a real contributor to** — the totals above it") was deliberately written
soft enough to accommodate this: a resource genuinely is a real contributor to its SDA's spend
line, without this spec claiming to price that contribution individually. Adopting Cost and Usage
Reports for true per-resource pricing would be materially larger scope (a new S3 export pipeline,
a new ingestion shape, Athena or similar to query it) for a capability neither FR-001–FR-003 nor
any success criterion actually requires at that precision — SC-001's ±1% reconciliation claim is
about the account/service/day total, not a per-resource figure.

**Alternatives considered**: Adopting Cost and Usage Reports now — rejected as disproportionate
scope for this release; splitting a service/SDA line's total evenly across its member resources
as an estimate — rejected as actively misleading (a fabricated-precision number presented as if
it were real, the exact failure mode spec 6's own Constraints section already forbids for agent
outputs, and no less wrong here for being arithmetic instead of a model).

## R-510 — Cost profile for this spec's new AWS resources (playbook §0.5.3)

This account has no free tier; every new billable resource gets the same pricing-floor-level
reasoning as spec 1's R-003 and spec 003's R-306, not an assertion of "cheap."

| Resource | Dev/prod choice | Reasoning |
|---|---|---|
| `notification-worker` Lambda + its EventBridge Scheduler rule | arm64, 512MB, daily schedule | Same per-GB-second reasoning as every prior worker (R-207/R-306): arm64 ~20% cheaper than x86; one invocation/day at demo scale is immaterial regardless of architecture choice. Smaller memory than the governance workers (512MB vs 1024MB) — this worker does no CPU-bound work, just DB reads/writes and SES API calls. |
| `cost-ingestion-worker` Lambda + its EventBridge Scheduler rule | arm64, 512MB, daily schedule | Same reasoning. One `ce:GetCostAndUsage` call per registered account per day. |
| `iam-hygiene-worker` Lambda + its EventBridge Scheduler rule | arm64, 512MB, **weekly**, not daily | IAM last-used data changes slowly (last-used timestamps update in hours-to-days granularity per AWS's own documented behavior, not real-time) — daily analysis would burn seven times the Lambda invocations and IAM API calls for no additional signal. Weekly is the cheapest cadence that still meets FR-019/FR-020's "flag-only recommendation" bar; nothing in the spec's success criteria requires daily freshness for this story. |
| Amazon Cost Explorer API calls (`ce:GetCostAndUsage`) | Standard API pricing (~$0.01/request beyond the first request per month, which is free) | One call per registered account per day. At demo scale (a handful of accounts), this is cents per month, stated explicitly rather than left as "presumably cheap." No new AWS resource is provisioned for this — it's an API call against data AWS already collects, not a new billable service instance. |
| Amazon SES | No monthly base cost; **$0.10 per 1,000 messages sent**, with a persistent (not 12-month-limited) free allowance of 62,000 messages/month when sending from a Lambda in the same AWS region — a perpetual per-service allowance, distinct from and not contradicting this account's lack of the general 12-month AWS Free Tier the rest of this section reasons around. At this platform's demo-scale finding volume (single digits to low tens of notifications/day), actual cost is $0 either way. **Domain identity is NOT provisioned** — dev/demo operates in SES's default sandbox mode (verified individual recipient addresses only, 200 emails/day, 1/sec), the same operational pattern already used for Cognito test users in prior live-verification sessions (T032's `*@cloudpulse-t032-verify.test` accounts) — a real owned domain for production sending is an ops decision out of this spec's scope, not a blocker for demo-scale live-verification. |
| No new Aurora capacity | Reuses the existing dev/prod clusters at their existing `min_acu = 0.5` | This spec adds five columns and one enum to `finding`, plus three small new tables (`spend_record`, `budget`, `notification`). No new database capacity is provisioned. Spec 1's R-003 RDS Proxy reasoning still applies unchanged. |
| No new VPC endpoint, no NAT gateway | Explicitly not provisioned by this plan | R-503/R-511: the standing, twice-declined-to-fund gap is not funded a third time without a new signal from the user. R-504 confirmed a narrower, single-purpose SES endpoint was technically available and would have unblocked notification-worker alone at a small, stated cost — presented to the user with real figures, and declined; not provisioned by this plan either. |
| No new Cognito pool, API Gateway, or Step Functions state machine | Reuses spec 1's identity/API surface and spec 002's orchestration entirely | Per playbook §0.5.4 — nothing here needs a second instance of any of the three. |

**Live-verification discipline (playbook §0.5.3, §0.5.5)**: any session that deploys this spec's
workers against a real AWS account for verification must end with the full resource sweep from
playbook §0.5.3, extended to confirm all three new EventBridge Scheduler rules and all three new
Lambda functions (and their CloudWatch log groups — the "no retention policy" check applies to
three *new* log groups here) are gone. `DEV_AUTO_DEPLOY` discipline is unchanged from prior specs.

## R-511 — Standing constraint, carried forward unchanged: R-407 (governance dashboard's own account-registration gap) now also bounds this spec's cost/IAM ingestion and — confirmed feasible, declined to fund — its notification worker too

Per playbook §0.5.5's explicit instruction not to re-litigate the NAT/VPC-endpoint cost tradeoff a
third time without a new signal from the user: this plan does not attempt to fund a fix. R-503
and R-504 above together state precisely why every one of this spec's three new workers — not
just two — is bounded identically: Cost Explorer and IAM have no PrivateLink option to fund even
if the user wanted to (R-503); SES does have one, priced and presented, and the user declined it
(R-504). Live-verification for User Stories 1, 2, 3, 5, and 7 (spend visibility, notification,
cadence/escalation, overrun findings, IAM hygiene) is bounded by this exactly the way spec 004's
own T032 was bounded for its populated-dashboard stories: provable at the mocked-test level in CI
(moto covers `ce`, `iam`, and `ses` clients), not provable live against a real send or real
ingested data until R-407 is funded.

~~**User Story 6 (utilization) is the one genuine exception** — it makes no AWS call at all
(R-509, computed entirely from already-persisted `Resource.state`) and is fully live-verifiable
today, independent of R-407's status.~~

**Corrected 2026-09-04, by attempting it (T051/T051a).** That exception does not hold. The
reasoning above is right about the *computation* — `compute_utilization` makes no AWS call — and
wrong about its *input*. `Resource.state` is "already-persisted" only if a scan has ever run;
a scan needs a registered account; and `register_account` calls STS and the Resource Groups
Tagging API, which is precisely the R-407 hang spec 003's own live verification stopped at.
Confirmed against the live dev environment rather than inferred: **zero NAT gateways, and the
only VPC endpoints present are S3 and Secrets Manager** — nothing for `sts`, `tagging`, `ce`,
`iam`, or `email`. So there is no route by which any resource acquires a `state` for utilization
to count.

What *is* live-verifiable, and was verified: the endpoint deploys, is reachable, and is
correctly role-gated. What is not: SC-007's hand-calculation against real scanned data. SC-007
therefore lands exactly where SC-001–SC-006 and SC-008 do — proven at the mocked-test level,
bounded by R-407 — and this spec has **no** live-provable success criterion after all.
