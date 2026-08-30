# Quickstart: Governance Dashboard

Validation guide, not a tutorial. Assumes specs 001–003's dev environment is deployed with this
spec's migrations, routes, and frontend implemented and deployed on top of it. Each scenario cites
the success criterion it proves. Run in order; later ones assume earlier ones passed.

**Before running V3–V6 live**: read research.md R-407 first. Every P1 screen beyond sign-in needs
at least one connected account with real scanned data to show anything but an empty state, and
account registration is currently blocked by the same standing VPC-networking gap tag compliance
and ownership's own T032 already found and the user has twice declined to fund. Unless that gap
has been resolved since this quickstart was written, scope a live run to V1–V2 (sign-in, empty/
error states) and prove V3–V8 at the mocked-test level only — this is the honest continuation of
specs 002/003's own outcome, not a new blocker to re-report.

**Tear down and run the full cost sweep (playbook §0.5.3) at the end of any session that
deployed** — this spec adds no new billable resource (research.md R-406), so no spec-004-specific
sweep addition is needed beyond the generic checklist.

## Prerequisites

- Specs 001–003's dev environment deployed and reachable.
- An admin-role, an operator-role, and a viewer-role Cognito user (spec 001's quickstart V-steps
  cover creating one of each).
- For V3–V8 (if research.md R-407's gap is resolved by the time this runs): at least one verified,
  scanned account with a known, hand-countable mix of compliant/non-compliant resources, at least
  one resource genuinely lacking an attributed owner, and at least one open finding.

## V1 — Each role sees exactly its permitted surface (SC-001)

1. Sign in as viewer. Confirm the shell's navigation shows compliance overview, inventory,
   findings, and scan history — and confirms no control to acknowledge a finding, seed a
   suggestion, trigger a scan, or reach any admin-only configuration screen (rules, SDAs,
   identity-pattern) is presented as available.
2. Sign in as operator. Confirm the same views, plus: an acknowledge control on findings and a
   trigger-scan control on scan operations are now available; admin-only configuration screens'
   controls remain unavailable.
3. Sign in as admin. Confirm every view and control, including the suggestion-seed control
   (FR-020a) and every admin-only configuration screen, is available.
4. Sign out from any role. Confirm the next page load redirects to sign-in rather than showing
   any previously-visible screen.
5. Attempt to load a dashboard URL directly with no signed-in session. Confirm redirect to
   sign-in, not a flash of governance data.

## V2 — Empty and error states render correctly with zero real data (FR-009, FR-025, Edge Cases)

Runnable with no connected account at all — the honest V-scenario when research.md R-407's gap is
still open.

1. With no connected account, open the compliance overview. Confirm an explicit "not yet
   scanned"/"no accounts" state, not a zero score presented as if it were real, and not an error.
2. Open the inventory explorer. Confirm an explicit "no resources" state, not a blank table that
   looks broken.
3. Open the findings workbench. Confirm an explicit "no findings" state.
4. Temporarily point the frontend's runtime config at an unreachable API URL (or simulate via
   Playwright route interception in CI). Confirm each of the three screens above shows an
   explicit error state with a retry option, not a silently stale or blank screen.

## V3 — Compliance overview matches the API exactly and loads within budget (SC-003, SC-004)

*(Needs a connected, scanned account — see this file's opening note.)*

1. In the test account, manually count total top-level resources, and how many currently have at
   least one open finding.
2. Open the compliance overview. Confirm the overall score, per-account score, and findings-by-
   type/severity breakdown exactly match `GET /accounts/{id}/compliance-score` and `GET
   /findings`'s own responses for the same account — not a dashboard-computed approximation.
3. With the account scaled to (or seeded at) 5,000 resources, confirm the overview finishes
   loading within 2 seconds.

## V4 — Inventory filters return exactly the correct set, including "missing owner tag" and unattributed owner (SC-005)

*(Needs a connected, scanned account — see this file's opening note.)*

1. Filter the inventory by account, then add service, region, SDA, and `tagStatus` filters one at
   a time. Confirm each additional filter narrows the result set to exactly the resources
   matching every applied filter, verified against a manual count.
2. Apply `tagStatus=missing:owner` (research.md R-403: the tag-compliance reading of "missing
   owner tag"). Confirm the result set is exactly the resources with an open finding against the
   seeded `owner` rule.
3. Apply `ownerStatus=unattributed` (research.md R-403: the separate, attribution reading).
   Confirm the result set is exactly the resources with no `ResourceOwner` row — and confirm it
   differs from step 2's result set where the two facts genuinely diverge (a resource with a
   valid `owner` tag but no CloudTrail-derived attribution, or vice versa).
4. Open one resource's detail panel. Confirm its tags, owner + evidence (or "unattributed"),
   findings, and enrichment detail each match what `GET /resources/{resourceId}`,
   `GET /resources/{resourceId}/owner`, and `GET /findings?resourceId=...` independently report.

## V5 — Acknowledging a finding is immediate and never affects scoring (SC-006, FR-017)

*(Needs a connected, scanned account with at least one open finding.)*

1. As admin or operator, note the account's current compliance score, then acknowledge one open
   finding from the workbench. Confirm the acknowledged state appears in the list within the same
   interaction — no manual page refresh.
2. Re-check the account's compliance score. Confirm it is unchanged by the acknowledgment.
3. As admin or operator, attempt to acknowledge the same finding again (or trigger two
   near-simultaneous acknowledgments). Confirm no error and no duplicate acknowledgment record
   (`GET /findings/{id}/acknowledge`'s effect, or a direct row count, shows exactly one).
4. As viewer, confirm the finding's acknowledged state is visible but no control to acknowledge
   (or un-acknowledge) it is available.

## V6 — A finding's suggestion displays correctly, real or admin-seeded (SC-007, FR-018–FR-020a)

*(Needs a connected, scanned account with at least one open finding.)*

1. Open a finding with no suggestion yet. Confirm the explicit "no suggestion available" state —
   not an error, a blank space, or a perpetual loading indicator.
2. As admin, attach a demo/QA test suggestion and blast-radius note to that finding (FR-020a).
   Confirm it now displays inline exactly as FR-018 describes, visibly marked as test data.
3. As operator or viewer, confirm the seeded suggestion is visible but no control to attach or
   edit one is available (FR-028a).

## V7 — Full role matrix across every new surface (SC-001, cross-cutting)

Repeat the write actions this spec adds — acknowledge, seed a suggestion, trigger a scan — against
all three roles, confirming: admin succeeds at every one; operator succeeds at acknowledge and
trigger-scan but is refused at seed-suggestion; viewer is refused at all three, with every refusal
returning the platform's standard 403 envelope, not a silently disabled control that never calls
the API at all (the API is the authority, per `authGuard`'s own "usability, not security" doctrine
this project has held since spec 002).

## V8 — On-demand scan status updates without a manual reload (SC-008, P2)

*(Needs a connected account — connection itself is what research.md R-407 blocks; if that gap is
open, this scenario is provable only against a LocalStack/mocked scan-trigger path in CI, not
live, matching V3–V6's own honest scoping.)*

1. As admin or operator, trigger an on-demand scan from the scan-operations screen.
2. Confirm the status shown updates (via polling, research.md's Assumptions) through to a final
   state (`succeeded`/`partial`/`failed`) without a manual page reload.
3. Once finished, confirm the scan's history entry shows `added`/`removed`/`changed` counts
   (research.md R-405) matching a manual count of what actually changed in the account.
