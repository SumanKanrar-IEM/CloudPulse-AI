# Contributing to CloudPulse AI

CloudPulse AI is built by one maintainer working with AI agents, under the project constitution
(`.specify/memory/constitution.md`, v3.x). This file is the constitution's contribution rules
distilled into a checklist. The automated PR reviewer (`.github/workflows/contribution-guidelines-checker.md`)
checks every pull request against it, and its comment is the **recorded AI review** Principle VII
requires before a merge.

When this file and the constitution disagree, the constitution wins.

## Every pull request

- **Targets `pods/pod73`**, the only long-lived branch (Principle VII).
- **Comes from a branch named `pods/pod73-<something>`** — e.g. `pods/pod73-006-t069`.
- **Cites at least one task ID (`T` + three digits) in its description**, and the spec it belongs
  to. The task must already exist in `specs/<spec>/tasks.md`; a fix the task list didn't
  anticipate gets a new task first (Principle I). CI's `pr-task-reference` gate enforces the ID.
- **Is small and single-purpose.** One task or one tightly related group.
- **Has a green CI run** (all required checks) and **a recorded AI review** before it is merged.
  Nobody merges a PR with neither, however small (Principle VII).
- **Uses a conventional-commit title**: `feat(006): …`, `fix(002): …`, `docs: …`, `refactor: …`,
  `chore: …`, `test: …`.
- **Explains what changed and why** in plain prose, and **how it was tested**.

## Code

- **Spec first** (Principle I). Behaviour follows `spec.md`, `plan.md` and `tasks.md`. A change the
  spec does not sanction is raised and recorded, not improvised.
- **No credentials, secrets or long-lived keys** anywhere in source, config or fixtures
  (Principle III). Cloud access is IAM roles only; CI reaches AWS through GitHub OIDC only.
  Scanning permissions stay read-only.
- **Provider SDKs stay inside `backend/connectors/`** (Principle V). No `boto3`/AWS SDK type leaks
  past the connector layer; CI's `connector-boundary` gate enforces it.
- **Typed contracts at every boundary** (Principle V). The OpenAPI document is generated from the
  backend's Pydantic models (`backend/openapi.generated.yaml`), and the Angular client under
  `frontend/src/app/api/` is generated from it — never hand-edited.
- **Rules, SDA mappings and coverage are data, not code** (Principle V).
- **Deterministic core, agentic edge** (Principle IV). Discovery, validation, scoring and cost are
  deterministic. Agents explain and propose; they never execute changes, never hold credentials,
  and every agent output is validated against platform data before it is shown.
- **Structured logging** at operational boundaries.

## Tests (Principle VI)

- Tests are written **with** the code, covering the task's acceptance criteria.
- Cloud-touching code has integration tests against mocked AWS (moto / LocalStack /
  Testcontainers Postgres) — never a real account in CI.
- Before pushing, run what CI runs: from `backend/`, `ruff check .`, `ruff format --check .`,
  `mypy .` and `pytest`; from `frontend/`, `npm run lint`, `npm run build` and
  `npx playwright test`.

## Docs

- A change that alters behaviour, a contract, a table or infrastructure updates the matching doc:
  the spec's `data-model.md` / `quickstart.md`, `ops/erd/schema.mmd`, or the relevant `README.md`.
- Each spec phase's outcome is recorded in `AI_WORKFLOW_JOURNAL.md`.

## Priorities (Principle VIII)

Every requirement is P1 (demo-critical) or P2 (stretch). P1 scope is frozen; new ideas enter as P2
or later and never block a P1 path.
