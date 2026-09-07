# Quickstart — Agentic Insights (spec 006)

Runnable validation scenarios. `V1`–`V2` prove the P1 stories; `V3`–`V7` prove P2.

> **Read this before planning a live session.** Every capability in this spec calls Amazon
> Bedrock from a VPC-attached Lambda. The dev VPC has no NAT gateway and only S3 and Secrets
> Manager interface endpoints — verified against the running environment during spec 005's T051.
> Whether Bedrock *offers* an interface endpoint is **unverified** (research.md R-604); check it
> with the command in R-604 before claiming anything either way.
>
> Plan for the model being unreachable. That is a **specified, testable state** here (FR-007a,
> SC-009), not an outage — which is what makes V1, V2 and V7's degraded paths runnable today and
> the rest provable at the mocked-test level. This is the same honest bound specs 002–005 each
> landed on, stated before the attempt rather than discovered during it.
>
> **Tear down and run the full §0.5.3 sweep at the end of any session that deployed**, extended
> to confirm the Bedrock agents, agent aliases, guardrails, action-group Lambdas, and their log
> groups are gone. Spec 005's teardown reported `Destroy complete! Resources: 106 destroyed.` and
> still left an RDS-created log group with no retention policy — the exit code is not the check.

## Prerequisites

- Specs 001–005 deployed and reachable, with at least one admin user.
- A tenant with open findings, a compliance score that has moved, and ingested spend — otherwise
  the digest correctly reports "nothing notable" and V1 proves less than it appears to.
- For any live-model step: the R-407 networking gap funded. Without it, run the degraded paths.

## V1 — The digest cites only real resources (SC-001, SC-004)

1. Trigger the digest run (its schedule, or invoke the worker directly).
2. `GET /insights/digest`. Confirm `available: true`, and that `sections[].references[]` is
   non-empty.
3. **The actual test**: for every reference, confirm the id exists — `GET /resources/{id}`,
   `GET /findings`, or `GET /sdas/{id}` as appropriate. Any 404 is an SC-001 failure.
4. Read the digest cold. Confirm you can name the tenant's most urgent governance issue without
   opening another screen (SC-004).
5. **Grounding, proven positively**: seed a fixture whose model output cites an ARN absent from
   the store, re-run, and confirm the digest is *not* displayed and a row appears in
   `GET /insights/rejections` naming that ARN. A validator only ever observed passing is not
   observed working.

**Degraded path (model unreachable)**: confirm `GET /insights/digest` returns `available: false`,
the dashboard renders "not enough data yet", the run appears in `GET /insights/runs` with
`status: failed` and a populated `failureReason`, and every other dashboard surface — inventory,
findings, compliance, cost, utilization — is byte-for-byte unaffected (SC-009).

## V2 — Every open finding carries a suggestion (SC-002, SC-005)

1. With open findings present, trigger the suggester.
2. `GET /findings` then `GET /findings/{findingId}/suggestion` for each. Confirm every open
   finding has `source: ai_generated`, a `suggestionText`, and a `blastRadiusNote`.
3. Confirm the suggestion names **that finding's own resource** — per-finding, not per-class
   (Clarifications 2026-09-05). A suggestion identical across two findings on different resources
   is a failure of FR-011, not a caching win.
4. **Admin-seeded suggestions survive**: seed one via `PUT /findings/{id}/suggestion`, re-run the
   suggester, confirm it still reads `source: admin_seeded` (FR-013).
5. **No execution path** (SC-005): inspect the workbench and confirm no control applies,
   schedules, or executes a fix. Then confirm the API agrees — there is no endpoint that does.
6. **Cost cap** (FR-004, SC-008): set a cap below the open-finding count, re-run, confirm the run
   records `status: truncated`, findings without a suggestion yet show none rather than a
   placeholder, and the next run picks them up.

## V3 — A coverage proposal takes effect without a code change (SC-003) [P2]

1. Ensure an account holds a resource type present in inventory but absent from the coverage
   definitions, **for which an enricher already exists**, or a rule gap over already-collected
   fields. Those are the only two proposable kinds (R-603).
2. Run the advisor. `GET /coverage-proposals` — confirm a `pending` proposal naming the gap and
   the account that revealed it.
3. As a **viewer**, confirm the proposal is visible and `POST .../decision` is refused (FR-016).
4. As an **admin**, accept it. Confirm the response shows `accepted` with `decidedBy`/`decidedAt`.
5. Run a scan. Confirm the change took effect — **with no deployment between steps 4 and 5**
   (SC-003) — and that `appliedAt` is populated.
6. Confirm it applied **tenant-wide**, not only to the evidence account (Clarifications).
7. Reject a second proposal; confirm the next advisor run does not re-raise it (FR-018).

## V4 — Metrics collect without duplicating (FR-019, FR-020) [P2]

1. Run collection against an account with compute and database resources.
2. Confirm measurements land per resource and period.
3. Run it again for the same period. Confirm no duplicate row — the unique index refuses it.
4. Confirm a resource with no available metric is stored with `is_unavailable: true` and a NULL
   value, never `0`.

## V5 — Forecasts are reproducible and backtestable (SC-006) [P2]

1. `GET /forecasts`. Confirm projections for projects with history, and
   `insufficientHistory: true` with a null value for those without.
2. **Reproducibility**: re-run the calculation over the same history and confirm an identical
   figure (SC-006). This is the property that distinguishes a calculation from a model output.
3. Backtest against held-out actuals; confirm MAPE < 15% on test projects.

## V6 — Rightsizing arrives with evidence (FR-023) [P2]

1. `GET /rightsizing`. Confirm each recommendation names a smaller class, carries non-empty
   `evidence`, and an estimated monthly saving.
2. Confirm a high- or variably-utilized resource receives **no** downsizing recommendation.
3. Confirm no control anywhere applies one.

## V7 — Narratives match their charts exactly (SC-007) [P2]

1. Open a cost or forecast page carrying a narrative.
2. Compare every figure in the prose against the chart. Any mismatch is an SC-007 failure.
3. Seed a fixture whose narrative states a figure the calculation did not produce; confirm it is
   **not displayed** (FR-024).

## Teardown

```bash
export AWS_PROFILE=cloudpulse-dev && ops/teardown.sh dev
```

Then the full playbook §0.5.3 sweep, extended for this spec:

```bash
aws bedrock-agent list-agents --query 'length(agentSummaries)'
aws bedrock list-guardrails --query 'length(guardrails)'
aws lambda list-functions --query "length(Functions[?contains(FunctionName,'action-group')])"
aws logs describe-log-groups --query 'logGroups[?retentionInDays==null].logGroupName'
```

The last one is not optional. It is the check that caught spec 005's surviving log group after a
`destroy` that reported complete success.
