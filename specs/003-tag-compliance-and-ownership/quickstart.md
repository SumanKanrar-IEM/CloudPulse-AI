# Quickstart: Tag Compliance and Ownership

Validation guide, not a tutorial. Assumes spec 002's dev environment is deployed with at least one
verified, scanned account (spec 002's own quickstart V1–V3), and this spec's migrations, routes,
and governance workers are implemented and deployed on top of it. Each scenario cites the success
criterion it proves. Run in order; later ones assume earlier ones passed. **Tear down and run the
full cost sweep (playbook §0.5.3) at the end of the session** — this spec provisions two SQS queues
and two Lambda workers beyond spec 002's baseline (research.md R-306).

## Prerequisites

- Spec 002's dev environment deployed and reachable, with at least one verified account that has
  completed at least one scan.
- An admin-role Cognito user (spec 001's quickstart V-steps cover creating one).
- In the connected test account: at least one resource with a missing required tag, one with an
  invalid tag value, one fully compliant resource, and one resource created directly through the
  AWS console within the last 90 days (for ownership attribution — V4) plus one created through
  infrastructure-as-code with at least 3 modifications by a known person afterward (for the
  fallback chain — V5).

## V1 — A rule edit changes findings on the next scan, never mid-scan (SC-001)

1. `GET /rules` as any role, confirm the five seed rules (`project_name`, `owner`, `project_id`,
   `created_by` required; `environment` recognized, not required) already exist.
2. As admin, `PATCH /rules/project_name` to add an `allowedValues` constraint that a resource's
   current `project_name` tag value violates.
3. Trigger a scan (`POST /accounts/{id}/scans` as operator) and, **before it completes**, confirm
   via `GET /findings` that no new finding has appeared yet for the in-progress scan's resources.
4. After the scan completes, confirm the finding now exists — the edit took effect starting with
   this scan, not retroactively and not mid-scan.

## V2 — A fixed tag auto-closes its finding (SC-002)

1. Starting from V1's now-open finding, fix the offending tag directly in AWS.
2. Trigger another scan.
3. Confirm via `GET /findings?resourceId=...&status=open` that the finding no longer appears
   there, and `GET /findings?resourceId=...&status=resolved` shows it with a `resolvedAt`
   timestamp — with no manual action taken beyond triggering the scan.

## V3 — Compliance score matches a hand count (SC-003)

1. In the test account, manually count: total top-level resources, and how many currently have at
   least one open finding.
2. `GET /accounts/{id}/compliance-score`. Confirm `compliantCount`, `totalCount`, and `score`
   exactly match the manual tally — `compliantCount = totalCount - (resources with ≥1 open
   finding)`.
3. Register one SDA (`POST /sdas`) whose tag-value mapping matches a known subset of the account's
   resources, trigger a scan so matching takes effect, then `GET /sdas/{id}/compliance-score` and
   confirm it reflects only that subset, matching a separate hand count restricted to those
   resources.

## V4 — Direct creator attribution for a console-created resource (SC-004)

1. Note the identity of whoever created the console-created test resource from Prerequisites.
2. Trigger a scan (this enqueues the ownership-attribution worker — research.md R-303; allow a few
   seconds for the SQS-driven worker to process before checking).
3. `GET /resources/{id}/owner`. Confirm `ownerEmail` (or the raw identity, if email resolution
   hasn't run — P2) matches the actual creator, `confidence` is `high`, and `evidence.kind` is
   `direct` with a populated `cloudtrailEventId`.

## V5 — Fallback attribution for an IaC-created resource (SC-005)

1. Using the IaC-created test resource from Prerequisites (created by an automation/pipeline
   identity, modified at least 3 times afterward by a known person).
2. Trigger a scan, allow the ownership-attribution worker to process.
3. `GET /resources/{id}/owner`. Confirm the owner is the human modifier (not the automation
   identity), `confidence` is lower than V4's (`medium` or `low`), and `evidence.kind` is
   `fallback`.
4. Separately, confirm a resource created by automation with **fewer than 3** modifications by any
   single human returns a null `ownerEmail`/`confidence` (queued unattributed, not a guessed
   owner below the threshold).

## V6 — "No SDA" bucket stays visible and reclassifies on registration (SC-006, SC-007)

1. Before registering any SDA whose mapping would match it, confirm a specific resource appears in
   `GET /sdas/unmatched-resources`.
2. Register an SDA whose mapping matches that resource, trigger a scan.
3. Confirm the resource no longer appears in `GET /sdas/unmatched-resources` and does appear when
   listing that SDA's resources — reclassified by the scan that just ran, no separate trigger
   needed.
4. Attempt to register a second SDA whose mapping overlaps the first (Acceptance Scenario US2.4).
   Confirm `POST /sdas` returns 409, not a silently-accepted ambiguous mapping.

## V7 — Rules and SDAs are admin-only to write, open to every role to read (role matrix)

| Action | Admin | Operator | Viewer |
|---|---|---|---|
| View rules / SDAs / findings / scores / ownership | 200 | 200 | 200 |
| Create/edit a rule | 201/200 | 403 | 403 |
| Register/edit an SDA | 201/200 | 403 | 403 |
| Set the owner-identity pattern or an override (P2) | 200 | 403 | 403 |

Verify every cell explicitly (FR-029/FR-030) — the same discipline spec 002's V9 established for
its own role matrix.

## V8 — A rule edit doesn't orphan an already-open finding (research.md R-301)

1. With a finding already open against a rule's version 1 (from V1), edit that same rule again
   (`PATCH /rules/{key}`), producing version 3 for that key.
2. Trigger a scan. Confirm `GET /findings?resourceId=...` shows the **same finding id** as before
   (not a new one), now reporting `ruleVersion: 3` — proving the finding followed the rule's key
   across two edits rather than being orphaned against a superseded version or duplicated.

## Teardown

Full teardown and cost sweep per playbook §0.5.3, extended per research.md R-306: confirm
`aws sqs list-queues` returns neither `compliance-validation` nor `ownership-attribution` (nor
their DLQs), and confirm the two new Lambda workers' CloudWatch log groups are gone or, if
retained deliberately, have a retention policy set — not left with `retentionInDays: null`.
