# Quickstart: Account Onboarding and Discovery

Validation guide, not a tutorial. Assumes spec 1's dev environment is deployed (or freshly
redeployed — see playbook §0.5.3/§0.5.5: flip `DEV_AUTO_DEPLOY` to `true` first, or dispatch
`Deploy dev` manually) and this spec's migrations/routes/scan orchestration are implemented and
deployed on top of it. Each scenario cites the success criterion it proves. Run in order; later
ones assume earlier ones passed. **Tear down and run the full cost sweep (playbook §0.5.3) at the
end of the session, not just at the end of the whole spec** — this spec provisions a Step
Functions state machine and scan-worker Lambdas beyond spec 1's baseline.

## Prerequisites

- Spec 1's dev environment deployed and reachable (`curl .../health` returns `healthy`).
- An admin-role Cognito user (spec 1's quickstart V-steps cover creating one).
- A second, separate AWS account available for cross-account verification (research.md R-208) —
  distinct from the account CloudPulse AI's own compute runs in.

## V1 — Same-account registration under budget (SC-001)

1. As admin, `POST /accounts` with `connectionMode: local`.
2. Time from request to `status: verified` in the response. Expect **under 5 minutes** — for
   same-account mode this should be seconds, not minutes, since no cross-account template
   deployment is on the critical path.

## V2 — Cross-account registration under budget, and denial without the ExternalId (SC-001, SC-004)

1. Deploy the platform-provided cross-account template into the second AWS account, supplying the
   platform-generated ExternalId shown by the registration flow (FR-003a — this value must come
   *from the platform*, never typed in by hand).
2. `POST /accounts` with `connectionMode: assume_role`, the resulting role ARN, and at least one
   region. Time to `status: verified` — under 5 minutes, excluding step 1's template deployment
   time (SC-001 explicitly excludes it).
3. Separately, deploy a second copy of the template with a **wrong** ExternalId (or none), attempt
   registration against it, and confirm it is refused and never reaches `verified` — 100% of such
   attempts, per SC-004. Repeat with an entirely fabricated role ARN and confirm the same.

## V3 — Whole-account discovery, including untagged resources (SC-002)

1. In the verified account, note its actual resource count via the AWS console or CLI as a manual
   baseline (a handful of resources across at least 3 different services, at least one untagged).
2. Trigger a scan (`POST /accounts/{id}/scans` as operator, or wait for the daily schedule).
3. Compare inventory (`GET /accounts/{id}` plus the resource listing) against the manual baseline.
   Expect **>95% discovered**, including the untagged resource, and confirm at least one resource
   type outside the six P1 enrichment types (FR-019) still appears with full identity fields even
   without enrichment detail (FR-016/FR-017).

## V4 — Deletion reflected on the next scan (SC-003)

1. Delete one resource directly in AWS (one already present in inventory from V3).
2. Trigger another scan.
3. Confirm that resource is now marked deleted in inventory (not removed from the record — its
   row/entry still exists, flagged) with no manual step beyond triggering the scan itself.

## V5 — Coverage-as-data takes effect with no deployment (SC-005)

1. Note the current enrichment detail captured for a P1 resource type (e.g. EC2 instance type).
2. Edit the coverage definition file (research.md R-203) to add or change one field it captures,
   and merge that change through the normal PR flow (no application code touched).
3. Trigger a new scan and confirm the changed capture appears in that resource's `detail` — with
   zero code changes and zero redeployment of the API Lambda itself (only the coverage-data file
   changed).

## V6 — A partial scan failure doesn't over-delete (SC-006)

1. With multiple regions configured on one account, force one region's discovery to fail
   mid-scan (e.g. temporarily narrow the scanner role's permissions for that region only, or use
   a fault-injection hook if implemented).
2. Confirm the scan completes with `status: partial`, resources from the succeeding region(s) are
   recorded normally, and **no resource in the failed region is marked deleted** — its deleted
   markers must be exactly what they were before this scan ran.
3. Restore the role's permissions and confirm the next scan returns to `status: succeeded` and
   catches up that region normally.

## V7 — Concurrent accounts don't interleave (SC-007)

1. With two verified accounts, trigger scans of both at close to the same moment (two near-
   simultaneous on-demand triggers, or wait for both to be due on the daily schedule together).
2. Confirm both complete with correct, non-cross-contaminated results — no resource from account A
   appears under account B's inventory or vice versa, and both scans' `resource_count` matches
   each account's own actual resource count independently.

## V8 — Deactivate/reactivate round-trip (SC-008)

1. As admin, `POST /accounts/{id}/deactivate` on a verified account with existing scan history.
2. Confirm: the accounts view still shows it (status `disabled`), its historical resources/scans/
   findings remain fully browsable, and it is **not** included in the next scheduled scan cycle.
3. As operator, attempt `POST /accounts/{id}/scans` against it — expect refusal (FR-026a still
   requires an active account, deactivation supersedes operator's normal trigger right).
4. As admin, `POST /accounts/{id}/reactivate`. Confirm it resumes normal scanning from the next
   cycle with no re-registration step.

## V9 — Role matrix (SC-009)

Exercise the full cell matrix and confirm each gives the expected allow/refuse — mirroring spec
1's SC-008 role-matrix pattern:

| Action | Admin | Operator | Viewer |
|---|---|---|---|
| View accounts list | 200 | 200 | 200 |
| Register account | 201 | 403 | 403 |
| Deactivate / reactivate | 200 | 403 | 403 |
| Trigger on-demand scan | 403 | 202 | 403 |

The two 403 cells for admin and viewer on "trigger on-demand scan" are the ones most likely to be
implemented wrong — a naive "admin can do everything" shortcut would pass every other cell in this
table while silently failing this one. Verify it explicitly, not by inference from the others
passing (research.md R-205's non-hierarchical-roles point, made concrete).

## Teardown

Full teardown and cost sweep per playbook §0.5.3, plus this spec's own additions (research.md
R-207/R-208): confirm the second AWS account's cross-account role and ExternalId secret are also
removed, not just the primary account's resources, and confirm
`aws stepfunctions list-state-machines` returns none for this environment before ending the
session.
