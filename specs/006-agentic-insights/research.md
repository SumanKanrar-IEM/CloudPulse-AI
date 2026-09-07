# Research — Agentic Insights (spec 006)

Numbered `R-6xx`, continuing the convention specs 001–005 used. Each decision records what was
chosen, why, and what was rejected — so a later reader can tell a considered choice from an
accident.

## R-601 — Bedrock Agents with Lambda action groups, not direct `InvokeModel`

**Decision**: The GenAI layer is Amazon Bedrock Agents. Each capability (digest, suggester,
advisor, narrator) is an agent with action groups implemented as Lambda functions, which call the
platform's own HTTP API as the read-only agent principal spec 001 reserved.

**Rationale**: Constitution Principle II (NON-NEGOTIABLE) fixes the product GenAI layer to
"Amazon Bedrock Agents — agents, action groups, and guardrails". A direct `bedrock-runtime:
InvokeModel` call with hand-rolled tool-calling would be simpler to build and cheaper to run, and
is explicitly not permitted. This plan does not revisit that; changing it is a constitution
amendment, not a plan decision.

**Alternatives considered**: Direct `InvokeModel` with our own orchestration — prohibited by
Principle II. Bedrock Flows — not "agents, action groups, and guardrails" as named.

## R-602 — Action groups call the HTTP API, never the database

**Decision**: Action-group Lambdas call the deployed API Gateway endpoint using the
`AgentPrincipal` path `app/core/agent_access.py` already provides (`custom:agent_id` claim,
`READ_ONLY_METHODS`, viewer role, every mutating method refused). They receive no database
credential and no `AssumeRole` grant into any scanned account.

**Rationale**: Spec 001's FR-056 built this deliberately and its module docstring states why —
"a rule stated once in a constitution and re-implemented by each later spec is a rule that
eventually gets implemented wrong." Giving action groups a database session would be faster and
would bypass tenant scoping, the read-only method filter, and the audit trail in one step.

**Consequence worth stating**: the action-group Lambdas need network egress to API Gateway. That
is the same egress constraint every other worker has (see R-605).

## R-603 — The coverage advisor can propose *rules* as data, but not *enrichment* as data

**Decision**: The advisor's P2 scope is split, and the split is a real constraint rather than a
staging choice:

* **Rule extensions are genuinely code-free.** `rule.definition` is JSONB and spec 003's engine
  evaluates it as data, so an accepted proposal that adds or widens a tagging rule takes effect
  on the next scan with no deployment — exactly what FR-017 and SC-003 claim.
* **Enrichment coverage is not.** `backend/app/scan/coverage_definitions.json` maps a resource
  type to an `enrichment_function` **name** — a Python function that must already exist. A
  proposal to enrich a resource type nobody has written an enricher for cannot take effect
  without a code change, however the proposal is stored.

So the advisor proposes three classes, and only the first two satisfy "no code change":

1. a new or widened **rule** over already-collected fields — data only;
2. **enabling enrichment for a type whose enricher already exists** but is not in the coverage
   map — data only;
3. a type with **no existing enricher** — surfaced as a *documented gap for a human*, explicitly
   not as an acceptable proposal, because accepting it could not do anything.

**Rationale**: FR-017 says an accepted proposal takes effect "with no code deployment". Without
this split that requirement would be unimplementable for class 3 and the spec would ship a button
that silently does nothing. Naming the boundary now is cheaper than discovering it in
implementation — the lesson playbook §0.5.5 records about assumptions that read as settled.

**Alternatives considered**: A generic data-driven enricher (a declarative field-extraction DSL
over Cloud Control payloads) — genuinely would make class 3 data-only, and is real unplanned
scope: a DSL, its evaluator, its validation, and its own security review. Rejected for a P2
story; recorded here as the thing to build if class-3 coverage is ever wanted.

## R-604 — Bedrock's VPC reachability is UNVERIFIED and must be checked before any funding claim

**Decision**: This plan does **not** assert whether Bedrock (`bedrock`, `bedrock-runtime`,
`bedrock-agent`, `bedrock-agent-runtime`) or CloudWatch (`monitoring`) publish VPC interface
endpoints. It must be verified live before any statement is made either way, with:

```bash
aws ec2 describe-vpc-endpoint-services --query 'ServiceNames' --output text | tr '\t' '\n' | grep -iE 'bedrock|monitoring'
```

**Why this is a decision and not an omission**: an attempt to verify it during planning returned
"available: 0" for every service — including `monitoring`, which is known to publish an endpoint.
The command had a swallowed authentication failure (`2>/dev/null || echo 0` turning an expired SSO
token into a plausible-looking zero). The result was wrong for every row, in a way that would have
read as a confident finding. It is recorded here as unverified rather than guessed, and the check
above avoids the same trap by not suppressing errors.

**What is verified** (T051, spec 005, against the running dev environment): the deployed VPC has
**no NAT gateway** and only **S3 and Secrets Manager** interface endpoints. That is a fact about
what is *provisioned*, not about what AWS *offers* — the two were conflated once already and must
not be again.

**Consequence for this spec either way**: if endpoints exist, this is R-504's situation (a
priced, fundable gap the maintainer may decline); if they do not, it is R-503's (a platform
limitation with nothing to fund). The spec is already written to be acceptable in either case —
FR-007a and SC-009 make an unreachable model a specified, testable state.

## R-605 — Every new compute is VPC-attached, and inherits the standing R-407 gap

**Decision**: The action-group Lambdas, the digest worker, the suggester worker, and the metrics
collector are all VPC-attached, like every worker specs 002–005 built.

**Rationale**: they need Aurora, which is private-subnet-only and has been since spec 001. The
alternative — a non-VPC Lambda proxying database access through the API Lambda — is more moving
parts than the gap it dodges, which is the same conclusion R-503 reached for spec 005's workers.

**Consequence**: they cannot reach Bedrock, CloudWatch, or their own API Gateway endpoint at
runtime until the R-407 NAT/endpoint gap is funded. Twice declined; this plan does not re-litigate
it (playbook §0.5.5). Every capability here is therefore expected to be proven at the mocked-test
level, and FR-007a/SC-009 exist precisely so that is a specified outcome rather than a failure.

## R-606 — Cost profile for every billable resource this spec adds

This account has no free tier (playbook §0.5.3), so each new resource gets the same
pricing-floor reasoning R-003 applied to RDS Proxy.

**Prices below are structural, not quotes.** Bedrock and CloudWatch pricing changes and is
region-specific; verify against the live pricing pages before funding anything. What matters here
is the *shape* of each cost and which lever controls it.

| Resource | Cost driver | Dev posture | Why |
| --- | --- | --- | --- |
| Bedrock model invocation | per input + output token | **The dominant cost.** Capped per run (FR-004) | Token cost scales with the *content* sent, so the lever is how much governance data each prompt carries, not how often runs fire |
| Bedrock Agent orchestration | per invocation, plus the model tokens each reasoning step spends | Fewest action-group round trips that answer the question | An agent that re-queries the API five times pays model tokens five times to decide to |
| Action-group Lambda | per ms, arm64 | 512MB, same as every other worker | Trivial against token cost; not worth tuning |
| Digest/suggester workers | per ms, daily | 512MB, daily schedule | Same shape as the notification worker |
| CloudWatch `GetMetricData` (P2) | per metric-datapoint requested | P2 only; not deployed for P1 | Scales with resources × metrics × periods — the one P2 cost that grows with inventory |
| Metrics storage | Aurora rows | P2 only | Bounded by the 30-day retention FR-006a fixes |
| Agent/digest/rejection rows | Aurora rows | Negligible | One digest per tenant per day, expired at 30 days |
| Bedrock Guardrails | per text unit evaluated | On for every agent output | Small against generation cost, and non-optional — Principle II names guardrails |

**The structural point, mirroring R-003's pricing-floor argument**: the per-finding suggestion
decision (Clarifications, 2026-09-05) makes suggester cost scale with *open finding count*, not
with finding classes. At a few hundred open findings that is a few hundred model calls per run.
This is the one design decision in the spec with an unbounded-looking cost curve, and FR-004's
cost cap is the only thing bounding it — which is why the cap is a requirement rather than an
operational setting, and why a truncated run is a specified state rather than an error.

**Dev/prod parity**: dev runs the same agents on the same schedules with a lower cost cap. No
separate model, no separate prompt set — a cheaper model in dev would make the eval suite
meaningless as a signal for prod.

**Teardown**: any live-verification session ends with `ops/teardown.sh dev` **and** the full
§0.5.3 sweep, extended for this spec to confirm the agents, action-group Lambdas, guardrails, and
their log groups are gone. Spec 005's own teardown proved the sweep matters: `terraform destroy`
reported 106 resources destroyed and still left an RDS-created log group with no retention policy.

## R-607 — Grounding validation is deterministic code, never a second model call

**Decision**: The validator that enforces FR-001 is ordinary Python: extract every candidate
identifier and figure from the agent's output, look each up against the governance store, reject
the whole output if any is absent.

**Rationale**: a validator that itself hallucinated would defeat its own purpose, and Principle
IV's testable clause demands "every agent response passes a grounding validator that rejects ARNs
and metrics absent from the platform datastore" — which is only meaningful if the validator is
deterministic. It also keeps the validator unit-testable with no cloud call, which is what lets
SC-001 be proven in CI while the model itself is unreachable.

**Consequence**: extraction is pattern-based and will occasionally flag a figure that was fine.
Rejecting a good digest is the acceptable failure direction; displaying a fabricated ARN is not.

## R-608 — Prompts and agent definitions are files in `agents/`, versioned by content hash

**Decision**: Prompts, agent definitions, and action-group schemas live in `agents/` as files.
Every stored output records the content hash of the definition that produced it (FR-005).

**Rationale**: a version string someone must remember to bump is a version string that goes
stale. A content hash cannot disagree with the file it came from. It also makes "did behaviour
change because the prompt changed?" answerable from the stored record alone.

## R-609 — The eval suite runs in CI against recorded fixtures, not against live Bedrock

**Decision**: `agents/evals/` holds cases with recorded model responses. CI asserts the
deterministic parts — the grounding validator, the output schema, the refusal of mutating
methods, the cost-cap accounting — without calling Bedrock.

**Rationale**: a CI job that calls a live model is non-deterministic, costs money per PR, and
here would fail outright given R-605. This keeps the constitution's "eval suite in CI" real
rather than aspirational, and is the same choice R-509 made for utilization: prefer the thing
that is actually provable.

**Alternatives considered**: live-model evals gated to a manual workflow — sensible later, and
recorded as out of scope until R-407 is funded.

## R-610 — Digest storage is a row, not a rendered artifact

**Decision**: A digest is stored as structured content plus its provenance (run, definition hash,
period, outcome), and rendered by the frontend.

**Rationale**: storing rendered HTML would put model output directly into the DOM path and make
grounding re-validation impossible after the fact. Structured content keeps the validator's
verdict meaningful and lets the same digest be re-rendered if the presentation changes.
