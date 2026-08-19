# AI Workflow & Agentic Development Journal — CloudPulse AI

> **Purpose:** Evidence of AI-native engineering practices for the hackathon assessment.
> Documents how the POD used GitHub Copilot, GitHub Spec Kit, and GitHub Agentic Workflows
> to build the AWS-native CloudPulse AI MVP — covering spec-driven development, architectural
> discipline, engineering standards, and POD collaboration.
> **Rule:** the person who runs a speckit phase appends its entry the same day.

## 0. Project Initialization & Scope Definition

- **Tools:** GitHub Spec Kit (`specify init`, Copilot integration, Python scripts), AI-assisted document analysis.
- **What we did:**
  - Initialized the repo with GitHub Spec Kit for GitHub Copilot (`.github/skills/speckit-*`, `.specify/` scaffolding); repo pushed to `SumanKanrar-IEM/CloudPulse-AI`; moved the working copy out of OneDrive to a plain local path to protect git integrity.
  - Used AI to deep-analyze all product documents (`docs/`): Capstone Overview, Plan & Tech Stack, Engineering Guide, Architecture deck, and the Backlog spreadsheet — including programmatic extraction of the **color-coded MVP stories** (cell-fill analysis of the xlsx).
  - Locked MVP scope v2 with explicit dependency rulings (drop S32, cut Notification Engine E6, include S43 + S47, AI suggestions render on findings page) and priority tiers (P1 demo-critical / P2 stretch).
  - Decided the AI-discovery approach: **deterministic engine, AI-planned coverage** — generic whole-account discovery with a Bedrock Agent proposing coverage extensions as data.
  - Produced `SPECKIT_PLAYBOOK.md`: exact inputs for every speckit command, six-feature spec slicing (one spec per member of the 6-person POD), run order, and POD working agreement — trunk-based on `pods/pod73`, short-lived `pods/pod73-XXX` feature branches, all PRs into `pods/pod73` with Copilot review.
- **Outcome:** *(fill after constitution: date, POD member names/owners per spec)*

## 1. Constitution

- **Tool:** `/speckit-constitution` (whole POD session)
- **Approach:** Eight enforceable principles derived from the product docs and hackathon judging criteria: Spec-First Delivery; AWS-Native & GitHub-Native (Amazon Bedrock Agents for all GenAI); Zero Stored Credentials; Deterministic Core, Agentic Edge; Contract-First Modularity; Test & Quality Gates; Trunk-Based POD Collaboration; Honest Prioritization (P1/P2).
- **Outcome:** *(constitution version, ratification date, any POD amendments)*

## 2. Specification (6 feature specs, one owner each)

- **Tools:** `/speckit-specify`, `/speckit-clarify`
- **Slicing (one owner per POD member):** 1 platform-foundation (DevOps) · 2 account-onboarding-and-discovery (BE2) · 3 tag-compliance-and-ownership (BE1) · 4 governance-dashboard (FE) · 5 cost-and-utilization (BE3/full-stack) · 6 ai-insights-agent (AI engineer).
- **Approach:** Functional, tech-agnostic spec inputs from the playbook; clarify answered from the settled decision log; each spec branch renamed to the `pods/pod73-XXX` pattern and merged to `pods/pod73` via PR the same day.
- **Outcome:** *(per spec: branch/PR link, clarify questions that surfaced, decisions recorded)*

## 3. Planning & Task Generation

- **Tools:** `/speckit-plan`, `/speckit-checklist`, `/speckit-tasks`, `/speckit-taskstoissues`, `/speckit-analyze`
- **Approach:** One shared AWS-native technology direction across all six plans (Lambda/FastAPI, Step Functions, Cloud Control API discovery, Aurora Serverless v2, Angular 18, Bedrock Agents, Terraform, GitHub Actions OIDC). Tasks ordered P1-first, exported to GitHub Issues for POD assignment; analyze run per spec before any code.
- **Outcome:** *(plan highlights, analyze findings fixed, issue counts per spec)*

## 4. Implementation & POD Collaboration

- **Tools:** `/speckit-implement`, GitHub PRs with Copilot review, GitHub Actions CI
- **Approach:** Task-sized short-lived branches named `pods/pod73-<task-id>-<slug>`; every PR targets `pods/pod73`, references spec + issue, passes CI gates (ruff, mypy, pytest+moto, Angular build, terraform validate), and gets Copilot + human review before same-day merge to the always-releasable trunk.
- **Outcome:** *(PR/merge stats, test coverage, notable Copilot-review catches, demo milestones)*

## 5. Agentic Automation

- **Tools:** GitHub Agentic Workflows (`gh aw`), adapted from githubnext/agentics
- **Planned set:** issue triage, constitution-aware PR reviewer, CI doctor, daily progress + journal drafter.
- **Outcome:** *(workflows compiled/enabled, examples of agent contributions)*

## 6. Assessment & Convergence

- **Tools:** `/speckit-analyze`, `/speckit-checklist`, `/speckit-converge`
- **Approach:** End-of-sprint audit of codebase vs specs and constitution; remaining gaps appended as tasks, never silently dropped.
- **Outcome:** *(convergence report summary, P1 coverage %, final architectural assessment)*
