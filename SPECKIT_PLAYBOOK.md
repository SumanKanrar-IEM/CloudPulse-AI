# CloudPulse AI — Spec Kit Playbook (GitHub Copilot Edition)

> Copy-paste inputs for every `/speckit-*` command, in execution order, for the CloudPulse AI MVP.
> Scope source: color-coded stories in `docs/CloudPulse-AI_Backlog.xlsx` (scope v2 — see §0.2).
> Audience: the 6-person POD running GitHub Copilot in VS Code against this repo.

---

## 0. Ground rules before any command

### 0.1 Working agreement

- **Branching:** trunk-based. `pods/pod73` is the only long-lived branch and the target of every PR. All short-lived branches follow the naming pattern `pods/pod73-XXX` (e.g. `pods/pod73-001-platform-foundation`, `pods/pod73-T042-scan-diffing`). Every spec and every task slice happens on such a branch → PR into `pods/pod73` → Copilot review → merge within hours.
- **Repo settings (do once):** on GitHub, set `pods/pod73` as the repository **default branch** so PRs auto-target it, and protect it (require the CI check + 1 review, no direct pushes). All GitHub Actions triggers must reference `pods/pod73`, not `main`.
- **Spec ownership:** six specs, six POD members — each member owns exactly one spec and runs its full speckit lifecycle (specify → clarify → plan → tasks → implement). The constitution is written once, together.
- **Journal:** after every speckit phase, the person who ran it appends the outcome to `AI_WORKFLOW_JOURNAL.md` (structure already prepared).
- **Spec Kit mechanics:** `/speckit-specify` auto-creates a numbered feature branch (e.g. `001-platform-foundation`) and `specs/001-platform-foundation/spec.md`. Immediately rename the branch to match the POD pattern before pushing:
  `git branch -m 001-platform-foundation pods/pod73-001-platform-foundation`
  The spec directory name keeps its `001-...` form. If a later speckit command on the renamed branch complains it cannot detect the feature branch, set the `SPECIFY_FEATURE` environment variable to the spec directory name (e.g. `SPECIFY_FEATURE=001-platform-foundation`) before running it. Merge each spec PR into `pods/pod73` promptly so later specs and plans can reference it.

### 0.2 MVP scope v2 (the single source of truth for "what's in")

| In | Stories |
|---|---|
| Platform foundation | S1–S7 |
| Onboarding | S8–S10 |
| Discovery | S11–S17, S47, **AI-planned whole-account coverage (new)** |
| Compliance + SDA + ownership | S18, S18a, S18b, S19, S20, S21, S22, S23a |
| Dashboard | S27–S31, S33 (S44 suggestions render on the findings page) |
| Cost + utilization | S39–S42, S54–S56 |
| AI insights (Amazon Bedrock Agents) | S43, S44, S50–S53, coverage advisor |

**Out (do not let any spec re-import these):** S32, E6 Notification Engine (S24–S26) — intentional cut, findings visibility is dashboard-only; E8 remediation execution (S34–S38); S45, S46, S48, S49; S57–S63.

**Priority tiers (baked into every spec):**
- **P1 (demo-critical path):** onboard account → whole-account scan → findings + compliance score + ownership → dashboard (overview, inventory, findings) → Bedrock Agent digest + remediation suggestions → basic cost view. Roughly: S1–S6, S8–S12, S13–S16, S18, S18a, S19–S21, S27–S30, S39, S42, S43, S44.
- **P2 (stretch, never blocks P1):** S7, S17, S18b, S22, S23a, S31, S33, S40, S41, S47, S50–S56, coverage advisor.

### 0.3 Recommended run order

```
Day 1        /speckit-constitution                       (whole POD, one session)
Day 1–2      /speckit-specify  × 6                       (owners in parallel; merge spec PRs fast)
Day 2        /speckit-clarify  per spec                  (owner answers from §5 cheat sheet)
Day 2–3      /speckit-plan     per spec                  (spec 1 first — it is the dependency root)
Day 3        /speckit-checklist per spec (optional but cheap evidence of rigor)
Day 3        /speckit-tasks    per spec
Day 3        /speckit-taskstoissues per spec             (assign to owners on the GitHub board)
Day 3        /speckit-analyze  per spec                  (fix findings before coding)
Day 4–13     /speckit-implement in task slices           (branch → PR → Copilot review → merge)
Day 13–14    /speckit-converge                           (audit vs constitution, final journal)
```

---

## 1. `/speckit-constitution` — paste this

```
Create the CloudPulse AI constitution. Context: CloudPulse AI is a serverless cloud
governance, cost & compliance platform for AWS, built by a 6-person POD in a 2-week
hackathon that is judged on AI-native engineering practices, spec-driven development,
architectural discipline, coding standards, modularity, and POD collaboration — not on
business value. Derive the principles below, keep them declarative and testable, and
version it 1.0.0 with today's ratification date.

Principle I — Spec-First Delivery. No production code exists without a merged spec, plan,
and tasks that trace to it. Specs are the source of truth; when code and spec disagree, the
spec is corrected first via PR. Every speckit phase outcome is recorded in
AI_WORKFLOW_JOURNAL.md by the person who ran it.

Principle II — AWS-Native and GitHub-Native, exclusively. All runtime components run on
AWS managed services; the GenAI layer is implemented with Amazon Bedrock Agents (agents,
action groups, guardrails) — no third-party model hosts, no non-AWS agent frameworks.
All engineering tooling is GitHub-native: GitHub Actions, GitHub Copilot, GitHub Spec Kit,
GitHub Issues/Projects. Nothing may depend on any other AI vendor's runtime.

Principle III — Zero Stored Credentials. Cloud access is IAM-roles-only (same-account
local role or cross-account AssumeRole with ExternalId). The platform never stores access
keys, secrets in code, or long-lived credentials; CI/CD authenticates to AWS via GitHub
OIDC federation only. Scanning permissions are read-only. Every privileged or state-changing
operation writes an immutable audit record.

Principle IV — Deterministic Core, Agentic Edge. Discovery, validation, scoring, and cost
ingestion are deterministic and reproducible: the same account state always yields the same
inventory and findings. Bedrock Agents observe, explain, recommend, and propose
configuration (rules-as-data) — they never execute changes against cloud accounts, never
hold credentials, and every agent output shown to users must be grounded in and validated
against platform data (real ARNs, real numbers only).

Principle V — Contract-First Modularity. Typed contracts at every boundary: OpenAPI schema
is the frontend/backend contract; a provider-agnostic connector interface with a normalized
resource model isolates cloud specifics; tag rules, SDA mappings, coverage definitions, and
agent-proposed extensions are data, not code. New providers, rules, or resource types must
ship without modifying core code.

Principle VI — Test and Quality Gates. Every merge to pods/pod73 passes lint, type checks,
unit tests, and (for cloud-touching code) integration tests with mocked AWS in CI. Each
story's definition of done includes tests, structured logs, and updated docs. CI is
required — a red check blocks merge, no exceptions.

Principle VII — Trunk-Based POD Collaboration. pods/pod73 is the only long-lived branch
and is always releasable; every pull request targets it, and all working branches follow
the pods/pod73-XXX naming pattern. Work happens on short-lived branches merged via PR the
same day where possible; every PR gets a GitHub Copilot review plus one human review; PRs
stay small and reference their spec/task IDs. Each of the six feature specs has a single
named owner from the six-member POD.

Principle VIII — Honest Prioritization. Every requirement carries a P1 (demo-critical) or
P2 (stretch) tier. P1 scope is frozen; new ideas enter as P2 or post-MVP. P2 work never
blocks or destabilizes the P1 demo path.

Also define: governance section (constitution supersedes ad-hoc practice; amendments via PR
approved by the whole POD), and a compliance expectation that /speckit-analyze and PR
reviews check work against these principles.
```

---

## 2. `/speckit-specify` — six runs (owner in parentheses)

> Run each from `pods/pod73` (pull first). Spec Kit will create the numbered branch and spec file.
> Keep the inputs functional — the tech stack is decided later in `/speckit-plan`.

### Spec 1 — platform-foundation (DevOps)

```
Build the engineering and operational foundation of CloudPulse AI, an internal cloud
governance platform operated by a small platform team, so that all product features can be
developed, deployed, and observed safely by a 6-person POD.

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
  letter queues, with email alerts to the POD (S7) [P2].

Success criteria: a brand-new cloud account reaches a working dev environment in under one
hour using only the repo; a broken test provably blocks a merge; a forced failure raises an
alert. Out of scope: any product feature behavior (owned by specs 2–6), email notifications
to resource owners (cut from MVP).
```

### Spec 2 — account-onboarding-and-discovery (BE2)

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

### Spec 3 — tag-compliance-and-ownership (BE1)

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

### Spec 4 — governance-dashboard (FE)

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

### Spec 5 — cost-and-utilization (BE3 / full-stack)

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

### Spec 6 — ai-insights-agent (AI engineer)

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

If clarify surfaces something genuinely new, decide as a POD, record the answer in the
spec, and add one line to the journal.

---

## 4. `/speckit-plan` — paste this (per spec, after clarify)

Use the same technology direction for every spec so the plans compose into one system.
Prefix the input with the spec name.

```
Create the implementation plan for this spec. Technology direction for the whole platform
(constitution Principles II–V apply — AWS-native runtime, GitHub-native tooling):

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

Converts tasks to GitHub Issues. Then, on the GitHub board: label by spec, assign to the
spec owner, add P1/P2 labels. This is the POD's visible collaboration surface for judges.

## 8. `/speckit-analyze` — run per spec, no arguments

Cross-checks spec ↔ plan ↔ tasks ↔ constitution. Fix every CRITICAL finding before
implementation; journal one line per run ("analyze found X, fixed Y").

## 9. `/speckit-implement` — paste this (per task or task group)

```
Implement task(s) <TASK-IDs> from the tasks list. Work on the current feature branch only.
Follow the constitution: typed contracts, tests written with the code (pytest+moto for
cloud-touching code), structured logging, no credentials or secrets in code, rules and
coverage as data. Stop and report if the implementation would deviate from the spec or
plan instead of silently improvising.
```

POD loop per task: branch off `pods/pod73` as `pods/pod73-<task-id>-<slug>` →
`/speckit-implement` → push → PR into `pods/pod73` (reference issue + spec) → Copilot
review + 1 human review → merge → next task.

## 10. `/speckit-converge` — paste this (end of week 2)

```
Assess the implemented codebase against all six specs and the constitution. Report: spec
coverage per feature (P1 vs P2), constitution violations, dead or duplicated code,
missing tests against the quality gates, and contract drift between OpenAPI schema and
the Angular client. Append remaining work as tasks; do not silently expand scope.
```

Feed the output into the final `AI_WORKFLOW_JOURNAL.md` section (§4 Assessment &
Convergence) — this is direct evidence for the "engineering maturity" criterion.

---

## 11. After specs exist: GitHub Agentic Workflows

Proposed minimal high-impact set (adapted from githubnext/agentics), to be added once
specs are merged — each is a markdown workflow compiled with `gh aw compile`:

1. **Issue triage** — labels/annotates new issues against spec + P1/P2 taxonomy.
2. **PR quality reviewer** — reviews PRs against the constitution (complements the
   built-in Copilot review).
3. **CI doctor** — investigates failed Actions runs and comments root cause + fix.
4. **Daily progress & journal** — summarizes merged PRs/closed issues per spec into a
   daily report and drafts the AI_WORKFLOW_JOURNAL entry.

These will be detailed in a separate follow-up once the six specs are on `pods/pod73`.
