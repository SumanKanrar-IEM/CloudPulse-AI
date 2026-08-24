# Research: Tag Compliance and Ownership

Seven decisions, following specs 1–2's format: Decision / Rationale / Alternatives considered. Two
carry **VERIFY** markers. R-306/R-307 exist because the plan input explicitly requires a cost
profile and a live-verification discipline statement, mirroring spec 1's R-003 and spec 002's
R-207/R-208.

## R-301 — A finding follows a rule's stable key across edits, by re-pointing its FK

**Decision**: `Finding.rule_id` is a foreign key to one specific `Rule` row (spec 1's schema:
`Rule` is unique on `tenant_id, key, version`, so every edit is a new row). To honor the spec's
Clarifications decision — a finding stays tied to the rule's *key*, not one version — the
validation engine looks up an already-open finding for a resource by **joining `Finding` to `Rule`
and filtering on `Rule.key`**, not by matching `rule_id` directly. When re-evaluating, if that open
finding's `rule_id` now points at a superseded version, the engine **updates** `rule_id` (and
`rule_version`) to the currently-enabled version's row before deciding whether the violation still
holds, rather than leaving it pointed at the stale row.

**Rationale**: This requires no migration — `Rule`'s existing shape (a stable `key` plus an
incrementing `version`) already carries everything needed; the only change is in the query
(join through `key`, not `rule_id`) and in what a re-evaluation writes (an UPDATE of the existing
open row's `rule_id`, not an INSERT of a new one). This is also what keeps FR-016's auto-close
guarantee true: without this, an already-open finding pinned to a superseded rule row would never
be re-evaluated by any future scan (nothing queries by that stale `rule_id` again), so it could
never legitimately close — an orphaned finding, permanently open, that no admin action created and
none can clear.

**Alternatives considered**: Add a new `rule_key` column to `Finding`, duplicating what's already
derivable via the join — rejected as an unjustified schema change when the existing `Rule.key` +
`Finding.rule_id` shape already supports the join-based lookup with zero migration. Leave findings
permanently pinned to the version that opened them (spec's rejected Option B/C during
`/speckit-clarify`) — rejected at the spec level already; not re-litigated here.

## R-302 — Ownership attribution: one bulk CloudTrail sweep per scan, never per resource

**Decision**: The ownership-attribution worker calls `cloudtrail:LookupEvents` **once per scan**
(paginated, time-windowed to the preceding 90 days), not once per resource. Each returned event's
response elements are parsed for the identifiers CloudTrail records for that event type (for
example, `RunInstances`' response includes the launched instance's ID), producing a map from
resource identifier to `{principal, event_name, event_time}`. That map is then correlated
in-memory against the scan's current resource set (already persisted by `finalize_scan` before this
worker runs) to attribute each resource — the reverse of iterating resources and querying per one.

**Rationale**: The spec's own input describes attribution as "for each resource, mine 90 days of
cloud audit events" — read literally, that's a per-resource `LookupEvents` call, which does not
scale: spec 002's own Edge Cases already anticipate "tens of thousands of resources" in the largest
connected account, and `LookupEvents` is rate-limited (2 req/s by default) with no per-resource
filter parameter that would make a targeted call any cheaper than a broad one. `LookupEvents`' own
design is naturally a *time-range* query, not a *resource* query — a bulk sweep is not a workaround,
it is the API used as intended, and it turns the attribution worker's AWS-call count from "one per
resource" into "however many pages of events actually occurred in 90 days," a number bounded by
account activity, not inventory size. FR-020's actual requirement ("determine its creator by
examining the audit trail") is satisfied identically either way — this is a plan-level "how"
decision, not a spec-level "what" one, matching how spec 002's own R-201 left "Cloud Control API vs.
Tagging API sweep" to research.md rather than spec.md.

**Alternatives considered**: Per-resource `LookupEvents` calls filtered by `ResourceName` (the API
does support a resource-name lookup attribute for some event types) — rejected: coverage is
inconsistent across event/resource types (not every CloudTrail event records a queryable resource
name), and even where it works, N calls for N resources still multiplies against the 2 req/s rate
limit in a way one bulk sweep does not. A configured CloudTrail Trail with S3 delivery, queried via
Athena — rejected as genuine overkill for demo scale, and it would require *creating* a Trail
resource in the scanned account, which — unlike reading Event History — is a write/configuration
action against a scanned account, forbidden by spec 002's FR-005 regardless of demo scale.

## R-303 — Governance pipeline runs via SQS + Lambda workers, enqueued by scan finalization

**Decision**: `finalize_scan` (spec 002's `app/scan/orchestrator.py`) gains one additional
responsibility: after it sets the scan's final status and runs the deleted-marker sweep, it
enqueues one message per finalized scan to **two** new SQS queues — `compliance-validation` and
`ownership-attribution` — each consumed by its own Lambda worker. These workers are **not** a new
orchestration mechanism competing with Step Functions; they are event-driven consumers of the scan
lifecycle's own completion event, the same relationship spec 002's own worker Lambda already has to
Step Functions (a consumer invoked by an upstream trigger, not a second scheduler).

**Rationale**: This reconciles two things that would otherwise conflict: the plan-time-standing
technology direction explicitly names "SQS + Lambda workers for validation, ownership, and cost
ingestion" (spec 5's cost ingestion is out of scope here, but the pattern is shared), while
spec.md's own Dependencies section — written at spec time, before this plan resolved the mechanism
— says validation/scoring/attribution "run inside" spec 002's scan lifecycle and that this spec
"does not invent a second orchestration mechanism." Both are true under this design: the pipeline is
*driven by* scan completion (satisfying the spec's intent — nothing about SC-003/SC-004 requires
synchronous-with-scan-completion timing, only correctness), while the actual compute runs
decoupled, which is what keeps R-302's bulk CloudTrail sweep off the existing scan-worker Lambda's
30-second-class timeout budget entirely — a resource-count-bound cost that has no business sharing
a budget with Step Functions' own per-unit retry accounting. Two queues, not one, because
validation (SDA matching, rule evaluation, scoring — all in-memory/DB-only, fast, no AWS calls) and
ownership attribution (network-bound, rate-limited, genuinely slower) have different failure and
retry profiles; coupling them into one queue would mean a slow CloudTrail sweep's retry backoff
also delays fast validation work for the same scan, and vice versa.

**Alternatives considered**: Embed both steps synchronously inside `finalize_scan`'s own Lambda
invocation — rejected on R-302's own grounds: this would need one CloudTrail sweep to complete
inside the same invocation that also runs the deleted-marker sweep and resource count, and the two
have unrelated timeout budgets that shouldn't be coupled. Add a second Step Functions Map state for
governance processing — rejected as genuinely inventing a second orchestration mechanism (a new
state machine or a new Map branch), which the spec's Dependencies section explicitly rules out, and
which the plan-time technology direction doesn't call for either (it names SQS + Lambda, not a
second state machine).

## R-304 — New schema is minimal and P2-only: one table, one column, both deferred past P1

**Decision**: `Rule`, `Finding`, `Sda`, and `ResourceOwner` need no new columns — their existing
JSONB (`Rule.definition`, `Sda.tag_values`) and typed (`ResourceOwner.confidence`,
`ResourceOwner.evidence`) columns already carry everything P1's five stories need. The only new
schema this spec adds serves P2's owner identity resolution (S23a) exclusively: a nullable
`owner_identity_pattern` column on `tenant` (a genuinely tenant-wide, singleton-per-tenant config
value, so it belongs on the row that already represents "one tenant," not a new one-row-per-tenant
table), and one new table, `owner_identity_override` (`tenant_id`, `principal_id`, `owner_email`,
timestamps — genuinely N rows per tenant, one per identity the pattern can't resolve, so it needs
its own table, unlike the pattern itself).

**Rationale**: Minimizing new schema is Principle I discipline applied literally — spec 1 already
reserved exactly the shape P1 needs, and adding speculative columns "while we're in here" for P2
would be scope creep the constitution's Honest Prioritization principle exists to prevent. Putting
the singleton pattern value on `tenant` rather than a new `owner_identity_config` table with one row
per tenant avoids a table whose entire reason to exist is holding one string.

**Alternatives considered**: A generic key-value settings table for all future per-tenant config,
not just this one pattern — rejected as speculative infrastructure with no second consumer yet;
nothing else in specs 1–3 needs one, and inventing it here for a single string value is exactly the
kind of unjustified complexity Principle I's "every artifact traces to a merged spec" test would
catch. Storing the override table's identity as a foreign key into some existing identity table —
rejected: the audit-trail principal id (an IAM ARN or Cognito-independent AWS identity string) has
no corresponding row anywhere in this platform's own schema; it is inherently a free-text external
identifier, not a reference to platform data.

## R-305 — SDA overlap detection: exact tag-key/value intersection, not a tie-break rule

**Decision**: Two SDAs' `tag_values` mappings are considered overlapping — and a new/edited mapping
is refused (FR-010a) — if, for every tag key present in *both* mappings, the required value is the
same. A mapping with an extra key the other lacks (for example, `{team: platform}` versus
`{team: platform, env: prod}`) still counts as overlapping under this rule, even though one is a
strict subset of the other's criteria, because a resource satisfying the more specific mapping also
satisfies the less specific one — both would claim it.

**Rationale**: FR-010a's own language ("never ambiguous or order-dependent") requires catching
exactly this subset case, not just identical mappings — an identical-only check would let a
"platform team, prod" SDA and a "platform team" SDA both register successfully and then silently
disagree over every matching prod resource, precisely the ambiguity the requirement forbids.

**Alternatives considered**: Allow subset/hierarchical mappings deliberately (a more specific SDA
"nested" under a broader one, with the more specific one taking precedence) — rejected: nothing in
spec.md's stories or requirements asks for SDA hierarchy, and introducing an implicit precedence
rule (most-specific-wins) to make it safe would be exactly the kind of order/specificity-dependent
resolution FR-010a's own Edge Case exists to rule out. Simpler than it looks to add later if a real
need for it emerges (spec.md's Out of Scope doesn't foreclose it) — better to not build it now.

## R-306 — Cost profile for this spec's new AWS resources (playbook §0.5.3)

This account has no free tier; every new billable resource gets the same pricing-floor-level
reasoning as spec 1's R-003, not an assertion of "cheap."

| Resource | Dev/prod choice | Reasoning |
|---|---|---|
| SQS (`compliance-validation`, `ownership-attribution` queues + DLQs) | Standard queues, not FIFO | SQS Standard is priced per request at a rate that rounds to negligible at demo-scale message volume (one pair of messages per finalized scan — tens/day). FIFO costs more per request and caps throughput for an ordering guarantee this design doesn't need: each message is independently processable (one scan's governance pipeline doesn't depend on another's completing first), so Standard's at-least-once, unordered delivery is strictly sufficient and cheaper. |
| Compliance-validation / ownership-attribution Lambda workers | arm64, sized like spec 002's scan-worker Lambda (1024MB) | Same reasoning as spec 002's R-207: arm64 is ~20% cheaper than x86 per GB-second for equivalent performance; demo-scale invocation counts (one pair per finalized scan) make architecture choice immaterial to total cost regardless. |
| `cloudtrail:LookupEvents` calls | No new billable resource at all | `LookupEvents` against CloudTrail's default Event History is a **free API call** — no Trail, no S3 bucket, no CloudWatch Logs delivery is created or required (spec.md's own Assumptions section already rules a configured Trail out, for the independent reason that creating one is a write action FR-005 forbids). This line item costs literally nothing, stated explicitly rather than left implicit, per this plan's own "don't just assert cheap" instruction. |
| No new Aurora capacity | Reuses the existing dev/prod clusters at their existing `min_acu=0.5` | This spec adds one small table and one nullable column; it provisions no new database capacity. Spec 1's R-003 RDS Proxy reasoning still applies unchanged. |
| No new Cognito pool, API Gateway, or Step Functions state machine | Reuses spec 1's identity/API surface and spec 002's orchestration entirely | Per playbook §0.5.4 and this spec's own Dependencies section — nothing here needs a second instance of any of the three. |

**Live-verification discipline (playbook §0.5.3, §0.5.5)**: any session that deploys this spec's
governance pipeline against a real AWS account for verification must end with the full resource
sweep from playbook §0.5.3, extended to include `aws sqs list-queues` (already in the generic
sweep) confirming both new queues and their DLQs are gone, and a check that the two new Lambda
workers' CloudWatch log groups were not left behind with no retention policy (§0.5.3's log-group
check already covers this generically, called out again here because two *new* log groups are easy
to miss amid spec 002's existing ones). `DEV_AUTO_DEPLOY` discipline is unchanged from spec 002's
R-207.

## R-307 — VERIFY: moto's coverage of CloudTrail's `lookup_events`

Specs 1–2's R-007/R-209 established the testing split (moto for AWS API mocking, Testcontainers for
PostgreSQL). **VERIFY** before writing `backend/tests/unit/test_ownership_attribution.py`: does
moto mock `cloudtrail.lookup_events` with enough fidelity to exercise R-302's bulk-sweep-and-
correlate logic — specifically, can a moto-backed test actually generate CloudTrail events for
resource-creation API calls (for example, does calling moto's `ec2.run_instances` produce a
correspondingly mocked `RunInstances` CloudTrail event `lookup_events` will later return), or does
moto's CloudTrail mock only accept hand-constructed event fixtures with no automatic correlation to
other mocked API calls? If moto's coverage is thin (plausible — CloudTrail is a cross-cutting audit
service, not a resource API, and moto's per-service fidelity varies), the fallback is the same
pattern R-209 already established: hand-built fixtures (mocking the boto3 `lookup_events` response
shape directly) test the parsing/correlation code actually written, rather than testing moto's
simulation fidelity for a service moto may not deeply model.
