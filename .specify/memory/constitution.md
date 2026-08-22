<!--
Sync Impact Report
==================
Version change: 1.0.0 → 2.0.0 (2026-08-22)
Bump rationale: MAJOR. Principle VII is redefined from six-member POD collaboration to solo
delivery with AI collaboration, and Principle II is widened to name Claude Code as the permitted
development-time engine. Both redefinitions invalidate wording that earlier work was written
against (six named spec owners, mandatory second-human review), which is precisely the MAJOR
trigger in the versioning policy below.

Modified principles:
  - II. AWS-Native and GitHub-Native → II. AWS-Native Runtime and GitHub-Native Delivery
    (adds Claude Code as the permitted development-time Spec Kit engine; keeps the product
    GenAI layer restricted to Amazon Bedrock Agents; keeps every non-AWS AI runtime out of the
    deployed system)
  - VII. Trunk-Based POD Collaboration → VII. Solo Trunk-Based Delivery with AI Collaboration
    (single maintainer; automated AI review replaces the second-human merge gate; the six-owner
    table is removed and spec ownership becomes sequential authorship)
  - VIII. Honest Prioritization (amended: "recorded POD amendment" → "recorded amendment")

Resolved from v1.0.0:
  - TODO(POD_MEMBER_NAMES) is removed rather than filled — there is no POD to name.

Governance changes:
  - Amendment approval moves from "all six POD members" to the sole maintainer, recorded in
    AI_WORKFLOW_JOURNAL.md §1
  - Compliance wording updated for automated AI review

Added sections: none · Removed sections: spec-ownership table under Principle VII

--- Superseded v1.0.0 report ---
Version change: (unratified template) → 1.0.0
Bump rationale: Initial ratification. The previous file was an unpopulated scaffold with no
adopted principles, so this is the first governing version rather than an amendment.

Modified principles: none (no prior named principles existed)

Added principles:
  - I. Spec-First Delivery
  - II. AWS-Native and GitHub-Native (NON-NEGOTIABLE)
  - III. Zero Stored Credentials (NON-NEGOTIABLE)
  - IV. Deterministic Core, Agentic Edge
  - V. Contract-First Modularity
  - VI. Test and Quality Gates
  - VII. Trunk-Based POD Collaboration
  - VIII. Honest Prioritization

Added sections:
  - Technology and Security Constraints (template slot SECTION_2)
  - Development Workflow and Quality Gates (template slot SECTION_3)
  - Governance

Removed sections: none

Template placeholders resolved: PROJECT_NAME, PRINCIPLE_1..5_NAME/_DESCRIPTION (extended to
eight principles per adopted scope), SECTION_2_NAME/_CONTENT, SECTION_3_NAME/_CONTENT,
GOVERNANCE_RULES, CONSTITUTION_VERSION, RATIFICATION_DATE, LAST_AMENDED_DATE.

Deferred TODOs:
  - TODO(POD_MEMBER_NAMES): the six named spec owners in Principle VII are recorded by role
    only; replace each role slot with the owning POD member's name in the first amendment
    (PATCH bump) once ownership is confirmed in AI_WORKFLOW_JOURNAL.md §0.
-->

# CloudPulse AI Constitution

CloudPulse AI is a serverless cloud governance, cost, and compliance platform for AWS, built by
a six-person POD. This constitution governs how the platform is specified, built, reviewed, and
merged. It is optimized for demonstrable engineering discipline — spec-driven development,
architectural integrity, coding standards, modularity, and POD collaboration.

## Core Principles

### I. Spec-First Delivery

No production code exists without a merged spec, plan, and tasks that trace to it. Every source
file MUST be attributable to a task ID, every task to a plan, and every plan to a spec in
`specs/`. Specs are the single source of truth: when code and spec disagree, the spec MUST be
corrected first, via its own pull request, before the code is changed. Every speckit phase
outcome MUST be recorded in `AI_WORKFLOW_JOURNAL.md` by the person who ran that phase, on the
day they ran it.

Testable: a reviewer can name the spec ID and task ID behind any merged change; no PR merges
that introduces application behavior with no referenced task; no journal section is left with an
unfilled outcome after its phase completes.

Rationale: the POD is judged on spec-driven development. Specs that lag behind code are
evidence of the opposite, and a journal written after the fact is not evidence at all.

### II. AWS-Native Runtime and GitHub-Native Delivery (NON-NEGOTIABLE)

**Runtime.** All runtime components MUST run on AWS managed services. The entire product GenAI
layer MUST be implemented with Amazon Bedrock Agents — agents, action groups, and guardrails.
Third-party model hosts, non-AWS agent frameworks, and non-AWS orchestration runtimes are
prohibited in the deployed system. No component the user can reach may depend on any non-AWS AI
vendor's runtime.

**Delivery.** All engineering tooling MUST be GitHub-native: GitHub Actions for CI/CD, GitHub
Spec Kit for the spec lifecycle, and GitHub Issues/Projects for work tracking.

**Development-time AI.** Claude Code is the permitted engine for driving the Spec Kit lifecycle
and for AI-assisted implementation and review, alongside GitHub Copilot. This is a
development-time tool, not a runtime dependency: nothing it produces may cause the deployed
system to call a non-AWS model. The boundary is absolute — an authoring tool may be Anthropic's;
a running component may not be.

Testable: dependency manifests and infrastructure code contain no non-AWS inference or agent
SDKs, enforced by an automated allowlist gate in CI; every deployed compute, storage, queue, and
model call resolves to an AWS service; every required workflow runs in GitHub Actions.

Rationale: the AWS-native runtime is a hard constraint of the engagement. Naming the
development-time engine explicitly closes a gap the earlier wording left open — the lifecycle was
already being driven by Claude Code while the principle listed only Copilot, which made the
project's own tooling non-compliant on paper.

### III. Zero Stored Credentials (NON-NEGOTIABLE)

Cloud access MUST be IAM-roles-only: a same-account local role, or cross-account `AssumeRole`
with an `ExternalId`. The platform MUST NOT store access keys, MUST NOT contain secrets in
source, and MUST NOT hold long-lived credentials in any datastore, environment file, or
configuration record. CI/CD MUST authenticate to AWS through GitHub OIDC federation only.
Scanning permissions MUST be read-only. Every privileged or state-changing operation MUST write
an immutable audit record identifying actor, action, target, and time.

Testable: secret scanning and a repository-wide credential scan pass on every merge; the scanner
role policy contains no write, delete, or modify actions; no GitHub Actions workflow references a
static AWS key secret; each state-changing endpoint has a test asserting an audit record is
written.

Rationale: a governance platform that mishandles credentials disqualifies itself. Roles and OIDC
also remove the whole class of secret-rotation work from a two-week build.

### IV. Deterministic Core, Agentic Edge

Discovery, validation, scoring, and cost ingestion MUST be deterministic and reproducible: the
same account state MUST always yield the same inventory, the same findings, and the same scores.
No model call may sit on these paths. Bedrock Agents operate strictly at the edge — they observe,
explain, recommend, and propose configuration as rules-as-data. Agents MUST NOT execute changes
against cloud accounts, MUST NOT hold or receive credentials, and every agent output shown to a
user MUST be grounded in and validated against platform data before display: real ARNs, real
numbers, no invented identifiers or figures. Agent-proposed configuration MUST pass through
human review before it takes effect.

Testable: replaying a fixed account snapshot twice produces byte-identical inventory and finding
sets; core engine modules import no Bedrock client; every agent response passes a grounding
validator that rejects ARNs and metrics absent from the platform datastore.

Rationale: reproducibility is what makes findings defensible, and grounding is what keeps AI
output trustworthy. The agents add explanation and proposal, never authority.

### V. Contract-First Modularity

Every boundary MUST carry a typed contract. The OpenAPI schema is the binding contract between
frontend and backend, and both sides MUST generate from it rather than hand-maintaining types. A
provider-agnostic connector interface with a normalized resource model MUST isolate all cloud
specifics; provider SDK types MUST NOT leak past the connector layer. Tag rules, SDA mappings,
coverage definitions, and agent-proposed extensions MUST be data, not code. Adding a new
provider, rule, resource type, or coverage entry MUST be possible without modifying core code.

Testable: the frontend API client is generated from the OpenAPI document in CI and drift fails
the build; a grep for provider SDK imports outside the connector package returns nothing; a new
tag rule or coverage entry can be added by editing data alone, demonstrated by a test that adds
one at runtime.

Rationale: modularity is graded directly, and rules-as-data is also what lets an agent propose an
extension safely — a proposal becomes a data change, never a code change.

### VI. Test and Quality Gates

Every merge to `pods/pod73` MUST pass lint, type checks, and unit tests. Cloud-touching code MUST
additionally pass integration tests against mocked AWS in CI. Each story's definition of done
includes tests covering its acceptance criteria, structured logs at its operational boundaries,
and updated documentation. CI is a required check: a red check blocks merge, with no exceptions
and no administrative override.

Testable: branch protection on `pods/pod73` requires the CI check; every merged PR shows a green
required check; no merge commit exists whose head check was failing or bypassed.

Rationale: an always-green trunk is what makes trunk-based development safe with six people
merging daily, and it is the cheapest possible evidence of coding standards.

### VII. Solo Trunk-Based Delivery with AI Collaboration

`pods/pod73` is the only long-lived branch and MUST always be releasable. Every pull request
targets it. All working branches MUST follow the `pods/pod73-XXX` naming pattern. Work happens on
short-lived branches merged via PR the same day wherever possible. PRs MUST stay small and MUST
reference their spec and task IDs in the description.

**Review.** The project is built by a single maintainer working with AI agents, so there is no
second human to review. Every PR MUST therefore receive at least one automated AI review — an
agentic PR checker or GitHub Copilot review — before merge, and that review MUST check the change
against this constitution. Self-merge is permitted **only** after CI is green and an AI review is
recorded on the PR. A PR with no recorded review MUST NOT be merged, however small.

**Ownership.** The six feature specs are authored sequentially in dependency order (001 →
006) by the sole maintainer, each pipelined fully — specify, clarify, plan, checklist, tasks,
analyze — before the next begins, so every merged spec is context for its successors.

Testable: no branch outside the `pods/pod73-XXX` pattern is pushed; every merged PR carries a
recorded AI review and a green CI check; every merged PR body cites at least one spec or task ID;
no spec begins before its predecessor's analyze run is clean.

Rationale: a single maintainer loses the second pair of eyes, so the automated review is not a
nicety — it is the only remaining check between a mistake and the trunk. Making it mandatory and
recorded keeps the merge history as auditable evidence, which is what the assessment reads.
Sequential authoring replaces parallel ownership: it costs wall-clock time but means each spec is
written with its predecessors already settled.

### VIII. Honest Prioritization

Every requirement MUST carry a tier: P1 (demo-critical) or P2 (stretch). P1 scope is frozen at
plan approval; new ideas enter as P2 or post-MVP and MUST NOT be smuggled into P1 scope. P2 work
MUST NOT block, destabilize, or take dependency ownership of any P1 path — if a P2 change breaks
a P1 flow, the P2 change is reverted, not the P1 flow patched around it.

Testable: every functional requirement in every spec carries a P1 or P2 marker; no task added
after plan approval is marked P1 without a recorded amendment; the P1 demo path passes its
end-to-end check independently of any P2 feature being present.

Rationale: an honest, frozen critical path is what makes a two-week build land. Silent scope
growth is the standard way hackathon projects arrive at demo day with nothing runnable.

## Technology and Security Constraints

- **Runtime:** serverless AWS managed services only. Compute is AWS Lambda; orchestration is AWS
  Step Functions; persistence is Aurora Serverless v2 plus S3 for immutable snapshots.
- **GenAI:** Amazon Bedrock Agents exclusively, with action groups for tool access and guardrails
  enabled on every agent. Agent action groups MUST call platform APIs only — never cloud
  provider APIs directly.
- **Frontend/backend:** a single OpenAPI document is the contract; generated clients on both
  sides. Every API call is authenticated and rate-limited.
- **Infrastructure:** all infrastructure is defined as versioned code (Terraform) and applied
  through GitHub Actions with OIDC. Manual console changes to shared environments are prohibited;
  anything created by hand MUST be reproduced in code or destroyed.
- **Access:** read-only cross-account scanning roles with `ExternalId`. Production deployment
  requires an explicit approval gate.
- **Audit:** every privileged or state-changing operation, and every accepted agent proposal,
  writes an append-only audit event. Audit records are never updated or deleted.
- **Observability:** structured JSON logs with correlation IDs across the scan pipeline; no
  secrets, credentials, or raw customer tag values in logs.

## Development Workflow and Quality Gates

1. **Specify:** the spec owner runs `/speckit-specify`, then `/speckit-clarify`. The branch is
   renamed to the `pods/pod73-XXX` pattern before the first push. The spec PR merges into
   `pods/pod73` the same day.
2. **Plan and tasks:** `/speckit-plan`, `/speckit-checklist`, `/speckit-tasks`, and
   `/speckit-taskstoissues`, followed by `/speckit-analyze` before any implementation code is
   written. Tasks are ordered P1-first and exported to GitHub Issues for POD assignment.
3. **Implement:** one short-lived `pods/pod73-XXX` branch per task slice. Open a PR referencing
   the spec and task IDs, take the Copilot review plus one human review, merge on green CI,
   delete the branch.
4. **Required checks:** lint, type check, unit tests, and — for cloud-touching code —
   integration tests with mocked AWS. Secret scanning runs on every PR.
5. **Definition of done** for any story: acceptance-criteria tests pass, structured logs present
   at operational boundaries, docs updated, journal entry appended, and the spec still matches
   the shipped behavior.
6. **Journal:** the person who runs a speckit phase records its outcome in
   `AI_WORKFLOW_JOURNAL.md` the same day.

## Governance

This constitution supersedes all ad-hoc practice. Where a habit, a tool default, or a convenient
shortcut conflicts with a principle here, the principle wins; the alternative is to amend the
constitution, not to work around it.

**Amendments.** An amendment is proposed as a pull request that changes this file and states the
rationale and version bump in the PR description. The sole maintainer approves it, and the PR
MUST carry an AI review as with any other change. Amendments take effect on merge and MUST be
recorded in `AI_WORKFLOW_JOURNAL.md` §1.

**Versioning.** This document follows semantic versioning:

- **MAJOR** — a principle is removed, or redefined in a way that invalidates work already merged
  under the old wording.
- **MINOR** — a new principle or governing section is added, or existing guidance is materially
  expanded.
- **PATCH** — clarifications, wording, typo fixes, and non-semantic refinements, including
  filling deferred TODO placeholders.

**Compliance.** `/speckit-analyze` MUST be run against each spec's artifacts before
implementation begins, and MUST check spec, plan, and tasks against these principles; violations
are resolved before the first implementation task starts. Every pull request review — automated or
otherwise — MUST check the change against this constitution and MUST reject any PR that violates a
principle regardless of how well the code is written. Complexity that appears to violate a
principle MUST either be justified in the PR description and accepted at review, or removed. Runtime development guidance lives in `SPECKIT_PLAYBOOK.md`, which is subordinate to
this document.

**Version**: 2.0.0 | **Ratified**: 2026-08-22 | **Last Amended**: 2026-08-22
