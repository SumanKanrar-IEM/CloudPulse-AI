# Phase 0 Research: Platform Foundation

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-22

The technology direction was settled up front, so most of the stack was not open for research.
What remained were the seams where that direction meets a specific requirement in the spec and the
obvious approach does not work. Twelve decisions are recorded below; R-002, R-004, and R-007 are
the three that materially shape the architecture.

Items marked **VERIFY** rest on service or tool behaviour that should be confirmed against current
documentation during implementation rather than trusted from this document.

---

## R-001 — Terraform state backend and the bootstrap chicken-and-egg

**Decision**: A small `infra/bootstrap/` root module, applied once per account by a human with
console-level credentials, creates the S3 state bucket (versioned, encrypted, public access
blocked), the DynamoDB lock table, and the GitHub OIDC provider plus deploy role. Every other root
module uses that backend and is applied only by GitHub Actions through OIDC. The bootstrap step is
documented in `ops/runbooks/` as an explicit prerequisite of FR-006.

**Rationale**: FR-001 requires provisioning from versioned definitions with no manual console
configuration, but a remote state backend cannot store its own creation, and an OIDC trust
relationship cannot be created by a workflow that does not yet have a role to assume. Naming this
one bounded manual step honestly is better than pretending it does not exist. It is definitions in
the repository — it is simply applied by a person once, and never again.

**Alternatives considered**: Local state committed to the repo — rejected, state contains resource
identifiers and would conflict constantly across six people. Terraform Cloud — rejected under
Principle II, non-AWS runtime dependency for engineering tooling. A long-lived IAM user for
bootstrap — rejected outright under Principle III.

**Impacts**: FR-001, FR-006, SC-001. Adds roughly 10 minutes to the 60-minute budget.

---

## R-002 — Running Alembic migrations against a VPC-private Aurora cluster

**Decision**: A dedicated **migration Lambda** (`handlers/migrate_handler.py`) packaged with the
Alembic environment and placed in the same private subnets as the cluster. `deploy-dev.yml` and
`deploy-prod.yml` invoke it synchronously and fail the deployment on a non-zero result, before the
API Lambda's alias is shifted to the new version.

**Rationale**: FR-016 requires migrations to be applied before the new service version serves
traffic. Aurora sits in private subnets with no public endpoint; a GitHub-hosted runner is outside
the VPC and cannot reach it. A Lambda in the VPC can, reuses the same execution-role-plus-Secrets-
Manager credential path as the API (Principle III — no database password ever reaches the runner),
and its invocation result gives the pipeline a clean pass/fail. It also runs identically in dev and
prod with no second code path.

**Alternatives considered**: Publicly exposing Aurora and running Alembic on the runner — rejected,
it puts the governance store on the internet and requires a database credential in a GitHub secret,
violating Principle III. A self-hosted runner inside the VPC — rejected as disproportionate
infrastructure for a two-week build. RDS Data API — genuinely attractive since it removes the VPC
problem entirely, but Alembic and SQLAlchemy do not target it without an additional dialect
adapter, adding a dependency and a divergence between test and production access paths. **VERIFY**
whether Data API support for Aurora Serverless v2 PostgreSQL has matured enough to reconsider. A
migration step inside the API Lambda's init — rejected, it makes every cold start a migration race
between concurrent executions.

**Impacts**: FR-016, FR-020, FR-021, SC-005, SC-007. This is the single largest piece of
infrastructure this spec adds beyond the obvious.

---

## R-003 — Lambda-to-Aurora connection handling

**Decision**: RDS Proxy in front of the cluster, with the API Lambda holding a short-lived
SQLAlchemy engine configured with `NullPool`. Database credentials are read from Secrets Manager by
the execution role and cached in the Lambda execution context.

**Rationale**: Lambda concurrency multiplies raw connections, and Aurora Serverless v2 at a low
minimum ACU has a modest connection ceiling. RDS Proxy pools on the far side of the boundary, which
is the standard remedy. `NullPool` prevents SQLAlchemy from holding connections across invocations,
where a frozen execution context would otherwise strand them.

**Alternatives considered**: A module-level engine with SQLAlchemy's default pool — rejected,
frozen contexts leak connections and the failure mode (intermittent exhaustion under demo load) is
exactly the kind that surfaces at the worst moment. No proxy at demo scale — defensible for ten
users and worth reconsidering if RDS Proxy's cost proves material; recorded here as the fallback
simplification, not the default.

**Impacts**: FR-041, FR-042, and the p95 target in Technical Context.

---

## R-004 — Enforcing "exactly one role" against Cognito's multi-valued group claim

**Decision**: Two layers. A **pre-token-generation Lambda** on the Cognito user pool inspects
`cognito:groups`; when it contains exactly one of the three mapped groups it stamps a single custom
claim, and when it contains zero or more than one it stamps none. The FastAPI `require_role`
dependency then independently re-derives the role from the raw group claim and refuses the request
if it is not exactly one — it never trusts the custom claim alone.

**Rationale**: FR-032 requires exactly one role and FR-032a requires that zero groups and two
groups both be *refused* rather than resolved. Cognito's group claim is an array and the API
Gateway JWT authorizer validates signature, issuer, audience, and expiry — it does not evaluate
claim cardinality, so the authorizer alone cannot enforce FR-032a. **VERIFY** the exact claim name
and the pre-token-generation trigger's ability to add claims under the current Cognito version. The
second, in-application check exists because a single-layer control that silently picks the first
group is precisely the privilege-escalation bug FR-032a was written to prevent.

**Alternatives considered**: A Lambda authorizer instead of the JWT authorizer — workable and gives
one place to enforce cardinality, but adds an invocation to every request's latency and gives up
API Gateway's built-in JWT caching. Enforcing only in the application — simpler, but leaves an
inconsistent claim in a token that other consumers might later trust. Enforcing only in the
pre-token Lambda — rejected, an existing token issued before a group change would keep working
until expiry with no server-side re-check.

**Impacts**: FR-031a, FR-032, FR-032a, FR-034, SC-008. Directly satisfies the "no group / two
groups" edge cases.

---

## R-005 — Role re-derivation within the one-hour bound

**Decision**: Cognito access and ID token lifetime set to 1 hour, refresh token to 8 hours. The
role is re-derived on every token refresh by the pre-token-generation Lambda and re-validated on
every request by `require_role`.

**Rationale**: FR-038 requires a directory group change to take effect within one bounded interval
without action inside the platform, and FR-038a requires access to end within that same interval.
A 1-hour access token makes the worst-case propagation delay exactly the 1 hour the spec's
Assumptions section commits to, and SC-013 measures precisely that. The 8-hour refresh token keeps
a working day from requiring repeated sign-ins.

**Alternatives considered**: 24-hour tokens — rejected, breaks FR-038's bound outright. 15-minute
tokens with silent refresh — tighter, but adds refresh complexity in the SPA for a guarantee the
spec does not ask for.

**Impacts**: FR-036, FR-038, FR-038a, SC-013.

---

## R-006 — First-administrator bootstrap

**Decision**: The three Cognito groups are created by Terraform from a `map` variable in
`infra/envs/*/terraform.tfvars` (satisfying FR-039a, mapping as data). The first admin is added to
the admin group by a human in the Cognito console or by CLI, documented as a runbook step. No
seeded user, no break-glass credential, and no in-platform bootstrap endpoint exists.

**Rationale**: FR-039 requires exactly this — the act happens in the identity provider, not the
platform — and explicitly forbids a bootstrap path in the application. The signed-in-but-
unauthorised state that a fresh environment presents until this step is done is the spec's stated
expected behaviour, not a defect.

**Alternatives considered**: Terraform-managed group membership for named individuals — tempting
and fully declarative, but it puts personnel records into version control and makes offboarding a
pull request. Rejected. A one-time bootstrap endpoint disabled after first use — explicitly
prohibited by FR-039.

**Impacts**: FR-039, FR-039a, and the "first administrator" edge case.

---

## R-007 — Integration testing without LocalStack coverage for Cognito and Aurora

**Decision**: Split the strategy by dependency rather than forcing one tool to cover everything.

| Dependency | Test approach | Tier |
|---|---|---|
| PostgreSQL / Alembic | **Testcontainers PostgreSQL 16** — real engine, real migrations | integration |
| S3, SQS, EventBridge, Step Functions | **LocalStack** (community-supported services) | integration |
| Arbitrary AWS API calls in unit tests | **moto** | unit |
| Cognito JWT verification | **Locally-generated RSA keypair** signing test tokens against a stub JWKS endpoint | integration |
| API Gateway / CloudFront | Not simulated — exercised by Playwright against the deployed dev environment | E2E |

**Rationale**: Principle VI requires integration tests with mocked AWS for cloud-touching code, and
FR-010 requires unit tests to run with no real credentials. LocalStack's free tier does not cover
Cognito or RDS/Aurora — **VERIFY** current tier coverage before implementation, as this is the
single most likely fact in this document to have changed. Running migrations against a real
PostgreSQL container is strictly better than any emulation anyway, since FR-026 demands migrations
apply cleanly to a populated store and only a real engine proves that. Signing our own JWTs tests
the code we actually wrote — claim extraction and cardinality enforcement — rather than testing
Cognito, which is AWS's to get right.

**Alternatives considered**: LocalStack Pro — rejected, a paid third-party dependency in the merge
path for a two-week build. Mocking the database layer entirely — rejected, it would leave FR-026
and SC-007 untested, and those are load-bearing for five downstream specs. Testing against a shared
real dev environment — rejected, it makes CI results depend on shared mutable state and breaks
under concurrent work.

**Impacts**: FR-010, FR-026, Principle VI, SC-007.

---

## R-008 — Enforcing the additive-only contract rule

**Decision**: `oasdiff breaking` in `ci.yml`, comparing the OpenAPI document generated from the
pull request's FastAPI app against the copy on `pods/pod73`. The document is generated during CI —
never hand-written — and a separate step regenerates the Angular client and fails on any diff.

**Rationale**: FR-048b requires CI to fail on removed or renamed fields, removed endpoints,
newly-required parameters, and narrowed types. `oasdiff` classifies exactly this set. Generating
rather than committing the schema means it cannot drift from the Pydantic models, which is what
makes it a real contract under Principle V rather than documentation. **VERIFY** oasdiff's
classification of each of FR-048b's four cases and add explicit fixture tests for any it does not
flag by default.

**Alternatives considered**: Committing `openapi.yaml` and reviewing diffs by eye — rejected,
FR-048b requires an automated gate. `openapi-diff` alternatives — equivalent; `oasdiff` chosen for
its explicit breaking/non-breaking classification and simple exit codes.

**Impacts**: FR-048, FR-048a, FR-048b, FR-048c, SC-003.

---

## R-009 — Accessibility gate

**Decision**: `@angular-eslint`'s template accessibility rules run inside the frontend lint step and
fail the pull request. `axe-core` assertions run inside the Playwright E2E suite against the
rendered shell. The keyboard-operability and focus-visibility halves of FR-047a stay a reviewer's
responsibility, as FR-047b explicitly states.

**Rationale**: FR-047b requires automated linting in the frontend build and, unusually, requires
the plan not to overclaim: automated rules catch missing labels, roles, and alt text but cannot
judge whether a flow is keyboard-operable. Splitting static rules from rendered axe checks covers
meaningfully more than either alone.

**Alternatives considered**: Playwright + axe only — rejected, catches nothing until an E2E test
exists for a screen. Lint only — rejected, misses everything about the rendered result. Pa11y CI —
equivalent capability, extra tool for no gain over axe-in-Playwright.

**Impacts**: FR-009, FR-047a, FR-047b, SC-015.

---

## R-010 — Prod deletion protection and the teardown refusal

**Decision (corrected 2026-08-22 — see the note below)**: **Two** independent layers, not three.
Aurora `deletion_protection = true` and `skip_final_snapshot = false` in prod, and an `ops/`
teardown script that reads the target workspace and exits non-zero if it is `prod`, before
invoking anything.

> **Correction (T130).** This decision originally specified three layers, the middle one being
> Terraform `lifecycle { prevent_destroy = true }`. **That layer is not implementable as
> specified.** Terraform requires `prevent_destroy` to be a literal — it cannot reference a
> variable — so it cannot be made conditional on `var.environment`. FR-002 mandates one shared
> module set for dev and prod, so enabling it would also block the routine dev teardown that
> FR-005 explicitly permits.
>
> The remaining two layers hold, and the lost one was the weakest of the three anyway: it fails
> partway through a plan rather than up front, whereas the "teardown aimed at prod" edge case
> requires refusal *before anything is touched* — which only the script guard provides.
>
> Recorded here rather than worked around, per Principle I: when code and spec disagree, the spec
> is corrected first.

**Rationale**: FR-005a requires that the routine teardown path refuse to act on prod and that
destroying prod need a deliberate out-of-band step. The "teardown aimed at prod" edge case
specifically requires refusal *before* anything is touched, which only the script-level guard
provides — `prevent_destroy` fails partway through a plan, and `deletion_protection` is the last
line rather than the first. Defence in depth is warranted because the failure is unrecoverable.

**Alternatives considered**: `deletion_protection` alone — rejected, it protects the cluster but
lets Terraform destroy the surrounding stack. Duplicating the database module into dev and prod
variants purely to allow a literal `prevent_destroy` — rejected, it violates FR-002's single
shared module set and would let the two environments drift, which is a larger risk than the
protection is worth. IAM denial of delete actions for the deploy role —
attractive, but the same role must be able to replace resources during normal deployment, so the
policy cannot cleanly distinguish the two.

**Impacts**: FR-005, FR-005a, SC-002.

---

## R-011 — Retention configuration

**Decision**: Retention is set declaratively in Terraform, per data class, and never by hand.

| Data | Mechanism | Value | Requirement |
|---|---|---|---|
| Structured logs | CloudWatch log group `retention_in_days` | 30 | FR-046a |
| Prod backups | Aurora `backup_retention_period` | 7 | FR-005b |
| Audit events | No expiry, no lifecycle rule, no purge job | indefinite | FR-029a |
| Raw scan snapshots | S3 lifecycle (bucket provisioned here, policy owned by spec 2) | deferred | — |

**Rationale**: The clarification session fixed all three values. Expressing them as Terraform
attributes rather than operational settings makes SC-014 verifiable by inspecting the environment,
which is exactly how SC-014 is worded. Audit events get no lifecycle rule at all — FR-029a demands
that no retention setting exist that could remove them, so the correct implementation is the
absence of a mechanism, and a reviewer should treat any appearance of one as a defect.

**Alternatives considered**: Application-level purge jobs — rejected, more code and more ways to
delete something that must never be deleted.

**Impacts**: FR-005b, FR-029a, FR-046a, SC-014.

---

## R-012 — Log redaction and correlation identifiers

**Decision**: AWS Lambda Powertools `Logger` with a custom formatter carrying a redaction
denylist, injected via middleware alongside a correlation identifier. Inbound correlation
identifiers are accepted only if they match a strict UUID pattern; anything else is discarded and
a fresh one generated. The identifier is echoed in every response, success and error alike.

**Rationale**: FR-044 requires a correlation identifier in the response and every log line, FR-046
forbids credentials, secrets, session tokens, and raw customer tag values in logs, and the
"correlation identifier absent" edge case requires that a caller-supplied value never be logged
unvalidated — a caller-controlled string in a log field is a log-injection vector. Powertools gives
structured JSON and correlation propagation without hand-rolling either.

**Alternatives considered**: Standard library `logging` with a JSON formatter — workable but
reimplements what Powertools already provides, and Powertools is already in the stated direction.
Trusting inbound correlation identifiers — rejected on the edge case above.

**Impacts**: FR-043, FR-044, FR-045, FR-046, SC-009, SC-010.

---

## VERIFY outcomes (T123, resolved 2026-08-22)

Three of the four were settled during implementation. One was not reached and is recorded honestly
as still open rather than quietly dropped.

| # | Item | Outcome |
|---|---|---|
| R-007 | LocalStack free-tier coverage for Cognito and RDS | **Sidestepped, not tested.** The split strategy was implemented as designed and needs LocalStack for neither database nor identity: Testcontainers PostgreSQL 16 runs the migrations, and Cognito is covered by locally-signed JWTs plus claim-shape tests. 52 integration tests pass without LocalStack being involved at all. The dependency is declared for the S3/SQS/EventBridge tests specs 002–005 will add; its tier coverage should be confirmed then. |
| R-002 | RDS Data API maturity for Aurora Serverless v2 with SQLAlchemy 2 | **Not reconsidered — the migration Lambda shipped.** It works, is tested, and now also carries deployment recording (Phase 8), which faces the identical VPC constraint. Revisiting Data API would now mean unpicking two callers, so the case for it is weaker than at planning time, not stronger. |
| R-004 | Cognito pre-token-generation trigger claim behaviour and exact claim naming | **Resolved by not depending on it.** The trigger is implemented and wired, but `app/core/security.py` re-derives the role from the raw `cognito:groups` array on every request and never trusts the stamped claim. A dedicated test asserts both layers agree for every case. If the trigger's behaviour differs from expectation in a live pool, FR-032a still holds — which was the point of the two-layer design. |
| R-008 | `oasdiff` classification of all four FR-048b breaking-change categories | **STILL OPEN.** `oasdiff` is wired into `ci.yml` but has never run — that needs a pull request against the trunk (T034). The four categories must be confirmed against fixture 06 before the gate can be trusted. Until then FR-048b is enforced in intent only. |

**One item genuinely outstanding: R-008.** It is bundled into T034, which needs repository access.

## Original open items

1. **R-007** — LocalStack free-tier coverage for Cognito and RDS. Highest-risk assumption here; if
   coverage has expanded, the split strategy simplifies but remains correct.
2. **R-002** — RDS Data API maturity for Aurora Serverless v2 PostgreSQL with SQLAlchemy 2. If
   viable, the migration Lambda could be retired and the VPC constraint disappears.
3. **R-004** — Cognito pre-token-generation trigger claim behaviour and exact claim naming.
4. **R-008** — `oasdiff` classification of all four breaking-change categories in FR-048b.
