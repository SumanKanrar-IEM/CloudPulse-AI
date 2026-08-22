# AI Workflow & Agentic Development Journal — CloudPulse AI

> **Purpose:** Evidence of AI-native engineering practices for the hackathon assessment.
> Documents how the AWS-native CloudPulse AI MVP is built by a **solo developer driving
> Claude Code as the GitHub Spec Kit engine**, with GitHub as the delivery platform
> (Actions, Issues, agentic workflows) — covering spec-driven development, architectural
> discipline, engineering standards, and human–AI collaboration ("a POD of one human plus
> AI agents").
> **Rule:** every speckit phase gets its entry appended the same day it runs.

## 0. Project Initialization & Scope Definition

- **Tools:** GitHub Spec Kit (`specify init`, Copilot integration, Python scripts), AI-assisted document analysis.
- **What we did:**
  - Initialized the repo with GitHub Spec Kit for GitHub Copilot (`.github/skills/speckit-*`, `.specify/` scaffolding); repo pushed to `SumanKanrar-IEM/CloudPulse-AI`; moved the working copy out of OneDrive to a plain local path to protect git integrity.
  - Used AI to deep-analyze all product documents (`docs/`): Capstone Overview, Plan & Tech Stack, Engineering Guide, Architecture deck, and the Backlog spreadsheet — including programmatic extraction of the **color-coded MVP stories** (cell-fill analysis of the xlsx).
  - Locked MVP scope v2 with explicit dependency rulings (drop S32, cut Notification Engine E6, include S43 + S47, AI suggestions render on findings page) and priority tiers (P1 demo-critical / P2 stretch).
  - Decided the AI-discovery approach: **deterministic engine, AI-planned coverage** — generic whole-account discovery with a Bedrock Agent proposing coverage extensions as data.
  - Produced `SPECKIT_PLAYBOOK.md`: exact inputs for every speckit command, six-feature spec slicing, run order, and working agreement — trunk-based on `pods/pod73`, short-lived `pods/pod73-XXX` feature branches, all PRs into `pods/pod73` with AI review.
  - **Pivoted the delivery model:** re-installed Spec Kit with the **claude** integration so Claude Code drives the full `/speckit-*` lifecycle, and moved from a 6-member POD plan to **solo development end-to-end** — automated AI reviews (agentic PR checker / Copilot code review) replace the second-human merge gate; constitution amended to v2.0.0 accordingly.
- **Outcome (2026-08-22):** Repo initialized with Spec Kit + Claude Code integration on branch
  `pods/pod73`; working branch `pods/pod73-001-platform-foundation` cut for spec 001. Delivery
  model pivoted from a 6-person POD to solo-with-AI-agents, and the constitution amended to
  **v2.0.0** to match. Spec 001 (platform-foundation) pipelined end to end in a single session:
  constitution → specify → clarify → plan → checklist → tasks → analyze → remediation.

## 1. Constitution

- **Tool:** `/speckit-constitution` (run in Claude Code)
- **Approach:** Eight enforceable principles derived from the product docs and hackathon judging criteria: Spec-First Delivery; AWS-Native runtime & GitHub-Native delivery (Amazon Bedrock Agents for all product GenAI; Claude Code as the development-time engine); Zero Stored Credentials; Deterministic Core, Agentic Edge; Contract-First Modularity; Test & Quality Gates; Solo Trunk-Based Delivery with AI Collaboration; Honest Prioritization (P1/P2). v1.0.0 ratified for the original POD model; amended to v2.0.0 for solo + Claude Code governance.
- **Outcome (2026-08-22):** **v1.0.0 ratified** — 8 principles, each with an explicit *Testable*
  clause and rationale, plus Technology/Security Constraints, Development Workflow, and Governance
  sections. **Amended to v2.0.0 the same day** (MAJOR): Principle VII redefined from *Trunk-Based
  POD Collaboration* to *Solo Trunk-Based Delivery with AI Collaboration* — automated AI review
  replaces the second-human merge gate, the six-owner table is removed, specs are authored
  sequentially 001→006. Principle II widened to *AWS-Native Runtime and GitHub-Native Delivery*,
  naming Claude Code as the permitted development-time engine while keeping the product GenAI layer
  restricted to Bedrock Agents and every non-AWS AI runtime out of the deployed system. That
  amendment closed a real self-inconsistency: the lifecycle was already being driven by Claude Code
  while the principle listed only Copilot, which made the project non-compliant with its own
  constitution on paper. `TODO(POD_MEMBER_NAMES)` removed rather than filled — there is no POD to
  name. Governance: amendments now approved by the sole maintainer, still via PR with an AI review.
- **Amended to v2.0.1 (2026-08-23, PATCH):** `/speckit-analyze` (T128, finding F1, CRITICAL)
  caught that the v2.0.0 amendment's own Sync Impact Report had claimed full propagation while
  missing two spots — the opening paragraph ("built by a six-person POD") and the Development
  Workflow section (step 2: "POD assignment"; step 3: "Copilot review plus one human review") —
  both still describing the six-person process, directly contradicting the redefined Principle
  VII. A constitution that contradicts itself gives a PR reviewer no single MUST to check
  against, which is why this was flagged CRITICAL rather than a routine wording nit. No principle
  redefined; wording only. [PR #25](https://github.com/SumanKanrar-IEM/CloudPulse-AI/pull/25).

## 2. Specification (6 feature specs, sequential solo pipeline)

- **Tools:** `/speckit-specify`, `/speckit-clarify` (Claude Code)
- **Slicing (authored in dependency order):** 1 platform-foundation · 2 account-onboarding-and-discovery · 3 tag-compliance-and-ownership · 4 governance-dashboard · 5 cost-and-utilization · 6 ai-insights-agent.
- **Approach:** Functional, tech-agnostic spec inputs from the playbook; each spec pipelined fully (specify → clarify → plan → checklist → tasks → analyze) before the next begins, so every merged spec is context for its successors; clarify answered from the settled decision log; each spec branch renamed to the `pods/pod73-XXX` pattern and merged to `pods/pod73` via PR the same day.
- **Outcome — spec 001 platform-foundation (2026-08-22):** branch
  `pods/pod73-001-platform-foundation`. `/speckit-specify` produced 7 user stories (6×P1, 1×P2) and
  53 functional requirements across backlog S1–S7, with one `[NEEDS CLARIFICATION]` raised: the
  input described identity two contradictory ways ("sign in with organizational identity" vs S5's
  "user sign-up/sign-in"). Answered **A — federated sign-in only, role derived from directory group
  membership**, which removed work rather than adding it but surfaced two cases worth pinning down
  (no mapped group, multiple mapped groups — both now refused rather than resolved).
  `/speckit-clarify` asked 4 of a possible 5 questions, all answered "recommended": (1) prod data
  is *not* disposable — teardown is dev-only, prod carries deletion protection, daily backups
  retained; (2) retention per data class — audit events indefinite, logs 30 days, backups 7 days;
  (3) API contract is unversioned and additive-only with a CI breaking-change gate, no `/v1` prefix;
  (4) accessibility baseline plus automated linting in the frontend build. Two items were resolved
  by informed guess rather than asked, and recorded as reversible: single seeded tenant with a
  tenant-aware schema, and a 1-hour session/role-propagation bound.

## 3. Planning & Task Generation

- **Tools:** `/speckit-plan`, `/speckit-checklist`, `/speckit-tasks`, `/speckit-taskstoissues`, `/speckit-analyze`
- **Approach:** One shared AWS-native technology direction across all six plans (Lambda/FastAPI, Step Functions, Cloud Control API discovery, Aurora Serverless v2, Angular 18, Bedrock Agents, Terraform, GitHub Actions OIDC). Tasks ordered P1-first, exported to GitHub Issues to feed the agentic triage workflow and the visible burndown board; analyze run per spec before any code.
- **Outcome — spec 001 (2026-08-22):** `/speckit-plan` produced plan.md, research.md (12 decisions
  with rejected alternatives), data-model.md (10 entities, 8 ordered migrations), an OpenAPI
  skeleton contract, and quickstart.md (V1–V9 validation scenarios). Constitution check PASS at
  both gates; Complexity Tracking empty. Three decisions dominated: **R-002** a migration Lambda in
  the VPC, because a GitHub runner cannot reach a private Aurora cluster and putting a DB password
  in a GitHub secret would violate Principle III; **R-004** a Cognito pre-token-generation Lambda
  *plus* an independent in-application re-check, because the JWT authorizer validates signature and
  expiry but not claim cardinality, and a control that silently picks the first group is the exact
  escalation bug FR-032a exists to prevent; **R-007** a split integration-test strategy —
  Testcontainers PostgreSQL, moto, locally-signed JWTs — because LocalStack's free tier covers
  neither Cognito nor RDS. Four items carry **VERIFY** markers rather than being asserted as fact.
- **`/speckit-checklist`:** generated `scope-and-contracts.md`, 48 reviewer-owned items across
  tier completeness, testability, scope leakage, and cross-spec contracts. Roughly a dozen were
  written because the expected answer was "no" — they were found, not invented.
- **`/speckit-tasks`:** 128 tasks, T001–T128, across 10 phases. P1 = T001–T113; P2 = T114–T122, all
  explicitly marked. 122 cite a backlog S-number; all 128 cite a requirement or principle.
- **`/speckit-analyze` (2026-08-22):** 15 findings — 2 CRITICAL, 4 HIGH, 7 MEDIUM, 2 LOW. FR
  coverage measured mechanically at 92% (61/66), SC coverage 100%. **All 15 resolved.** The two
  CRITICALs were this journal's own unfilled outcomes (Principle I) and a connector interface that
  tasks created but no requirement asked for (Principle I + V) — resolved by adding FR-054 and
  delegating the protocol to spec 2 (S11) rather than widening spec 001's scope. Seven new
  requirements added (FR-001a, FR-013a, FR-033a, FR-054–FR-057), three vague ones quantified
  (FR-003, FR-012, FR-021), two success criteria added (SC-016, SC-017), and two task-ordering
  errors corrected. Spec 001 now stands at 73 FRs and 17 SCs with 100% task coverage.

## 4. Implementation & Human–AI Collaboration

- **Tools:** `/speckit-implement` (Claude Code), GitHub PRs with automated AI review, GitHub Actions CI
- **Approach:** Task-sized short-lived branches named `pods/pod73-<task-id>-<slug>`; every PR targets `pods/pod73`, references spec + issue, passes CI gates (ruff, mypy, pytest+moto, Angular build, terraform validate), and gets an automated AI review (agentic PR checker / Copilot code review) before same-day self-merge to the always-releasable trunk.
- **Outcome — spec 001, Phases 1–3 (2026-08-22):** `/speckit-implement` completed **31 of 128
  tasks** — T001–T012 and T014–T032, the full monorepo scaffold, Terraform bootstrap/network/env
  source, and the nine-category PR gate. **Verified, not asserted:** 20 unit tests pass; both new
  enforcement gates were negative-tested (each exits 1 on a planted violation and 0 once reverted);
  all 18 Python files parse; all YAML/JSON/TOML parses; no workflow references `main`/`master`.
  **Four tasks deliberately left open** because they need access this session does not have:
  T013 (apply bootstrap to a real AWS account), T033 (branch protection), T034/T035 (live PR runs
  to prove each gate fails and to time the suite). Phases 4–8 are blocked behind T013.
  **Caught during implementation:** gitleaks would have failed the build on two deliberate
  credential-shaped strings — the CI fixture and the scanner's own self-test — so a narrow
  `.gitleaks.toml` allowlist was added rather than leaving a gate that cries wolf.
- **T013 bootstrap applied to AWS account 767828743440 (2026-08-22):** 9 resources created,
  verified against the live account. Three defects were caught before anything touched AWS:
  a local/CI Terraform version mismatch (1.15.8 vs a pinned 1.9.5) that would have made the
  first CD run unreadable-state, `fmt` violations in 3 files, and an undeclared `tls` provider.
  All three are now pinned/fixed. **Identity was moved off account root to IAM Identity Center
  SSO before applying** — the original session was `arn:...:root`, which is exactly the finding
  CloudPulse AI exists to detect. **`PowerUserAccess` was replaced with a least-privilege policy**
  (3,059 chars, 8 statements) before apply rather than deferring to T107: 4 DENY statements block
  the deploy role from destroying the bootstrap foundation, rewriting its own trust policy,
  attaching admin policies, or creating any IAM user or access key — making Principle III
  structurally enforced rather than merely intended. `prevent_destroy` was removed from the state
  bucket and lock table at the maintainer's request so the account can be torn down cleanly; the
  IAM deny still prevents the *pipeline* from destroying them. OIDC trust verified as scoped to
  `repo:SumanKanrar-IEM/CloudPulse-AI` on `refs/heads/pods/pod73` and the `dev` environment only.
  **Open follow-up: root access keys still exist on the account** (`AccountAccessKeysPresent=1`)
  and should be deleted.
- **Phase 4 written, not applied (2026-08-22):** T036–T045 complete — Aurora Serverless v2,
  CloudFront/S3 frontend, snapshot bucket, teardown guard, idempotency check, runbook. Apply
  deferred by the maintainer after a cost review surfaced that **RDS Proxy costs ~$88/mo** on an
  8-ACU minimum — roughly twice the 0.5-ACU cluster it pools for. research.md R-003 had already
  recorded the no-proxy fallback at demo scale, so taking it follows the plan rather than
  deviating; `enable_rds_proxy` is wired either way (T129 tracks the decision). Two bugs caught in
  the teardown guard: `${1,,}` needs bash 4+ and macOS ships 3.2, so the guard **failed open** —
  fixed and pinned by a test; and the first version of that test emptied `PATH`, which broke
  `dirname`/`tr` and tested the harness rather than the guard — rewritten to use recording shims.
  **T039 is partial by necessity:** Terraform requires `prevent_destroy` to be a literal, so it
  cannot be conditional on environment, and FR-002 mandates one shared module set. R-010's layers 1
  and 3 hold; layer 2 is not implementable as specified. T130 added to correct the spec rather than
  work around it (Principle I).
- **Phase 5 complete (2026-08-22):** T050–T063 — 11 tables, 8 ordered migrations, SQLAlchemy 2
  models, tenant-scoped session, append-only audit writer, ERD. **26 integration tests pass against
  a real PostgreSQL 16 container**, which is the only thing that genuinely proves FR-026: migrating
  a populated database loses zero rows. Audit immutability verified in all three layers separately —
  trigger, withheld grant, and absent ORM path — including the bulk `DELETE FROM audit_event` case a
  naive row-trigger implementation misses. Revision `0003` declares `REVERSIBLE: no` and raises on
  downgrade, because rolling it back would restore UPDATE/DELETE on the audit table. **The
  connector-boundary gate caught its first real violation** — `migrations/env.py` importing boto3 —
  and it was judged rather than reflexively allowlisted: it fetches the platform's *own* database
  credential, not scanned-account data, so it qualifies under the same reasoning as `app/core/db.py`.
  The allowlist now states the test for what qualifies.
- **Phase 6 complete (2026-08-22):** T064–T076, T078–T079 — FastAPI skeleton, uniform error
  envelope, correlation middleware, redacting structured logger, health endpoint, API Gateway +
  Lambda Terraform, migration Lambda, generated contract, and the Angular a11y shell.
  **Three bugs found by the tests, two of them real:**
  (1) `_check_database` caught only `TimeoutError`, so an unexpected failure inside the health
  check surfaced as a 500 — which is "failing to respond", exactly what FR-042 forbids alongside a
  false healthy. Now total.
  (2) Validation error fields were reported as `query.n` rather than `n` — the location kind is
  FastAPI's internal detail, not what a client developer needs.
  (3) A test-fixture route collision (`/_t/boom` matching `/_t/{code:int}`), fixed in the test.
  **Two contract gaps closed at T075:** the error envelope existed only at runtime and never
  entered the generated OpenAPI document, leaving consumers to hand-roll the error type; and no
  security scheme was declared, so a later endpoint would have inherited no requirement. Both now
  in the contract, with `/health` as the single explicit public opt-out (FR-033a). The committed
  `backend/openapi.generated.yaml` is now the CI baseline, with a staleness check that fails a PR
  whose contract does not match its code — the design-time copy under `specs/` is explicitly
  non-authoritative.
  **The credential scanner fired again**, this time on the redaction test's own fixtures. Rather
  than appending another name, the exclusion now states the rule — *does the file exist to define,
  test, or allowlist credential patterns?* — and the gitleaks config mirrors it, so the local gate
  and CI agree.
  **T077 and T080 remain open:** the Angular client generation needs npm (not installed here) and
  the log-trace confirmation needs a deployed environment.
- **T077 + Phase 7 complete (2026-08-22):** npm installed by the maintainer unblocked T077. The
  generator is a Java tool with no JRE present, so OpenJDK was installed and pointed at via
  `JAVA_HOME` rather than `brew link` — openjdk is keg-only and linking shadows the macOS Java stub
  system-wide. The generated Angular client **includes typed `ErrorEnvelope`/`ErrorBody`/
  `ErrorDetail` models**, which retroactively justifies the T075 fix: without it every consumer
  would have hand-rolled the error type. Angular build and lint both verified green.
  **Phase 7 (T081–T094, T097):** Cognito pool with `allow_admin_create_user_only = true` (leaving
  Cognito's public sign-up on would have been an FR-031 violation shipped by omission), three role
  groups from a data map, 1h/8h token validity, pre-token Lambda, JWT authorizer with `/health` as
  the single explicit `authorization_type = NONE` route, `require_role`, `/me`, Angular auth guard,
  and the FR-056 agent access path.
  **The FR-032a rule is enforced in two independent layers and tested for agreement.** A dedicated
  test asserts the pre-token Lambda and `app/core/security.py` resolve identically for every case —
  if they disagreed, sign-in would appear to succeed while every request failed. The role matrix
  covers all **18 SC-008 cells**; the no-mapped-group and multiple-mapped-group rows are the only
  two that catch the naive "pick the first group" implementation, and their refusals are asserted
  byte-identical so a caller cannot learn its own group cardinality from the error.
  Cognito group `precedence` was deliberately left unset: precedence exists to break multi-group
  ties, and FR-032a requires refusal rather than resolution.
  **Remaining in Phases 1–7 all need external access:** T033–T035 (repo admin, live PR runs),
  T046–T049 (an applied environment), T080/T095/T096 (a deployed environment).
- **Phase 8 written (2026-08-22):** T098–T106 and T112 — `deploy-dev.yml`, `deploy-prod.yml`, the
  deployment record, and failure handling. **The prod gate is structural, not procedural:** the
  workflow is split into a `plan` job with no environment gate (read-only, so it needs no approval)
  and a `deploy` job carrying `environment: prod`. GitHub pauses the second until a reviewer
  approves, so FR-019's "leaves prod completely unchanged until approved" holds by construction
  rather than by careful step ordering. Prod is `workflow_dispatch` only and refuses any commit
  that is not an ancestor of `pods/pod73`.
  **Deployment recording had the same VPC problem as migrations** (R-002): the `deployment` table
  is in the private subnet and the runner cannot reach it. Rather than add a third Lambda, the
  existing in-VPC handler gained `record_start`/`record_finish` — the pipeline always calls both
  together, and a second function would duplicate the VPC config, role and package for no gain.
  `downgrade` remains absent from its allowlist.
  **`if: always()` on the outcome step is load-bearing:** FR-021's third condition is that a failed
  deployment is recorded as `failed`, not left `running`, because a stuck record is
  indistinguishable from one still in progress. `cancel-in-progress: false` on both concurrency
  groups for the same reason — cancelling mid-apply is exactly how an environment reaches the
  unknown state FR-021 forbids.
  **T112 (SC-012) confirmed both halves locally:** the credential scan passes, and no workflow
  references a static AWS key. The only `secrets.` reference is GitHub's own auto-provided token;
  the deploy role ARN correctly uses `vars.` because it is an identifier, not a credential.
  **248 tests passing** (196 unit, 52 integration); all 9 Terraform roots validate.
  T107–T111 and T113 need an applied environment.
- **Phases 9 and 10, cost-free tasks (2026-08-22):** Phase 9 (T114–T122, all P2) written but
  deliberately **not applied** — `enable_observability` defaults to `false`, so deleting the module
  leaves every P1 criterion intact, which is the Principle VIII check. T116 decided the thresholds
  FR-050 left as "agreed threshold", with the reasoning stored next to each alarm: 5 errors over
  two 5-minute periods (a healthy service at demo scale produces zero 5xx, but one cold-start blip
  should not page); 1 scan failure (an unscanned account has no tolerable rate); any DLQ message at
  all (a non-zero depth *is* the failure).
  **The `treat_missing_data` settings carry more weight than the numbers.** Left at the default,
  a failure-count alarm parks in INSUFFICIENT_DATA and never fires — indistinguishable from
  healthy. The heartbeat alarm inverts it to `breaching`, because a *missing* heartbeat is the
  failure; getting that backwards would produce an alarm that can never fire, which is precisely
  the FR-053 problem it exists to solve. The wiring script also asserts the SNS email subscription
  is **confirmed**, not merely created: a pending subscription looks exactly like working alerting
  until the first real incident.
  **Phase 10:** T130 corrected R-010 and the FR-005a note — `prevent_destroy` cannot be conditional,
  so prod protection is two layers, not three; the spec was corrected rather than worked around
  (Principle I). T123 recorded the four VERIFY outcomes honestly: three were resolved or sidestepped
  during implementation, and **R-008 (`oasdiff` classification) is recorded as still open** rather
  than quietly dropped — the gate is wired but has never run, so FR-048b is enforced in intent only
  until T034. T125 became a script rather than prose; two of my own checks were wrong before the
  artifacts were (`spec 2` vs `spec 002`, and a shell `||` precedence bug), which is a reminder that
  a verification failing is not the same as the thing being verified failing.
  **266 tests passing** (214 unit, 52 integration); 10/10 Terraform roots validate.
- **Live verification session (2026-08-22, 11:04-11:59 UTC, cost ~$0.07):** T129 decided (ephemeral
  sessions; proxy off per R-003, min_acu 0.5), then applied 48 resources to dev, verified, and
  destroyed. **Eleven tasks closed:** T046-T049, T080, T095, T096, T110, T111, T113, T129.
  Teardown verified independently against AWS - zero orphaned resources; only the state bucket
  survives, as it must.

  **Four defects that only a live apply could find** - `terraform validate` and `plan` passed all
  of them:
  1. **Non-ASCII in a security group description.** `CreateSecurityGroup` rejects it outright
     (`Character sets beyond ASCII are not supported`); an em-dash failed the apply midway, after
     ~20 resources already existed. Fixed in 3 files and now guarded by
     `ops/scripts/check_terraform_ascii.py`, wired into CI and `make check`.
  2. **`count` derived from an unknown value.** The JWT authorizer's count came from a sibling
     module's output, which Terraform cannot evaluate at plan time. Replaced with an explicit
     `enable_cognito_auth` boolean - the standard pattern for exactly this.
  3. **Aurora `16.4` no longer exists.** Valid at planning time, deprecated by first apply. Pinned
     to `16.14`, staying on major 16 deliberately so the Testcontainers suite (`postgres:16-alpine`)
     tests the same major the platform runs on.
  4. **FR-043 / SC-009 gap, fixed 2026-08-23.** Every pre-authorizer rejection returned API
     Gateway's `{"message":"Unauthorized"}`, not the uniform envelope. Chose the Lambda authorizer
     over a spec amendment (research.md R-004 addendum). `handlers/authorizer_handler.py` performs
     the same signature/issuer/audience/expiry checks the native JWT authorizer did, but always
     returns `isAuthorized: true` -- a failed check is recorded as `context.valid: "false"` rather
     than denied at the gateway, so the request reaches the app and gets refused there instead,
     through the same `AppError(UNAUTHORIZED)` path every other failure already uses. Covered by
     14 new unit tests: `test_authorizer_handler.py` (signature/issuer/audience/expiry, including
     that an unverified token still returns `isAuthorized: true` with no claim data attached) and
     `test_claims_from_authorizer_context.py` (the load-bearing one -- proves an unverified context
     yields zero claims, not a leaked `sub`).

  **FR-032a verified end to end against a real Cognito pool**, which is the result that matters
  most: no mapped group -> 403, viewer -> 200 viewer, **two groups -> 403 refused rather than
  resolved**, admin -> 200 admin. The naive "pick the first group" implementation would have passed
  three of those four.

  **Two smaller findings, both fixed 2026-08-23:**
  - `/me` returned an empty `email` because the access token carries no email claim (the ID token
    does). Not a platform bug -- the frontend token-attachment code doesn't exist yet (a later
    spec's job) and access tokens never carry email by design. Documented as a requirement on
    whichever client sends the Authorization header, in `infra/modules/identity/main.tf` next to
    the app client that issues both token types.
  - The API Gateway access-log format used `$context.error.messageString` for `correlationId`,
    which is empty outside a gateway-level error and logged `"-"` on every normal request. HTTP
    APIs cannot read an integration's response headers back into the access log, so the app's own
    `X-Correlation-Id` was never recoverable there regardless of which `$context` variable was used.
    Renamed the field to `requestId` (`$context.requestId`, always populated) and had
    `app.api.middleware` log that same id alongside the app's `correlation_id`, so the two log
    groups can still be cross-referenced by a shared field for SC-010.

  **SC-010 note:** `filter-log-events` did not index a new low-volume group within 2 minutes, but
  **CloudWatch Logs Insights found the record in 2 seconds** with all fields intact. Insights is the
  correct tool and the runbook should say so.

## 5. Agentic Automation

- **Tools:** GitHub Agentic Workflows (`gh aw`), adapted from githubnext/agentics
- **Planned set:** issue triage, constitution-aware PR reviewer, CI doctor, daily progress + journal drafter.
- **Outcome:** *(workflows compiled/enabled, examples of agent contributions)*

## 6. Assessment & Convergence

- **Tools:** `/speckit-analyze`, `/speckit-checklist`, `/speckit-converge`
- **Approach:** End-of-sprint audit of codebase vs specs and constitution; remaining gaps appended as tasks, never silently dropped.
- **Outcome:** *(convergence report summary, P1 coverage %, final architectural assessment)*

## T033 — Branch protection configured (2026-08-22)

**Context.** Branch protection, rulesets, and environment required-reviewers are all
unavailable on a private repo under a free personal GitHub account — confirmed via the
API rather than assumed (`403 Upgrade to GitHub Pro or make this repository public`).
Verified this blocked 6 of the 9 remaining tasks (T033, T034, T035, T108, T109, T127),
including the mechanism that enforces FR-011 and FR-017.

**Decision.** The maintainer made the repository public. Verified before recommending
it: `gitleaks detect` over the *entire* history returns "no leaks found" — Principle
III's zero-stored-credentials design means there was nothing to expose. The only
identifiable data in committed files is the AWS account ID (non-secret, appears in
every ARN) and Cognito/API IDs from an environment already destroyed.

**Applied via the GitHub API** (`gh api`), then independently re-read to confirm:

- **Branch protection on `pods/pod73`**: 13 required status checks (every CI job by
  name), `enforce_admins: true` (no bypass — FR-011), force-push and deletion both
  disabled, conversation resolution required. `required_approving_review_count: 0` —
  GitHub cannot let a sole maintainer approve their own PR, so the merge gate is
  green CI + a recorded AI review per constitution v2.0.0 Principle VII, not a second
  human approval.
- **`prod` GitHub Environment**: required reviewer (the maintainer), restricted to
  protected branches only. This is what makes `environment: prod` in
  `deploy-prod.yml` actually pause for approval — FR-017 is now enforced, not merely
  coded.
- **`dev` GitHub Environment**: no gate, protected-branches-only — matches FR-015's
  "deploys automatically on merge."

T033 complete. Unblocks T034, T035, T108, T109, T127.

## T034, T108 — live-verified against the real trunk (2026-08-22)

**Sequencing decision.** T034 needs branch protection tested against the real trunk,
but `pods/pod73` had none of spec 001's code yet — PR #1 (the entire foundation) had
been open the whole build. Rather than test fixtures against a feature branch (which
would only prove "the check fails," not "merge is blocked"), asked the maintainer and
merged PR #1 first. GitHub Copilot review is unavailable on this account tier, so an
AI review was recorded as a `COMMENTED` review (GitHub does not allow self-approval)
per constitution v2.0.0 Principle VII's fallback, then merged.

**Merging to trunk immediately triggered `deploy-dev.yml`** (FR-015) — an unplanned
but genuine opportunity to exercise T108 for real. It failed three times, each
failure a real bug caught only by watching a live run:

1. **OIDC trust rejected.** `AssumeRoleWithWebIdentity` failed with a bare
   "Not authorized." CloudTrail showed GitHub's actual `sub` claim embeds numeric
   owner/repo IDs (`repo:OWNER@ID/REPO@ID:...`) by default now — confirmed via
   `gh api .../actions/oidc/customization/sub` (`use_default: true`). The trust
   policy only listed the older plain form. Fixed by listing both.
2. **`aws lambda invoke ... /dev/stdout` concatenation.** The CLI's own status
   metadata and the Lambda's payload land on the same stream, producing two JSON
   documents on one line; `jq` silently evaluates the requested field against both,
   emitting the second as a bare `null` that fails `$GITHUB_OUTPUT`'s parser.
   Reproduced locally against the live Lambda before fixing all six call sites.
   Alongside it: the frontend publish step derived the S3 bucket name by stripping
   `https://` off the CloudFront URL — masked by a `||` fallback that happened to
   guess right.
3. **`record_start` ran before migrations.** On a brand-new database the `tenant`
   table it queries does not exist yet. Reordered both workflows to
   apply → migrate → record → publish → smoke test → record outcome. prod's ordering
   changed more: `record_start` had run before `terraform apply` even created the
   migrate Lambda, which would have failed prod's very first deploy outright. The
   `environment: prod` gate — not step ordering — is what actually enforces
   FR-017/FR-019.

Two smaller bugs surfaced alongside: my own `jq -r '.error // \"unknown error\"'`
inside single quotes (backslashes are literal there; invalid jq syntax), and
`Settings` requiring Cognito config that no Python code reads and that the
migration/pre-token Lambdas never set. Each fix shipped as its own small PR (#2–#5),
each with a recorded AI review, each merged only after all 13 checks passed.

**T108 / SC-005, independently verified — PASS.** Merge to live-in-dev: 142 seconds
(budget 15 minutes). Confirmed against the live API (`/health` returns `healthy`,
`version` matches the merge commit) and by round-tripping `record_start`/
`record_finish` directly against the migrated schema — not just the workflow's own
green checkmark.

**T034 / SC-003, verified as 11 real PRs against the protected trunk**, not a
tabletop exercise. Every broken fixture showed `mergeStateStatus: BLOCKED` — the
half of SC-003 a dry run cannot prove. The additive fixture showed
`CLEAN, MERGEABLE` with all 13 checks green, confirming FR-048a's inverse.

Three findings were genuine cross-check couplings, not defects, and are now
documented in `ops/ci-fixtures/README.md` rather than engineered away: an untyped
snippet fails both `ruff` and `mypy`; a leaked credential fails both `secret-scan`
and the unit suite's own `test_no_credentials.py` (deliberate defense in depth); a
shared Terraform module fails both environments' validate jobs. Two were fixture
authoring bugs and were fixed: a literal `1 == 2` also tripped mypy's
comparison-overlap check, and a missing blank line tripped ruff's import sort.
Fixtures 6 and 11 needed the generated client regenerated in the same commit — the
same requirement any real contract-changing PR has (FR-048) — which is why the
first pass on both showed `client-drift` failing alongside (or instead of) the
intended result.

All 11 fixture PRs closed without merging; branches deleted.

**T035 / SC-004.** Wall-clock across six real CI runs this session: 61-78s, well under
the 10-minute budget. No parallelism tuning needed.

## Session: prod live verification, full teardown, requirements review (2026-08-22/23)

**T107 / T109, verified against a real, paused, then real, completed prod deploy.**
`infra/bootstrap` had only ever been applied for dev — provisioning prod exposed
that its OIDC provider is an AWS account-wide singleton and bootstrap has no
backend of its own. Fixed with a `create_oidc_provider` variable: prod's bootstrap
apply reuses dev's existing provider via a `data` source instead of trying (and
failing) to create a second one. Verified in isolation with
`terraform plan -state=terraform-prod.tfstate` before applying, then confirmed via
`aws iam list-open-id-connect-providers` that dev's provider/role/bucket were
untouched afterward. This was the most architecturally significant fix of the
session and wasn't in the original task list — discovered mid-task (PR #20).

With prod's cost profile mirrored to dev's (PR #19: `enable_rds_proxy=false`,
`min_acu=0.5`, `max_acu=2`, `enable_observability=false`), dispatched
`deploy-prod.yml` for real. The `Apply to prod` job — gated by `environment: prod`
with the maintainer as required reviewer — paused at `pending_deployments`, exactly
as FR-017 specifies. Independently verified via AWS CLI *while paused*: zero prod
RDS clusters, zero prod-tagged VPCs, zero prod Lambda functions — the only
CloudFront distribution and Cognito pool that existed belonged to dev. This is the
live SC-006 proof (a paused release leaves prod byte-for-byte unchanged), not a
code-review claim. After manual approval via the GitHub UI, the deploy completed:
`terraform apply` → migrations → `record_start` (approved_by=$GITHUB_ACTOR,
approved_at populated — reaching this job at all requires GitHub to have recorded
that approval) → frontend publish → `record_finish`. Confirmed independently by
curling the live prod `/health` endpoint (200, `version` matches the deployed SHA).

**Full teardown of both environments, then an independent cost sweep.** Dev:
`ops/teardown.sh dev` destroyed 48 resources cleanly; the frontend S3 bucket needed
a manual `aws s3 rm --recursive` first (Terraform can't delete a non-empty bucket)
and a second destroy pass closed it out — 49 total. Prod: `ops/teardown.sh`
correctly refuses prod by design (FR-005a), so prod's teardown required the
documented out-of-band step — `aws rds modify-db-cluster --no-deletion-protection`
— confirmed by the user before running, then a direct `terraform destroy` in
`infra/envs/prod` (48 resources). Swept every cost-bearing AWS resource category
after both destroys completed: RDS, Lambda, VPCs, NAT gateways, EC2, load
balancers, Elastic IPs, CloudFront, Cognito, API Gateway, VPC endpoints, Secrets
Manager, EventBridge, SQS, Step Functions — all zero. Only the two bootstrap state
buckets and their paired (empty, pay-per-request) DynamoDB lock tables remain,
alongside three AWS-managed (free) KMS default keys. Nothing needed force-destroying.

**T124 — reviewed `checklists/scope-and-contracts.md` against the current spec
text, item by item**, not a rubber stamp of the prior remediation table. 30/48
marked satisfied; 18 left open as genuine, accepted gaps for a solo-maintainer
foundation spec — mostly edge cases (approval expiry, IdP outage, correlation-ID
validation, name collision) that exist only in the Edge Cases prose with no
matching FR, plus a few terms (bounded interval, agreed threshold, authorised
approver) quantified only in Assumptions rather than in the requirement text
itself. None block the P1 demo path. Documented in a new "Review pass" section in
the checklist file rather than just flipping boxes.

**T127 — confirmed all 9 merged PRs (#1-5, #17-20)** carry both a green
`SUCCESS` status rollup and a recorded `COMMENTED` AI review. No PR merged without
one.

129/130 tasks now closed. The sole remaining item is T128 (re-run
`/speckit-analyze`), deliberately out of this session's scope — flagged for the
next joint review rather than run unprompted, since it may surface findings that
change scope.

## T128 -- /speckit-analyze re-run and remediation (2026-08-23)

Re-ran `/speckit-analyze` against the current state of spec.md, plan.md, and tasks.md.
FR/SC-to-task coverage cross-checked mechanically: all 73 FR keys and all 17 SC keys
have >=1 referencing task -- zero orphaned-requirement findings. Six real findings
surfaced instead, all now resolved:

- **F1 CRITICAL** -- the constitution's own opening paragraph and Development
  Workflow section still described the six-person POD process ("Copilot review plus
  one human review"), directly contradicting Principle VII's v2.0.0 redefinition to
  solo delivery. A constitution that contradicts itself gives a PR reviewer no single
  MUST to check against. Amended to v2.0.1 (PATCH, wording only) --
  [PR #25](https://github.com/SumanKanrar-IEM/CloudPulse-AI/pull/25).
- **F2 HIGH** -- PRs #23 and #24 (the `identity_sources` fix and the `DEV_AUTO_DEPLOY`
  toggle) merged with zero task ID in their bodies, violating Principle I. Retroactive
  tasks T131-T134 added tracing #22-#24 --
  [PR #26](https://github.com/SumanKanrar-IEM/CloudPulse-AI/pull/26).
- **F3/F4 MEDIUM** -- five stale "JWT authorizer" references and one Tier Summary
  overclaim (SC-016/017 attributed to Phases 1-8 when they're actually T125 in Phase
  10), both fixed in PR #26.
- **G1/G2 MEDIUM** -- no automated gate exercised the authorizer's actual AWS-level
  wiring (`infra/tests/test_authorizer_wiring.sh` added), and `DEV_AUTO_DEPLOY` was
  undocumented in the provisioning runbook (fixed). Both in PR #26.

**Closing F2's root cause, not just its symptom.** Retroactive task tracing fixes the
historical record but does nothing to stop the next untracked PR. Added a
`pr-task-reference` CI gate requiring every PR body to cite a `T\d{3}` task ID --
[PR #27](https://github.com/SumanKanrar-IEM/CloudPulse-AI/pull/27) -- and wired it into
`pods/pod73`'s required status checks. Deliberately does not accept an FR-/SC-
reference as a substitute: PR #24 cited `FR-015` and still had no tracing task, which
is direct proof that check alone would not have prevented F2. Verified live, not just
by inspection: opened a throwaway PR with no task ID, confirmed
`mergeStateStatus: BLOCKED`, closed it without merging.

T128 marked complete. 130/130 tasks closed.
