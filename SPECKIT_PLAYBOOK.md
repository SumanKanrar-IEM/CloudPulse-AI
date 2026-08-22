# CloudPulse AI — Spec Kit Playbook (Claude Code Edition, Solo)

> Copy-paste inputs for every `/speckit-*` command, in execution order, for the CloudPulse AI MVP.
> Scope source: color-coded stories in `docs/CloudPulse-AI_Backlog.xlsx` (scope v2 — see §0.3).
> Delivery model: **one developer** driving **Claude Code** as the spec-driven development
> engine, with GitHub as the delivery platform (repo, Actions, Issues, agentic workflows).
> The "POD" is one human plus AI agents — and that is the story the judges are told.

---

## 0. Ground rules before any command

### 0.1 Tooling model

- **Engine:** GitHub Spec Kit is installed with the **claude** integration (`.claude/skills/speckit-*`,
  Python scripts, `-` separator). Every command below runs **inside a Claude Code session in this
  repo** as `/speckit-<name>` (e.g. `/speckit-specify`, `/speckit-plan`).
- **Division of labor:** Claude Code authors specs, plans, tasks, and code; GitHub Actions is CI/CD;
  gh-aw agentic workflows (§11) are the automated teammates (triage, PR review, CI diagnosis,
  journal drafting). The product's own GenAI runs on Amazon Bedrock Agents — the engineering
  tooling choice does not change the AWS-native runtime rule.
- **Judged evidence:** the git history, PR trail, GitHub Issues, `AI_WORKFLOW_JOURNAL.md`, and the
  spec artifacts under `specs/` are the assessment surface. Keep them clean and truthful.

### 0.2 Working agreement (solo edition)

- **Branching:** trunk-based. `pods/pod73` is the only long-lived branch and the target of every
  PR. All working branches follow `pods/pod73-XXX`
  (e.g. `pods/pod73-001-platform-foundation`, `pods/pod73-T042-scan-diffing`).
- **Repo settings (do once):** set `pods/pod73` as the GitHub **default branch**; protect it —
  require the CI check, block direct pushes. Solo twist: do **not** require a human approval
  (there is no second human); the merge gate is **green CI + an automated AI review** (GitHub
  Copilot code review if available on the repo, else the gh-aw PR checker from §11). Self-merge
  after both are green.
- **PR ritual stays, even solo:** every change — spec documents included — lands via a
  `pods/pod73-XXX` branch and a PR that references its spec/task IDs. The PR trail *is* the
  collaboration evidence.
- **Journal:** after every speckit phase, append the outcome to `AI_WORKFLOW_JOURNAL.md` the same
  day.
- **Spec Kit mechanics:** `/speckit-specify` auto-creates a numbered branch (e.g.
  `002-account-onboarding-and-discovery`) and `specs/002-.../spec.md`. Immediately rename the
  branch to the trunk pattern before pushing:
  `git branch -m 002-<name> pods/pod73-002-<name>`
  The `specs/00N-...` directory name keeps its numeric form. If a later speckit command on the
  renamed branch cannot detect the feature, set `SPECIFY_FEATURE=00N-<name>` in the environment
  and rerun.

### 0.3 MVP scope v2 (the single source of truth for "what's in")

| In | Stories |
|---|---|
| Platform foundation | S1–S7 |
| Onboarding | S8–S10 |
| Discovery | S11–S17, S47, **AI-planned whole-account coverage (new)** |
| Compliance + SDA + ownership | S18, S18a, S18b, S19, S20, S21, S22, S23a |
| Dashboard | S27–S31, S33 (S44 suggestions render on the findings page) |
| Cost + utilization | S39–S42, S54–S56 |
| AI insights (Amazon Bedrock Agents) | S43, S44, S50–S53, coverage advisor |

**Out (do not let any spec re-import these):** S32, E6 Notification Engine (S24–S26) —
intentional cut, findings visibility is dashboard-only; E8 remediation execution (S34–S38);
S45, S46, S48, S49; S57–S63.

**Priority tiers (baked into every spec):**
- **P1 (demo-critical path):** onboard account → whole-account scan → findings + compliance
  score + ownership → dashboard (overview, inventory, findings) → Bedrock Agent digest +
  remediation suggestions → basic cost view. Roughly: S1–S6, S8–S16, S18, S18a, S19–S21,
  S27–S30, S39, S42, S43, S44.
- **P2 (stretch, never blocks P1):** S7, S17, S18b, S22, S23a, S31, S33, S40, S41, S47,
  S50–S56, coverage advisor.

### 0.4 End-to-end execution order (solo)

Pipeline each spec **fully** (specify → clarify → plan → checklist → tasks → analyze → merge)
in dependency order 1 → 2 → 3 → 4 → 5 → 6, so every merged spec is context Claude Code can
read when authoring the next.

> **Current status (2026-08-22):** setup (A1) done — trunk `pods/pod73` exists on the remote.
> Constitution **amended to v2.0.0** — solo governance + Claude Code as the development-time
> engine (A2 complete; see §1). **Spec 1 is complete through analyze** on
> `pods/pod73-001-platform-foundation`: spec (73 FRs, 17 SCs), clarify (4 questions), plan,
> research, data model, OpenAPI contract, quickstart, two checklists, tasks (128, T001–T128),
> analyze (15 findings, all resolved). FR and SC task coverage both 100%. Resume at step B11
> (PR into trunk) or B12 (`/speckit-taskstoissues`), then step 14 to start implementing.
>
> **Deviation from the plan below, recorded honestly:** the v2.0.0 amendment was applied
> in-session on `pods/pod73-001-platform-foundation` rather than on a separate
> `pods/pod73-000-constitution-v2` branch, because it was triggered by an analyze finding on
> spec 1 rather than run standalone. The constitution change and the spec-1 artifacts will
> therefore land in the same PR. For specs 2–6, follow A2/B3–B12 as written.

**A. One-time setup**
1. ~~Create `pods/pod73`, push, set as GitHub default branch + protection~~ *(done — verify the
   protection rule requires CI only, not a human approval)*.
2. ~~Run `/speckit-constitution` with the §1 **amendment input** (v2.0.0 — solo governance,
   Claude Code engine) → PR → merge. Journal.~~ *(done 2026-08-22 — applied on the spec-1
   branch, see the deviation note above; journal §1 records it)*.

**B. Spec authoring — repeat per spec, in order 1, 2, 3, 4, 5, 6**
3. `git checkout pods/pod73 && git pull`
4. `/speckit-specify` with the §2 input for spec N (creates branch `00N-<name>`)
5. `git branch -m 00N-<name> pods/pod73-00N-<name>` (fallback: `SPECIFY_FEATURE=00N-<name>`)
6. `/speckit-clarify` — answer from the §3 cheat sheet
7. `/speckit-plan` with the §4 input (+ suffix for specs 1 and 6)
8. `/speckit-checklist` (§5 input) — optional, cheap rigor evidence
9. `/speckit-tasks` (§6 input)
10. `/speckit-analyze` — fix CRITICALs on the branch
11. PR into `pods/pod73` → AI review + green CI → merge. One-line journal entry.
12. `/speckit-taskstoissues` for spec N (from the trunk with `SPECIFY_FEATURE` set, or before
    merging) → label issues by spec + P1/P2. Optional solo, but it feeds the triage workflow
    and gives judges a visible board.

**C. Agentic workflows — after the six specs merge, before heavy implementation**
13. Add the five gh-aw workflows + `CONTRIBUTING.md` (§11), `gh aw compile`, PR → merge.
    They act as your missing teammates for the whole implementation phase.

**D. Implementation — Wave 1, P1 only, in this order**
14. Spec 1 P1 (S1–S6): repo scaffold, Terraform, CI/CD, DB, identity, API skeleton.
15. Spec 2 P1 (S8–S16): onboarding, whole-account discovery, orchestration, persistence.
16. Spec 3 P1 (S18, S18a, S19, S20, S21): rules, SDA registry, findings, score, ownership.
17. Spec 4 P1 (S27–S30): dashboard shell, overview, inventory, findings workbench.
    → **Demo checkpoint 1:** onboard → scan → findings visible in the UI.
18. Spec 5 P1 (S39, S42): spend ingestion + cost dashboard.
19. Spec 6 P1 (S43, S44): Bedrock Agent digest + remediation suggester on findings page.
    → **Demo checkpoint 2:** full P1 demo path walkable end-to-end.
    Each task slice: branch `pods/pod73-<task-id>-<slug>` → `/speckit-implement` (§9 input)
    → PR → AI review + CI → merge → journal.

**E. Implementation — Wave 2, P2 in dependency order (each item skippable)**
20. S7 (alarms — do early, it protects the rest), S17 + S31, S33 (e2e hardening).
21. S47 (extra enrichers) → S56 (IAM hygiene, needs S47).
22. S50 (metrics) → S51 (forecasts) → S52 (rightsizing) → S53 (narratives) → S54/S55
    (utilization, needs S50).
23. S22 → S23a (ownership fallback + email resolution), S18b (SDA admin UI), S40 → S41
    (budgets → overrun findings).
24. Spec 6 coverage advisor (needs S47's coverage-as-data exercised).

**F. Close-out**
25. `/speckit-converge` (§10 input) → fix or log remaining gaps as tasks.
26. Final `/speckit-analyze` pass on any spec converge touched.
27. Complete `AI_WORKFLOW_JOURNAL.md` outcomes; verify every section has real entries.

Reach checkpoint 1 fast, then checkpoint 2, before touching Wave 2 — everything after
step 17 still leaves a coherent, judged-worthy story if the sprint compresses.

---

## 1. `/speckit-constitution` — amendment to v2.0.0 ✅ **APPLIED 2026-08-22**

> **Status: done.** The constitution on disk is v2.0.0. The input below is kept as the record of
> what was asked for; read the file itself for what actually landed. This was a governance change
> → **MAJOR** version bump, correctly applied as such.
>
> **What landed beyond the input below**, all of it tightening rather than loosening:
> - Principle II was restructured into three labelled parts — **Runtime** (AWS-only, Bedrock
>   Agents for product GenAI), **Delivery** (GitHub-native), and **Development-time AI** (Claude
>   Code and Copilot permitted) — because the single-paragraph form made it too easy to read the
>   Claude Code allowance as loosening the runtime rule. It does not: "an authoring tool may be
>   Anthropic's; a running component may not be."
> - Principle II's *Testable* clause now demands an **automated CI allowlist gate**, not just an
>   absence of SDKs. Spec 1 implements it as FR-013a / task T030 — a README assertion was judged
>   insufficient for a NON-NEGOTIABLE principle.
> - Principle VII spells out that a PR with **no recorded AI review must not be merged, however
>   small** — with the second human gone, that review is the only remaining check, so it is stated
>   as a hard rule rather than left implied.
> - Principle VIII's "recorded POD amendment" became "recorded amendment"; the v1.0.0 Sync Impact
>   Report is retained beneath the v2.0.0 one as history.
>
> The amendment also closed a real self-inconsistency: the lifecycle was already being driven by
> Claude Code while Principle II named only Copilot — the project was non-compliant with its own
> constitution on paper until this landed.

**Input used:**

```
Amend the constitution to version 2.0.0. Two material changes; leave all other principles
intact in substance.

1. Delivery model change (rewrites Principle VII, retitle it "Solo Trunk-Based Delivery
with AI Collaboration"): the project is delivered by a single developer working with AI
agents rather than a six-member POD. pods/pod73 remains the only long-lived branch, always
releasable, and the target of every pull request; all working branches keep the
pods/pod73-XXX naming pattern. Every change — including spec documents — still lands via a
small PR that references its spec/task IDs. The merge gate becomes: green CI plus an
automated AI code review (GitHub Copilot code review or the repository's agentic PR-review
workflow); self-merge is permitted once both are green, since no second human exists.
Remove the named-spec-owner roles and the TODO(POD_MEMBER_NAMES) item: the solo developer
owns all six specs and runs each spec's full lifecycle sequentially in dependency order.

2. Engineering-tooling change (updates Principle II and any other mention of GitHub
Copilot as the development engine): the AI engineering engine is Claude Code, driving the
GitHub Spec Kit lifecycle (/speckit-* skills) and implementation. GitHub remains the
delivery platform — repository, Actions CI/CD, Issues, branch protection, and gh-aw
agentic workflows. The product runtime rule is unchanged: all runtime components are
AWS-native and the product GenAI layer is Amazon Bedrock Agents exclusively — Claude Code
is a development-time tool and is never a runtime dependency of the platform.

Update the Sync Impact Report, bump the version with today's date, and propagate the
terminology change (POD → solo developer + AI agents) through the governance and workflow
sections without weakening any testable requirement except the human-approval gate
described above.
```

---

## 2. `/speckit-specify` — six runs, in dependency order

> Run each from `pods/pod73` (pull first). Spec Kit creates the numbered branch and spec file;
> rename the branch per §0.2. Keep the inputs functional — the tech stack is decided in
> `/speckit-plan`.

### Spec 1 — platform-foundation ✅ *(complete through `/speckit-analyze` + remediation — 2026-08-22)*

> Artifacts: `specs/001-platform-foundation/` — spec.md (73 FR, 17 SC), plan.md, research.md
> (12 decisions, 4 carrying **VERIFY** markers), data-model.md (10 entities, 8 migrations),
> contracts/openapi.yaml, quickstart.md (V1–V9), checklists/{requirements,scope-and-contracts}.md,
> tasks.md (128 tasks; P1 = T001–T113, P2 = T114–T122).
>
> **Clarify answers that became binding decisions for later specs:** federated sign-in only with
> the role derived from directory group membership (no self-service registration, no platform-side
> role store); prod data is not disposable (teardown is dev-only, deletion protection, daily
> backups); retention per class (audit indefinite, logs 30 days, backups 7 days); the API contract
> is **unversioned and additive-only** with a CI breaking-change gate; accessibility baseline plus
> automated linting in the frontend build.
>
> **Boundaries spec 1 fixed that specs 2–6 must build against:** FR-054 reserves the connector
> package and forbids provider SDK types leaking out of it — **spec 2 defines the protocol itself
> (S11), spec 1 deliberately does not**. FR-055 delegates finding-lifecycle states and SDA
> grouping semantics to spec 3. FR-056 requires agent action groups to reach data only through a
> read-only, tenant-scoped API principal — spec 6 implements against it and may not bypass it.

**Input used:**

```
Build the engineering and operational foundation of CloudPulse AI, an internal cloud
governance platform operated by a small platform team, so that all product features can be
developed, deployed, and observed safely by a solo developer working with AI agents.

Users and roles: platform users sign in with organizational identity and hold exactly one
role — admin (manage accounts, rules, SDAs), operator (run scans, work findings), or viewer
(read-only dashboards). Unauthenticated users see nothing.

Functional scope (backlog S1–S7):
- Reproducible environments: the entire platform can be provisioned from scratch in a fresh
  cloud account for two environments (dev, prod) from versioned definitions (S1) [P1].
- Continuous integration: every pull request is automatically checked — code style, static
  typing, backend unit tests with mocked cloud APIs, frontend build, and infrastructure
  validation — and a failing check blocks merge (S2) [P1].
- Continuous delivery: merges to the trunk deploy dev automatically, including database
  schema migrations; production deployment requires an explicit approval gate (S3) [P1].
- Governance data store: a relational store with a versioned, migratable schema covering
  tenants, accounts, resources, rules, findings, owners, SDAs, scans, and audit events;
  an ERD is kept in the repo (S4) [P1].
- Identity: user sign-up/sign-in with the three roles above; role claims are enforced on
  every API call (S5) [P1].
- API skeleton: a health-checked, structured-logging API service with a uniform error
  envelope, reachable from the web frontend (S6) [P1].
- Observability: a service dashboard with alarms on API errors, scan failures, and dead
  letter queues, with email alerts to the developer (S7) [P2].

Success criteria: a brand-new cloud account reaches a working dev environment in under one
hour using only the repo; a broken test provably blocks a merge; a forced failure raises an
alert. Out of scope: any product feature behavior (owned by specs 2–6), email notifications
to resource owners (cut from MVP).
```

### Spec 2 — account-onboarding-and-discovery

```
Enable an operator to connect AWS accounts to CloudPulse AI using roles only, and give the
platform a complete, continuously refreshed inventory of everything that exists in those
accounts — without maintaining a hardcoded service list.

Functional scope (backlog S8–S17, S47 + AI-ready coverage):
- Roles-only access (S8) [P1]: two connection modes — same-account (platform scans the
  account it lives in via a local read-only role) and cross-account (target account deploys
  a provided template creating a read-only scanner role protected by an ExternalId). Access
  keys are rejected by design.
- Account registration (S9) [P1]: add an account with mode, role reference, and scan-region
  list (default us-east-1); registration verifies access with a dry-run and rejects bad
  roles/regions with clear errors; regions editable later.
- Accounts admin page (S10) [P1]: list, add, verify accounts and see per-account scan status
  — an operator onboards without touching the AWS console except deploying the template.
- Normalized resource model + connector contract (S11) [P1]: one provider-agnostic resource
  shape (provider, account, unique id, service, native type, region, name, tags, state,
  created time, extra detail) so non-AWS providers can be added later without core changes.
- Whole-account discovery (S12 evolved) [P1]: the sweep enumerates ALL resource types
  present in the account using the cloud provider's generic discovery surfaces — coverage
  is not limited to a hand-picked service list. Tagged and untagged resources are found.
- Deep enrichment for governance-critical services (S13, S14, S47) [P1 for compute/storage/
  database/serverless: EC2, EBS, EIP, S3, RDS, Lambda; P2 for EKS, DynamoDB, ELB, IAM
  inventory]: state, size/class, attachment, runtime, and creation details.
- Coverage-as-data [P1 foundation]: which resource types are enriched, and how, is
  configuration data — new coverage ships without code changes. (The AI coverage advisor
  that proposes such extensions lives in the ai-insights-agent spec.)
- Scan orchestration (S15) [P1]: scans fan out per account × region × service group with
  retries and concurrency limits; a daily schedule plus on-demand trigger from the UI.
- Persistence with lifecycle (S16) [P1]: every scan stores a raw immutable snapshot and
  updates current state with diffing — resources get first-seen/last-seen/deleted markers,
  and disappearance auto-closes related findings.
- Scan history (S17) [P2]: per-scan record of trigger, duration, counts, and status,
  exposed via API.

Success criteria: a fresh account is onboarded in under 5 minutes; a scan of that account
lands >95% of its actual resources (validated by manual sampling) including untagged ones;
deleting a resource in AWS closes it in inventory on the next scan; cross-account access
fails closed without the ExternalId. Out of scope: tag validation (spec 3), any write
access to scanned accounts, non-AWS providers (interface only).
```

### Spec 3 — tag-compliance-and-ownership

```
Turn the raw inventory into governance signal: validate every resource against the
organization's tagging standards, group resources by the SDA (internal project) they belong
to, attribute a human owner to every resource, and score compliance.

Functional scope (backlog S18, S18a, S18b, S19, S20, S21, S22, S23a):
- Rules-as-data (S18) [P1]: tagging rules (case-insensitive keys, required set, allowed
  values) live in an admin-editable store seeded with the four mandatory tags —
  project_name, owner, project_id, created_by (environment optional). A rule change takes
  effect on the next scan with no deployment.
- SDA registry (S18a) [P1]: admins register SDAs (name, owner email, team, and the tag
  values that map to them); resources attach to their SDA at load time; unmatched resources
  land in a visible "No SDA" bucket.
- SDA admin UI (S18b) [P2]: CRUD, tag-value mapping editor, and a "No SDA" triage list;
  registering an SDA reclassifies matching resources on the next scan.
- Validation engine (S19) [P1]: evaluates rules on parent resources only; opens findings
  for missing tags, invalid values, and non-standard formats; dedupes; auto-closes a
  finding when a re-scan shows the tag fixed.
- Compliance scoring (S20) [P1]: score per account and per SDA = compliant parents / total
  parents, exposed via API and matching a hand count on a test account.
- Ownership attribution (S21) [P1]: for each resource, mine 90 days of cloud audit events
  for the creator; when the creator is a human principal, record them as owner with
  evidence.
- Attribution fallback (S22) [P2]: when the creator is a pipeline/automation identity, fall
  back to the most frequent human modifier (≥3 write events) with a confidence level and
  stored evidence; otherwise queue as unattributed.
- Owner identity resolution (S23a) [P2]: resolve owners to an email via a chain — owner tag
  if it is an email, else a configurable pattern over the audit-trail user id, else a manual
  override table; the pattern is configuration, not code.

Success criteria: a rule edit changes findings on the next scan without redeploy; a fixed
tag auto-closes its finding; compliance score matches a manual count; creator attribution
succeeds for console-created test resources and the fallback chain is exercised by an
IaC-created resource. Out of scope: notifying owners (cut from MVP — findings are visible
on the dashboard only), remediation execution, AI suggestions (spec 6).
```

### Spec 4 — governance-dashboard

```
Give admins, operators, and viewers a single web dashboard where the entire governance
story is visible: compliance posture, full inventory, findings with AI-suggested fixes,
and scan operations.

Functional scope (backlog S27–S31, S33; renders spec 6's suggestions):
- Authenticated shell (S27) [P1]: sign-in/sign-out against the platform identity service,
  role-based navigation guards (viewer never sees admin pages), responsive layout shell.
- Compliance overview (S28) [P1]: score cards, findings by type/severity charts, and a
  per-account summary table; numbers always match the API; loads under 2 seconds at 5,000
  resources.
- Inventory explorer (S29) [P1]: server-side paged and filtered table (account, service,
  region, tag status, SDA), with a resource detail panel showing tags, owner + evidence,
  findings, and enrichment detail; filter "missing owner tag" returns the correct set.
- Findings workbench (S30) [P1]: list/filter findings, acknowledge them, and see each
  finding's AI remediation suggestion with its blast-radius note (produced by the
  ai-insights-agent spec) inline; acknowledging updates status immediately.
- Scan operations (S31) [P2]: scan history page (last run, duration, deltas) and an
  on-demand "Scan now" button with live status.
- Hardening (S33) [P2]: end-to-end smoke tests for the P1 journeys, empty/error states,
  deployment polish; e2e runs in CI against dev after each deploy.

Success criteria: a viewer, operator, and admin each see exactly their permitted surface;
the full demo path (onboard → scan → findings + suggestions → acknowledge) is walkable
end-to-end in the UI without console access. Out of scope: notification bell/feed (cut),
approval workflows (no remediation execution in MVP), cost and utilization pages (spec 5),
agent chat interfaces.
```

### Spec 5 — cost-and-utilization

```
Add the financial-control dimension: what is each SDA/project spending, are budgets being
respected, how well utilized are sandbox accounts, and where is IAM hygiene rotting.

Functional scope (backlog S39–S42, S54–S56):
- Spend ingestion (S39) [P1]: daily spend by project tag, account, and service (24h
  granularity) ingested into the governance store; totals match the cloud provider's cost
  console within ±1%.
- Cost dashboard (S42) [P1]: spend by project/SDA/environment with trend charts, budget vs
  actual, and drill-down from org total to a single resource's spend.
- Auto-budgets (S40) [P2]: a budget is auto-created per registered project (80%/100%
  actual + forecast alerts); a newly registered project has its budget within a day.
- Overrun findings (S41) [P2]: budget overruns become findings in the standard findings
  pipeline with the same lifecycle (open/acknowledge/close), visible on the findings
  workbench (no email — notifications are cut from MVP).
- Sandbox utilization (S54, S55) [P2]: utilization % (used vs provisioned) per account and
  project, with a documented formula matching manual calculation, and drill-down pages
  (account → project → resource) reachable in ≤3 clicks.
- IAM hygiene (S56) [P2]: unused IAM roles/users/keys detected via last-used analysis and
  access patterns, producing flag-only cleanup recommendations (never auto-delete); zero
  false "unused" flags on active roles in the test account.

Success criteria: spend reconciles within ±1%; an overrun surfaces as a finding within a
day; utilization matches a hand calculation. Depends on: inventory (spec 2), findings
pipeline + SDA registry (spec 3), dashboard shell (spec 4). Out of scope: rightsizing and
forecasting (spec 6), cost-saving execution of any kind.
```

### Spec 6 — ai-insights-agent

```
Build the platform's intelligence layer as Amazon Bedrock Agents: AI that observes the
governance data, explains it, predicts it, and proposes improvements — while never
executing changes or touching cloud credentials. This is the AWS-native agentic showcase
of the MVP.

Agent capabilities (backlog S43, S44, S50–S53 + discovery coverage advisor):
- Insight digest (S43) [P1]: a nightly agent run analyzes top findings, compliance
  movement, and cost deltas and produces a plain-language digest rendered as a dashboard
  card; every ARN and number in the digest is validated against the governance store —
  fabricated references are rejected before display.
- Remediation suggester (S44) [P1]: for each finding class, the agent drafts the
  recommended fix plus a blast-radius note; suggestions render on the findings workbench
  next to each finding; humans decide — the agent has no execution path.
- Discovery coverage advisor (new) [P2]: the agent reviews inventory composition, detects
  resource types present in accounts but not yet enriched or governed, and proposes
  coverage/enrichment/rule extensions as configuration changes an admin can accept
  (leveraging spec 2's coverage-as-data and spec 3's rules-as-data).
- Metrics collection (S50) [P2]: utilization metrics (CPU, memory, network, storage) for
  compute and database resources are collected into a metrics store — the deterministic
  data feed for prediction.
- Forecasting (S51) [P2]: per-project spend and capacity forecasts with accuracy
  backtesting (target: MAPE < 15% on test projects).
- Rightsizing recommendations (S52) [P2]: instance-class recommendations with evidence and
  monthly savings estimate per recommendation.
- Forecast narratives (S53) [P2]: agent-written narratives on cost/forecast pages whose
  numbers match the charts exactly.

Constraints (constitution Principle IV): agents are read-only consumers of platform APIs
via typed, tenant-scoped tools; agents hold no cloud credentials; all agent outputs are
grounded in retrieved platform data and validated before display; agent runs have cost
caps and their prompts/definitions are versioned in the repo with an eval suite in CI.

Success criteria: the nightly digest cites only real resources; a suggestion appears for
every open finding class; an admin can accept a coverage proposal and see it take effect on
the next scan without a code change. Out of scope: natural-language Q&A chat, weekly
emails, remediation execution.
```

---

## 3. `/speckit-clarify` — run per spec, no arguments

Run it on each spec branch before planning. It asks up to ~5 targeted questions; answer
from this decision log (already settled — don't re-open):

| Likely question | Settled answer |
|---|---|
| Notification/email behavior? | Cut from MVP. Findings are dashboard-visible only. |
| Remediation execution? | Never in MVP. Suggestions only, rendered on findings page. |
| Multi-cloud? | AWS only at runtime; connector interface must stay provider-agnostic. |
| Tenancy? | Single internal tenant, but every entity carries tenant scoping for SaaS later. |
| Auth roles? | admin / operator / viewer, exactly three. |
| Mandatory tags? | project_name, owner, project_id, created_by; environment optional; keys case-insensitive; parent resources only. |
| Discovery breadth? | Whole account via generic discovery surfaces; enrichment depth per coverage-as-data config. |
| AI runtime? | Amazon Bedrock Agents, read-only tools, grounded outputs, no credentials. |
| Scan cadence? | Daily scheduled + on-demand from UI. |
| Regions? | Per-account region list, default us-east-1; global services once per account. |
| Priorities? | P1/P2 tiers as written in the spec; P1 frozen. |

If clarify surfaces something genuinely new, decide, record the answer in the spec, and
add one line to the journal.

---

## 4. `/speckit-plan` — paste this (per spec, after clarify)

Use the same technology direction for every spec so the plans compose into one system.
Prefix the input with the spec name.

```
Create the implementation plan for this spec. Technology direction for the whole platform
(constitution Principles II–V apply — AWS-native runtime, GitHub-native delivery):

- Backend: Python 3.12 on AWS Lambda (arm64). FastAPI + Mangum as a single API Lambda
  behind API Gateway HTTP API. Pydantic v2 models everywhere; AWS Lambda Powertools for
  structured logging, tracing, metrics.
- Discovery engine: Resource Groups Tagging API sweep + AWS Cloud Control API
  (ListResources over the CloudFormation resource-type registry) for whole-account
  enumeration without per-service code; targeted boto3 describes for deep enrichment of
  governance-critical services. Coverage definitions stored as data.
- Orchestration: AWS Step Functions Map fan-out per account × region × service group;
  EventBridge Scheduler for daily scans; SQS + Lambda workers for validation, ownership,
  and cost ingestion.
- Data: Aurora Serverless v2 PostgreSQL (SQLAlchemy 2 + Alembic migrations, run in CD);
  raw scan snapshots as immutable JSON in S3. Every table tenant-scoped.
- Identity: Amazon Cognito user pool (admin/operator/viewer groups), JWT authorizer on
  API Gateway.
- Frontend: Angular 18 (standalone components, signals) + Angular Material + ng2-charts,
  hosted on S3 + CloudFront; OpenAPI-generated client from the FastAPI schema.
- GenAI: Amazon Bedrock Agents (Claude models on Bedrock) with action groups implemented
  as Lambda functions calling tenant-scoped read-only platform APIs; agent definitions,
  prompts, and evals versioned in-repo; Bedrock Guardrails + cost alarms.
- Access model: roles-only — local read-only role (same-account) or AssumeRole +
  ExternalId (cross-account); GitHub OIDC federation for CI/CD; zero stored credentials.
- IaC & CI/CD: Terraform (modules per component, envs dev/prod) + GitHub Actions
  (ci.yml on PR: ruff, mypy, pytest+moto, Angular build, terraform validate/plan;
  deploy-dev.yml on merge; deploy-prod.yml behind environment approval). All workflow
  triggers target the pods/pod73 trunk — never main/master.
- Testing: pytest + moto for unit, LocalStack for integration in CI, Playwright for the
  P1 dashboard journeys.

Honor the P1/P2 tiers from the spec: the plan must sequence P1 work so it is deliverable
without any P2 item. Follow the monorepo layout: infra/ (Terraform), backend/ (app/api,
app/workers, app/scan, connectors/, migrations, tests), frontend/ (Angular), agents/
(Bedrock agent definitions, action-group lambdas, prompts, evals), ops/, .github/.
```

> For **spec 1** append: "This spec owns the monorepo scaffold, Terraform baseline, CI/CD
> pipelines, Cognito, Aurora, and the API skeleton that all other specs consume."
> For **spec 6** append: "This spec owns the agents/ directory and all Bedrock Agent
> resources; action groups may only call APIs delivered by specs 2, 3, and 5."

---

## 5. `/speckit-checklist` (optional, after plan) — paste this

```
Generate a requirements-quality checklist for this spec focusing on: P1/P2 tier
completeness, testability of every acceptance criterion, absence of out-of-scope leakage
(notifications, remediation execution, non-AWS AI runtimes), and cross-spec contract
consistency (connector interface, findings lifecycle, SDA grouping, agent tool surface).
```

## 6. `/speckit-tasks` — paste this (per spec)

```
Generate the task list. Order tasks so the P1 demo path completes first; every P2 task is
clearly marked and scheduled after P1. Each task must reference its backlog story ID
(S-numbers) and spec requirement, include its test task (unit/integration/e2e as
appropriate per the constitution's quality gates), and be sized for a single short-lived
branch and same-day PR.
```

## 7. `/speckit-taskstoissues` — run per spec, no special input

Converts tasks to GitHub Issues. Label by spec and P1/P2. Solo, this is optional but
recommended: it feeds the issue-triage agentic workflow and gives judges a visible,
dependency-ordered board of how the work was planned and burned down.

## 8. `/speckit-analyze` — run per spec, no arguments

Cross-checks spec ↔ plan ↔ tasks ↔ constitution. Fix every CRITICAL finding before
implementation; journal one line per run ("analyze found X, fixed Y").

> **What spec 1's run actually caught (2026-08-22) — expect the same shapes in specs 2–6.**
> 15 findings, 2 CRITICAL, FR coverage 92% before / 100% after. The recurring patterns:
>
> 1. **Tasks that build things no requirement asked for.** Spec 1's plan put a connector
>    interface in the tree; no FR required it. Fix was to *delegate* (FR-054 → spec 2 owns S11),
>    not to widen scope. When plan.md invents a file, check the spec asked for it.
> 2. **Detail that first appears in `data-model.md` instead of the spec.** Finding lifecycle
>    states and SDA semantics were settled in the data model and nowhere in the requirements.
> 3. **Edge cases with no matching requirement.** Six of spec 1's edge cases had no FR behind
>    them — they read as covered but nothing was testable.
> 4. **Vague adjectives that survive clarify.** "known, serviceable state", "precisely enough to
>    act on", "no unintended changes" all passed the earlier gates and only failed here.
> 5. **Constitution MUSTs enforced by a README rather than CI.** Principle II had no gate until
>    FR-013a added one.
> 6. **Ordering contradictions inside `tasks.md`** — a Phase-5 task depending on a Phase-6 module.
>
> Run analyze *before* the PR, not after: fixing 15 findings changed the spec, plan, tasks, both
> checklists, and the journal together, and that is much cheaper as one commit than as a follow-up.

## 9. `/speckit-implement` — paste this (per task or task group)

```
Implement task(s) <TASK-IDs> from the tasks list. Work on the current feature branch only.
Follow the constitution: typed contracts, tests written with the code (pytest+moto for
cloud-touching code), structured logging, no credentials or secrets in code, rules and
coverage as data. Stop and report if the implementation would deviate from the spec or
plan instead of silently improvising.
```

Solo loop per task: branch off `pods/pod73` as `pods/pod73-<task-id>-<slug>` →
`/speckit-implement` in Claude Code → push → PR into `pods/pod73` (reference issue + spec)
→ automated AI review + green CI → self-merge → next task. Journal daily, not per-PR.

## 10. `/speckit-converge` — paste this (end of sprint)

```
Assess the implemented codebase against all six specs and the constitution. Report: spec
coverage per feature (P1 vs P2), constitution violations, dead or duplicated code,
missing tests against the quality gates, and contract drift between OpenAPI schema and
the Angular client. Append remaining work as tasks; do not silently expand scope.
```

Feed the output into the final `AI_WORKFLOW_JOURNAL.md` section — this is direct evidence
for the "engineering maturity" criterion.

---

## 11. After specs exist: GitHub Agentic Workflows

Five workflows (four adapted/stock from githubnext/agentics + journal drafter), each a
markdown workflow compiled with `gh aw compile`. Solo, these are your teammates — enable
them right after the six specs merge (§0.4 step 13):

| # | Workflow | Source | Trigger |
|---|---|---|---|
| 1 | Issue Triage | agentics `issue-triage`, adapted to spec + P1/P2 taxonomy | issue opened |
| 2 | Contribution Guidelines Checker | agentics stock + `CONTRIBUTING.md` distilled from the constitution | PR opened/updated |
| 3 | CI Doctor | agentics stock | Actions run failure |
| 4 | Duplicate Code Detector | agentics stock | daily schedule |
| 5 | Daily Progress & Journal Drafter | agentics `daily-progress`, adapted to draft journal entries | daily schedule |

Notes:
- **#2 is the PR merge gate's AI reviewer** (with GitHub Copilot code review as an
  alternative/addition if available on the repo) — never throttle it.
- **Engine:** gh-aw workflows default to the Copilot engine; gh-aw also supports
  `engine: claude` (requires an `ANTHROPIC_API_KEY` repo secret) — pick per workflow based
  on available quota/keys. Either choice keeps the workflows GitHub-native.
- If quota tightens, demote #4 to every-other-day; #2 stays.
- Skipped by decision: ci-coach, doc-updater (conflicts with spec-first), repository-
  quality-improver (overlaps analyze/converge — at most run manually before converge),
  repo-assist (fights frozen P1 scope). Optional stretch: AgentMeter log-watcher adapted
  to monitor these five — an "we govern our agents" story if time allows.
