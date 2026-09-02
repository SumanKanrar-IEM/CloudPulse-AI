# Quickstart: Cost, Utilization, and Notifications

Validation guide, not a tutorial. Assumes specs 001–004's dev environment is deployed with this
spec's migrations, workers, and routes implemented and deployed on top of it. Each scenario cites
the success criterion it proves. Run in order; later ones assume earlier ones passed.

**Before running V1, V4–V7 live**: read research.md R-511 first. `cost-ingestion-worker` and
`iam-hygiene-worker` both inherit research.md R-407 (governance dashboard's own standing,
twice-declined-to-fund VPC-networking gap) unconditionally — Cost Explorer and IAM have no
VPC PrivateLink support at all, so these two workers cannot reach either API live until that gap
is funded. Unless it has been resolved since this quickstart was written, scope a live run to
V2–V3 (notification, if R-504's SES VERIFY resolves favorably) and V6 (utilization, which makes
no external AWS call at all) — prove V1, V4, V5, and V7 at the mocked-test level only (moto covers
`ce` and `iam`). This is the honest continuation of specs 002/003/004's own outcome on this same
gap, not a new blocker to re-report.

**Before running V2–V3 live**: resolve research.md R-504's VERIFY (does this region's SES support
a VPC interface endpoint reachable from the worker's private subnets) first. If it resolves
unfavorably, V2–V3 are also mocked-test-only until R-407 itself is funded.

**Tear down and run the full cost sweep (playbook §0.5.3) at the end of any session that
deployed** — extended per research.md R-510 to confirm all three new EventBridge Scheduler rules,
all three new Lambda functions, and their CloudWatch log groups are gone.

## Prerequisites

- Specs 001–004's dev environment deployed and reachable, with at least one admin-role user.
- For V1/V4/V5/V7 (if R-407/R-511's gap is resolved by the time this runs): at least one
  verified, scanned account with real spend history and a registered SDA/project.
- For V2/V3 (if R-504 resolves favorably, or R-407 is funded): a resource with a resolvable owner
  email (spec 003's attribution chain) and an SES-verified recipient address (sandbox mode,
  research.md R-510 — the same operational pattern spec 004's own T032 used for Cognito test
  users).

## V1 — Ingested spend reconciles with the cloud provider's own console (SC-001, SC-002)

1. Let `cost-ingestion-worker` run once (its daily schedule, or invoke it directly for a faster
   check).
2. `GET /spend/summary` for the ingested day. Compare the total against the AWS Cost Explorer
   console for the same account/day. Confirm within ±1% (SC-001).
3. Open the cost dashboard. Confirm it reflects the same total, loads within the same 2-second
   budget spec 004's SC-003 already established (SC-002), and that drilling from the org total
   through a project down to its member resources (research.md R-512 — a resource list, not a
   per-resource dollar figure) lands on resources that are genuinely part of that project.

## V2 — A newly-opened finding notifies its owner the same day (SC-003)

1. Open a finding (a tag violation, or drive a budget past its 100% threshold — V5) on a resource
   with a resolvable, SES-verified owner email.
2. Let `notification-worker` run once. Confirm one email arrives, naming the resource and the
   violation, with a working deep link (`GET /findings/{findingId}/notifications` should show one
   `sent` row for `cadence_point = day_0`).
3. Repeat against a resource whose owner email cannot be resolved. Confirm no email arrives and
   the notification row's `outcome` is `withheld_no_owner_email`.

## V3 — Reminders fire on schedule and stop on acknowledge/resolve; escalation flags a stale finding (SC-004)

Use a clock-forwarded test environment or a database-level date manipulation, not a real 2/4-day
wait, for this scenario's day-2/day-4 legs.

1. Leave V2's finding open. Advance to day 2, run `notification-worker`. Confirm a `day_2`
   reminder is `sent`.
2. Acknowledge the finding. Advance to day 4, run `notification-worker`. Confirm the `day_4` row's
   `outcome` is `suppressed_finding_closed`, not `sent`.
3. On a second, unacknowledged finding, advance past day 4 and run `notification-worker`. Confirm
   `GET /findings/{findingId}` shows `escalatedAt` populated (SC-004), and that acknowledging it
   afterward clears `escalatedAt` on the next read.

## V4 — A newly-registered project gets a budget automatically (SC-005)

1. Register a new SDA/project (spec 003's existing endpoint).
2. `GET /budgets` immediately. Confirm a budget exists for it with `amountUsd` set and all four
   `*CrossedAt` fields `null` (SC-005 — "within a day," proven here as "immediately").

## V5 — A budget overrun becomes a finding, visible and notified like any other (SC-006)

1. Push a test project's ingested spend (V1) past its budget's 100% threshold.
2. Run `cost-ingestion-worker`. Confirm `GET /findings?...` returns a new row with
   `kind: "budget_overrun"` and a populated `sda` field (not `resource`), and that
   `GET /budgets` shows `actual100CrossedAt` populated (SC-006).
3. Confirm this finding is notified exactly like V2's (same day-0 email, same cadence).
4. Bring the project's spend back under threshold and re-run the worker. Confirm the finding
   resolves the same way a fixed tag violation does.

## V6 — Utilization matches a hand calculation and drills down in ≤3 clicks (SC-007)

No AWS call involved (research.md R-509) — runnable regardless of R-407/R-511's status.

1. Pick a test account with a known, hand-countable mix of active and stopped/idle resources
   (only counting types where `state` is populated, per R-509's explicit scope).
2. `GET /utilization?accountId=...`. Confirm `percentage` matches `usedCount / provisionedCount`
   computed by hand from the same resource set.
3. On the dashboard, drill from the account-level utilization view to a project to a single
   resource. Confirm the resource-level view is reached in 3 clicks or fewer.

## V7 — IAM hygiene flags only genuinely unused principals (SC-008)

1. In a test account, ensure at least one actively-used IAM role/user/key and at least one
   genuinely unused one (no activity, easy to arrange with a throwaway test role).
2. Run `iam-hygiene-worker` (its weekly schedule, or invoke directly).
3. `GET /iam-hygiene?accountId=...`. Confirm the unused principal appears with evidence, and the
   actively-used one does not appear at all (SC-008 — zero false flags).
