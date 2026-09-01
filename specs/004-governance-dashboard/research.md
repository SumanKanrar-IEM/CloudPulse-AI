# Research: Governance Dashboard

Eight decisions, following specs 1–3's format: Decision / Rationale / Alternatives considered.
R-406 is the cost profile (playbook §0.5.3); R-407 carries forward a standing, already-decided
constraint rather than deciding anything new, per playbook §0.5.5's "don't re-litigate" discipline.

## R-401 — The frontend learns its API and Cognito configuration via a deploy-time injection step, finally wiring up the seam spec 002 built but never finished

**Decision**: A new step in `deploy-dev.yml`/`deploy-prod.yml`, inserted between the existing
"Terraform apply" step and the existing "Publish the frontend" step, writes a small
`<script>window.__CLOUDPULSE_CONFIG__ = {...}</script>` block into the already-built
`frontend/dist/cloudpulse/index.html`, populated from `terraform output` values: `apiBaseUrl`
(from `api_endpoint`, already output today), and three new values — `cognitoDomain`,
`cognitoClientId`, `cognitoRedirectUri` — from two new env-level Terraform outputs added by this
spec (`cognito_client_id`, `cognito_hosted_ui_domain`; the identity module already computes both,
confirmed by reading `infra/modules/identity/outputs.tf` directly — they were simply never
re-exported at the env level). No reordering of the existing "Build the frontend" step: it already
runs before "Terraform apply" today, and the runtime-config seam (`api-config.ts`) was built in
spec 002 specifically so a build-time environment file is never needed — this decision is the
deploy-side half spec 002's own code comment already flagged as unfinished ("Flagged to the user
rather than guessed at, since it needs a CI/CD pipeline decision this session did not make
unilaterally").

**Rationale**: This spec is the first one whose own success criteria (SC-002's live, walkable demo
path) actually depend on the deployed frontend being able to reach the real API and the real
Cognito Hosted UI — specs 002–003 built and live-verified their backends, and built minimal
frontend screens, but never exercised a live-deployed dashboard interaction end-to-end. Leaving
the seam unfinished would silently break every API call from the real CloudFront-hosted app the
moment this spec's live-verification is attempted, for a reason that has nothing to do with this
spec's own code. Fixing it now, in the same spec that first needs it, is more honest than
inheriting an unfixed cross-spec gap.

**Alternatives considered**: A build-time Angular environment file — rejected for the exact reason
spec 002's own comment already gives: the API Gateway URL isn't known until after `terraform
apply`, which runs after the frontend build step in the existing pipeline; reordering the pipeline
to build the frontend last would be a bigger, riskier change than adding one small injection step
that works with the existing order. Proxying the API through CloudFront as a second origin
behavior (same-origin relative paths, no runtime config needed at all) — rejected as materially
larger infrastructure surgery (a new CloudFront behavior, cache-key and CORS implications) for a
problem the existing runtime-config seam already solves with one new deploy step.

## R-402 — Sign-in is Authorization Code + PKCE; tested via route interception, not a live Cognito dependency

**Decision**: The new `sign-in.component.ts` redirects to Cognito Hosted UI's
`/oauth2/authorize` endpoint with a generated PKCE code challenge (S256) and a random `state`
value, both held in memory for the duration of the redirect round-trip (`sessionStorage`, cleared
immediately on use — never `localStorage`). The new `auth.callback.component.ts` (served at
`/auth/callback`, the exact path spec 001's Cognito app client `callback_urls` already points at
— confirmed in `infra/envs/dev/main.tf`, not assumed) validates `state`, exchanges the
authorization code and PKCE verifier for tokens at Cognito's `/oauth2/token` endpoint, calls
`GET /me` with the resulting access token, populates `AuthService`, and navigates to the
`returnTo` query parameter `authGuard` already sets today. Playwright tests exercise this flow by
intercepting the two Cognito network calls (`page.route()` on the authorize redirect and the token
exchange), returning fixture responses shaped like Cognito's real ones — the same pattern
`sdas.spec.ts` already established for intercepting platform API calls, applied to the two new
external calls this flow makes.

**Rationale**: Authorization Code with PKCE is not a style choice here — it is what Cognito
requires for a public client with no secret. `infra/modules/identity/main.tf` already sets
`allowed_oauth_flows = ["code"]` and `generate_secret = false`; the implicit flow (which would not
need PKCE) is not enabled on the app client at all, so there is no simpler flow actually available
to build against. Testing against a real Cognito Hosted UI page in CI was rejected for the same
reason this project's own `e2eMockRole` bypass exists for other screens (spec 003, T034): a
real external IdP dependency in CI is slow, flaky, and requires a real test user's credentials to
live somewhere CI can reach — route interception proves the flow's own logic (state validation,
token exchange, `/me` call, redirect) without that dependency, and is the same tradeoff this
project has already made once.

**Alternatives considered**: Storing tokens in `localStorage` for persistence across a page reload
— rejected: `AuthService`'s existing design is deliberately session-only (a signal populated from
`GET /me`, no persistence, re-derived every session per FR-031a's "the directory is the sole
authority"), and `localStorage` survives a closed tab in a way that widens this app's XSS blast
radius for no requirement this spec states. A real (non-intercepted) Cognito test user for e2e —
rejected on the same grounds `e2eMockRole` was: real IdP interaction in CI is exactly the kind of
external dependency this project has consistently avoided testing against directly.

## R-403 — "Missing owner tag" (FR-010's tag-status filter) and "lacking an attributed owner" (FR-013) are two different, both-real filters, not the same fact under two names

**Decision**: The inventory explorer exposes both as independent filter dimensions on
`GET /resources`: a `tagStatus` parameter (values including a per-rule "missing required tag"
state, driven by whether the resource has an open `Finding` for a given rule — including, but not
limited to, the seeded `owner` tag rule) and a separate `ownerStatus=unattributed` parameter
(driven by whether a `ResourceOwner` row exists for the resource at all). FR-013's own acceptance
bar — "genuinely lacking an attributed owner" — is proven by the second parameter, not the first.

**Rationale**: These are genuinely different facts in the schema tag compliance and ownership
already built, confirmed by reading both mechanisms directly rather than assuming they're the
same thing because both mention "owner": a resource's raw `owner` *tag* is validated by a
tagging *rule* (`Finding` against `rule.key = "owner"`) — a resource can carry a syntactically
fine `owner` tag and still have no `ResourceOwner` row, because attribution is a completely
separate mechanism (a bulk CloudTrail sweep correlating creation/modification events, research.md
R-302), never derived from the tag's own value. Conflating them would mean a resource with a
perfect `owner` tag but no CloudTrail-derived attribution — a real, expected state for any
resource created before the 90-day lookback window, tag compliance and ownership's own Edge
Cases — could never be found by either filter, silently defeating the exact "who do I not know
about" governance question User Story 5 (that spec's) ownership attribution exists to answer.

**Alternatives considered**: A single filter that treats "missing owner tag" as shorthand for
"unattributed," matching the most literal reading of the original backlog phrase — rejected after
checking both mechanisms directly: the literal phrase is genuinely ambiguous between the two real,
independently useful facts, and collapsing them into one loses real filtering capability spec.md's
own FR-012 (the detail panel showing tags *and* owner+evidence as two separate things) already
implies are distinct. Both filters existing costs nothing extra in query complexity — each is one
additional, independent `WHERE`/`JOIN` clause.

## R-404 — Acknowledgment is new orthogonal metadata, not the schema's already-reserved `suppressed` finding status

**Decision**: Finding acknowledgment is stored as two new nullable columns on the existing
`finding` table — `acknowledged_at`, `acknowledged_by` (an `app_user.id` FK) — parallel to the
table's existing `resolved_at`, not as a new or reused `FindingStatus` enum value.
`FindingStatus.SUPPRESSED` (already present in `backend/app/models/enums.py`, added by spec 003's
migration but never used by any spec 003 logic) is left alone, for a future spec to define.

**Rationale**: Checking the actual enum (not assumed from memory — an earlier read of this file
during planning missed the third member on a truncated view, then caught it on a full re-read)
matters here because reusing it would have been the wrong call for a documented reason:
`suppressed` reads as "dismissed, no longer counts" — precisely what FR-017 forbids acknowledgment
from being ("MUST NOT change its open/resolved status and MUST NOT affect any compliance score —
it is a human triage signal, not a resolution"). Tag compliance and ownership's own data-model.md
already documents `suppressed` as "reserved for a later spec, unused here"; nothing about this
spec's scope is that later spec, and claiming it now would either misuse it (make a genuinely
different concept share one enum value) or block whatever future spec `suppressed` was reserved
for from defining its own semantics cleanly.

**Alternatives considered**: A boolean `acknowledged` column with no timestamp/actor — rejected:
FR-016 requires recording who and when, as an auditable action; a bare boolean can't carry that
without a second lookup into the audit log for information the row should hold directly, the same
reasoning `resolved_at`'s own existing shape already reflects.

## R-405 — Scan-history deltas are computed at query time from existing timestamp columns, no new persisted state

**Decision**: `GET /accounts/{accountId}/scans`'s response gains three additional per-scan
integer fields — `added`, `removed`, `changed` — computed at query time from columns
`resource` already has: `added` counts resources whose `first_seen_at` falls within
`[scan.started_at, scan.finished_at]`; `removed` counts resources whose `deleted_at` falls in that
window; `changed` counts resources whose `last_seen_at` falls in that window while `first_seen_at`
predates `scan.started_at` (an existing resource this scan touched again, not a new one). No new
column on `scan`, no new table.

**Rationale**: Account onboarding and discovery already writes exactly the three timestamps this
needs (`first_seen_at`, `last_seen_at`, `deleted_at`) on every resource row, for its own
diffing/deleted-marker purposes; nothing about FR-021's "resulting resource deltas" requires a
second, separately-maintained counter that could drift from what those timestamps already say.
Matches this project's established preference for computing a value fresh from source-of-truth
data over persisting a derived one (tag compliance and ownership's compliance score works the same
way — computed on every `GET`, never stored) — the same reproducibility reasoning Principle IV
already establishes for scores applies equally well to a delta count.

**Alternatives considered**: Persisting delta counts as new columns on `scan` at `finalize_scan`
time — rejected: this would need `finalize_scan` (already a hot, tested integration point per
R-303) to compute and write three more numbers no other part of the pipeline reads, purely to save
one query-time computation this spec's own scale (a handful of scans per account, viewed
occasionally, never in a tight loop) does not need.

## R-406 — Cost profile: this spec adds zero new billable AWS resources

Every prior spec's research.md states a cost profile per playbook §0.5.3; this one is unusually
short because there is genuinely nothing new to price.

| Resource | Dev/prod choice | Reasoning |
|---|---|---|
| New API routes (`resources.py`, `findings.py` extensions) | Deployed on the existing API Lambda | No new Lambda function, no new API Gateway route integration cost beyond what already exists — these are new *paths* on infrastructure this spec does not provision. |
| New schema (`finding_remediation_suggestion`, two columns on `finding`) | Existing Aurora Serverless v2 cluster, `min_acu = 0.5` unchanged | Two small additive pieces; no new cluster, no capacity change. Spec 1's R-003 reasoning still applies unchanged. |
| Frontend (four new feature areas, sign-in/callback flow) | Existing S3 + CloudFront | Same static-hosting bill this project has paid since spec 001 — more files in the same bucket, not a new distribution. |
| Two new Terraform outputs (`cognito_client_id`, `cognito_hosted_ui_domain`) | No resource at all | Re-exporting values from an already-provisioned Cognito user pool costs nothing — Terraform outputs are not billable. |
| Deploy-workflow injection step (R-401) | GitHub Actions, existing `deploy-{dev,prod}.yml` | A few extra seconds of an already-running job; no new workflow, no new runner minutes beyond what deploying this spec's code would already cost regardless. |

**Live-verification discipline (playbook §0.5.3, §0.5.5)**: because this spec adds no new
billable resource, its own live-verification session's teardown-and-sweep is the same generic
playbook §0.5.3 checklist specs 1–3 already run — there is no spec-004-specific addition the way
R-207/R-306 needed one for their own new infrastructure. See R-407 for the one real blocker to
actually running that verification, which this spec does not create and does not resolve.

## R-407 — Standing constraint, not a new decision: this spec's live-verification depends on account registration, which is still blocked

Tag compliance and ownership's T032 (2026-08-30) confirmed — for the second time, following
account onboarding and discovery's own T053 — that `POST /accounts` hangs to Lambda's 30-second
timeout for **both** connection modes, because the API Lambda's VPC has no NAT gateway and no
interface endpoint for STS or the Resource Groups Tagging API, and a VPC-attached Lambda's ENI has
no public IP by AWS's own platform constraint. The user has twice declined to fund a fix (a NAT
instance, a NAT gateway, or several interface endpoints — all priced in tag compliance and
ownership's own tasks.md T032 entry). **This plan does not attempt to resolve that gap** — it is
an infra/cost decision already made twice, not a dashboard-feature decision this spec owns — but
records it here so whoever runs this spec's own live-verification task does not spend a session
rediscovering it a third time. Every P1 screen this spec builds (compliance overview, inventory,
findings) needs *some* real account with real scanned data to show anything beyond empty states;
without that gap resolved, this spec's live-verification can prove, at most, the sign-in flow and
every screen's empty/error states — not a populated dashboard. `tasks.md`'s own live-verification
task should scope itself accordingly rather than presenting this as a new blocker to report to the
user.

## R-408 — Found live, T032: `hosted_ui_domain` was a domain prefix, not a resolvable host — every real sign-in since spec 001 was broken

**What was wrong**: `infra/modules/identity/outputs.tf`'s `hosted_ui_domain` output returned
`aws_cognito_user_pool_domain.this.domain` directly — a Cognito-managed domain's *prefix*
(`cloudpulse-<env>-<account_id>`), not the host a browser can actually reach. Every consumer
(`sign-in.component.ts`'s `window.location.href = https://${config.domain}/oauth2/authorize...`,
`auth.service.ts`'s `signOut`) treated it as a directly-usable host. `SignInComponent.ngOnInit()`
fires that redirect immediately on mount, no click required — so the moment `authGuard` sent an
unauthenticated visitor to `/sign-in`, the browser committed to leaving the document for an
unresolvable host and landed on an error page. This is spec 001's bug (the identity module and the
sign-in component's redirect logic both predate this spec), invisible in every prior
live-verification session across specs 001–003 because none of them completed a real browser
sign-in — T003a already established that no session had even loaded the deployed SPA at all before
this spec fixed that; this was the next layer down, hidden until this spec's T032 got that far.

**How it was found**: not by inspection. Three real Cognito test users were created (one per role,
`admin-create-user`/`admin-set-user-password --permanent`/`admin-add-user-to-group`, matching spec
001 quickstart's own documented procedure) and used to sign in through the actual deployed Hosted
UI in a real browser, per this spec's own T032/quickstart.md V1. The page never rendered. A raw
`curl` against the deployed `index.html` showed a completely healthy response — the config
injection (R-401, and this task's own T032a fix) was correct — which narrowed the fault to
client-side behavior, not the server. Comparing `aws cognito-idp describe-user-pool-domain`'s
output against the value the frontend was actually constructing a URL from surfaced the missing
`.auth.<region>.amazoncognito.com` suffix directly.

**Fix**: at the source, not scattered across consumers — `hosted_ui_domain` now appends
`.auth.${data.aws_region.current.name}.amazoncognito.com` in the identity module itself, via a new
`data "aws_region" "current"` lookup matching the exact pattern `scan`/`governance`/`network`/`api`
modules already use for the same need. Every consumer of the output needed no change; they already
expected a directly-usable host, which is what the contract should have been from the start.
