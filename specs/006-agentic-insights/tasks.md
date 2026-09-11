---
description: "Task list for spec 006 — agentic insights"
---

# Tasks: Agentic Insights

**Input**: Design documents from `/specs/006-agentic-insights/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included and are NOT optional here — constitution Principle VI's quality
gates require tests written with the code, and Principle IV's grounding rule is only meaningful if
something proves a fabricated reference is actually rejected.

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable — different files, no dependency on an incomplete task
- **[Story]**: US1–US7 from spec.md
- Every task names exact file paths

## Tier Summary

**P1 (must complete first, deliverable with zero P2 items)**: Phases 1–5, T001–T031 plus the
T007a/T011a/T011b/T017a/T017b/T018a/T020a/T024a insertions — 39 tasks. Delivers
SC-001, SC-002, SC-004, SC-005, SC-008, SC-009 — the digest, the suggester, and every
grounding/safety guarantee.

**Phase 5a (P1 work, deferred)**: T061–T067 — the AgentCore migration forced by AWS closing
Bedrock Agents (constitution v3.0.0, R-613). Scheduled after P2 because P2 does not depend on which
runtime hosts an agent, and T061's spike could still change the shape of T062–T067.

Numbered T061+ rather than inserted at T032: P2 already owns T032–T060, and renumbering a phase
that other documents cite would break every reference to buy nothing. The higher numbers also
match execution order, since this phase runs last.

**P2 (stretch)**: Phases 6–10, T032–T060. Every P2 task is marked **[P2]** in its description.
Dropping all five P2 stories leaves both P1 stories and their success criteria intact — only
SC-003, SC-006, SC-007 and FR-015–FR-024 go with them.

## Process Note

If implementation surfaces a fix this list did not anticipate, **add the task here before opening
that fix's PR** — a `T0XXa`-style insertion next to the task it corrects. `pr-task-reference` CI
requires a task ID in the PR body regardless; the task exists for traceability, not to satisfy the
gate. Specs 003–005 each ended with several such tasks and the practice is what made their PR
history readable.

---

## Phase 1: Setup & Schema

**Purpose**: The tables and scaffold every later phase writes to.

- [X] T001 Create the `agents/` tree per plan.md — `agents/definitions/`, `agents/action-groups/`,
      `agents/prompts/`, `agents/evals/`, each with a README stating what it holds and that spec
      001 reserved this tree. Replace `agents/README.md`'s "deliberately empty" wording, which
      stops being true here — S43, S44, Principle I
      **Done.** Each subdirectory's README states the constraint that actually binds it rather
      than repeating the tree: action groups call the HTTP API and never the database (R-602);
      prompts are content-hashed so a behaviour change traces to a commit rather than to model
      drift; evals run against recorded fixtures, which buys determinism and free CI at the cost
      of proving output *handling* rather than model quality — stated so the suite is not mistaken
      for something it is not.
- [X] T002 Write `backend/migrations/versions/0015_agentic_insights.py` — the seven tables from
      data-model.md (`agent_run`, `insight_digest`, `grounding_rejection`, `coverage_proposal`,
      `resource_metric`, `forecast`, `rightsizing_recommendation`), the **seven** enum types
      data-model.md's "Enum additions" section lists, and the partial unique indexes. Declare `REVERSIBLE: yes` — S43, FR-005, FR-006a
      `erd-current` CI requires `ops/erd/schema.mmd` to change in this same PR.
      **Done.** Purely additive — no spec 001–005 row is touched and no backfill is needed. Two
      CHECK constraints encode requirements rather than conventions:
      `ck_agent_run_failure_reason_shape` (a failed run has a reason, a successful one does not)
      and `ck_resource_metric_unavailable_shape` (FR-020's unknown-never-zero). Every enum carries
      only values something can write today — the lesson migration 0014 paid for when
      `withheld_bounced` shipped with no writer and removing it needed a rename-create-recast-drop.
- [X] T003 Update `ops/erd/schema.mmd` with the seven new entities and their relationships to
      `tenant`, `finding`, `resource`, `sda` and `cloud_account` — S43, FR-028 (spec 001)
      **Done.** The ERD records *why* two shapes are what they are, not just what: `forecast` has
      no `agent_run_id` because forecasting is deterministic and never an agent output, and
      `grounding_rejection` deliberately does not store the rejected text — keeping unvalidated
      model output would create a home for fabricated ARNs inside the platform.
- [X] T004 [P] Add the SQLAlchemy models to `backend/app/models/core.py` and the enums to
      `backend/app/models/enums.py`, every table `TenantScoped` — S43, FR-005, FR-006a
      **Done.** The seven enums are created by this spec's own migration rather than added to
      migration 0001's `ENUM_TYPES` registry, matching what every spec since 003 has done — that
      dict is the one-time initial registry.
- [X] T005 [P] Write `backend/tests/integration/test_migration_0015.py` — every revision applies
      and downgrades cleanly, the enums hold exactly their documented values, and the partial
      unique indexes reject the duplicates they exist to prevent — S43, FR-006a
      **Done**, 18 tests. Two choices worth recording, both made after ruff flagged the first
      draft and both real improvements rather than lint appeasement: assertions use
      `IntegrityError`, never bare `Exception` — a broad catch would pass on a typo'd statement
      raising `ProgrammingError`, so the test would report a constraint working while actually
      proving the SQL was wrong — and every statement binds parameters instead of interpolating.
      Enum membership is asserted exactly rather than with `<=`, so a speculative value fails here
      instead of surviving into someone else's migration.

**Checkpoint**: Schema exists; nothing reads it yet.

---

## Phase 2: Foundational — Grounding & Run Accounting

**Purpose**: The two things all seven stories depend on. Built as their own phase deliberately
(plan.md): if the validator were built inside the digest phase, the suggester's compliance with
Principle IV would be an accident of ordering rather than a property of the design.

⚠️ **Blocking**: no user story may start before this phase completes.

- [X] T006 [P] Write `backend/tests/unit/test_grounding.py` — an output naming a resource absent
      from the store is rejected; one naming only real resources passes; a figure that does not
      match the store is rejected; the validator makes no model call and is deterministic over
      the same input. Covers FR-001a's boundary in both directions: a prose numeral like "the last
      7 days" does not trigger rejection, and a fabricated *platform* figure does — S43, FR-001,
      FR-001a, FR-006, research.md R-607
      **Done**, 18 tests. FR-001a's boundary is asserted in both directions: rejecting "the last 7
      days" would make grounding useless in practice, and letting a fabricated dollar figure
      through would make it dishonest.
- [X] T007 Write `backend/app/governance/grounding.py` — the deterministic validator: extract
      candidate ARNs, resource ids, project names and numerals from an agent output, resolve each
      against the governance store, return a pass/reject verdict naming the first unresolvable
      reference. FR-001a fixes *what* is validated: platform-computed quantities (counts, scores,
      percentages, money) resolve; ordinary prose numerals do not; a quantity presented as a
      platform figure that the platform never computed is unresolvable — S43, FR-001, FR-001a,
      R-607
      **Done.** Figures are **declared** as structured data rather than parsed out of prose, which
      required adding a `figures` array to the digest section contract — additive, and it makes
      validation exact instead of a regex guess at which numerals were meant to be figures. The
      body is still swept for currency and percentages, because FR-001a treats an undeclared
      platform-shaped quantity as unresolvable; bare integers are exempt.
- [X] T007a Close the parser differential in `backend/app/governance/grounding.py`. Found by a
      background security review of T007's commit, and real: **seven ways a fabricated monetary or
      percentage figure passed the prose sweep entirely**, so FR-001a's "presented as a platform
      figure but never computed" check never ran on it. A fullwidth dollar sign, a euro/pound/yen
      amount, a fullwidth percent, and a worded `9999.00 USD` all swept to nothing. `-$500.00`
      swept as `500.00` — the sign dropped, so a stated saving validated against a declared cost
      of the same magnitude, reader and validator seeing opposite facts. `$4,2,0,0.00` normalised
      onto a declared `4200.00`, because stripping commas blindly makes any grouping equivalent to
      any other.
      Fixed by NFKC-normalising the body before sweeping (folding fullwidth forms to ASCII),
      widening the currency class beyond `$`, capturing the sign on either side of the symbol, and
      failing **closed** on a token that reads as a figure but does not parse — rather than
      skipping it, which is how the malformed-grouping case slipped through. Nine regression tests
      pin each differential; one pins that well-formed grouping still passes, since R-607 names
      rejecting correct output as the failure direction to avoid — S43, FR-001, FR-001a, R-607

- [X] T008 [P] Write `backend/tests/unit/test_agent_run.py` — a run records its definition hash,
      cost and cap; reaching the cap yields `truncated`, not `failed`; an unreachable model yields
      `failed` with a reason; `finished_at` is set on every terminal state — S43, FR-004, FR-005
      **Done**, 13 tests, including that an error outranks an exhausted budget — a run that both
      hit its cap and threw is a failure, because the error is the fact needing diagnosis and
      truncation would hide it.
- [X] T009 Write `backend/app/governance/agent_runs.py` — open/close a run, enforce the cost cap,
      record `definition_hash`, and expose FR-004a's retention rule (item-wise capabilities keep
      validated items on truncation; whole-artifact capabilities discard). The cap is read from
      the environment at point of use with a conservative fallback, **not** added to `Settings` —
      see R-612 and spec 005's T029a, where the Settings route broke 11 unrelated tests — S43,
      FR-004, FR-004a, FR-005, R-612
      **Done.** Pure, and split from persistence deliberately: the decisions cannot drift into a
      query and are provable without a database. `RunBudget` refuses a zero or negative cap at
      construction — a cap of zero truncates every run before it starts, which is silent breakage
      dressed as a configured limit.
- [X] T010 [P] Write `backend/app/governance/definition_hash.py` and
      `backend/tests/unit/test_definition_hash.py` — content-hash a prompt/definition file so
      every stored output traces to what produced it; the hash changes when the file does — S43,
      FR-005, R-608
      **Done**, 10 tests. Hashing content rather than reading a version string: a version string is
      a promise someone must remember to keep, a content hash cannot disagree with its file. Line
      endings and trailing whitespace are normalised, so the hash does not move on how an editor
      saved a file — a hash that noisy stops being trusted, and one nobody trusts records
      nothing.
- [X] T011 Extend `backend/connectors/aws.py` with `invoke_agent(...)` — the only place the
      Bedrock SDK appears (Principle V, FR-054). Returns raw output; makes no grounding or cost
      judgement, which belong to `app/governance/` — S43, FR-003, R-601, R-602
      **Done.** Returns raw text and token counts. Raises rather than returning a partial result:
      FR-007a needs the caller to record `failed`, and a swallowed error would become a run that
      looks successful and produced nothing. `connector-boundary`: 173 files, 0 violations.
- [X] T011a [P] Write `backend/tests/integration/test_degraded_mode.py` — **FR-007a and SC-009,
      the requirement that makes P1 shippable under R-605.** With the model unreachable: the run
      is recorded `failed` with a reason; `GET /insights/digest` serves the last valid digest or
      the explicit not-enough-data state; the findings workbench shows suggestions already stored
      and none fabricated; and no surface renders a partial or placeholder result. Then replay a
      fixed fixture with the intelligence layer disabled and assert inventory, finding and score
      output are **byte-identical** to the run with it enabled — SC-009's own stated comparison,
      not a prose claim of no regression — S43, S44, FR-007a, SC-009
      **Done in part, and split — see T018a.** The deterministic half is here: populating every
      agent table leaves inventory, findings and the compliance score byte-identical, and an
      unreachable model is recorded `failed` with a reason rather than silently absent. The
      surface half — `GET /insights/digest` serving last-valid-output — asserts routes T018 builds
      in Phase 3, so it moves there as **T018a**. A Phase 2 test cannot exercise a Phase 3
      surface, and stubbing one to satisfy the ordering would prove nothing. This is an ordering
      error in this task list, recorded rather than worked around.
- [X] T011b [P] Write `backend/tests/unit/test_deterministic_core_isolation.py` — **Principle IV's
      own testable clause**, which no other task asserts: no module under `app/scan/`,
      `app/governance/validation.py`, `app/governance/scoring.py` or `app/governance/spend.py`
      imports a Bedrock client or reaches `app/governance/grounding.py`'s agent path, and
      replaying a fixed account snapshot twice produces byte-identical inventory and finding sets.
      `check_connector_boundary.py` restricts boto3 to `connectors/` generally but says nothing
      about Bedrock specifically reaching the deterministic core — S43, FR-007, Principle IV
      **Done**, 20 tests. Also asserts the core imports no *agent-layer* module: importing
      `agent_runs` or `digest` into scoring would put the intelligence layer's availability on a
      deterministic path, so scoring could start failing because Bedrock was unreachable. Carries
      a guard on the guard — if these module paths were renamed every test would skip and report
      green while asserting nothing, so one test fails if fewer than six are found.
- [X] T012 [P] Write `backend/tests/unit/test_agent_read_only.py` — the action-group principal is
      refused on every non-GET method and holds no cloud credential, asserted against spec 001's
      existing `app/core/agent_access.py` rather than a re-implementation — S43, FR-002, FR-003,
      FR-056 (spec 001)
      **Done**, 16 tests. Includes the fail-closed case (an HTTP method the platform has never
      heard of is refused, not permitted by omission) and that the guard leaves *human* principals
      alone — it must not become a general method filter, since an operator's POST is not an
      agent's POST.

- [X] T018a [US1] Assert FR-007a's **surface** half, alongside T018's routes: with the model
      unreachable, `GET /insights/digest` serves the last valid digest or the explicit
      not-enough-data state, `GET /insights/runs` shows the failed run with its reason, and no
      surface renders a partial or placeholder result. Split out of T011a, which could not
      exercise a Phase 3 surface from Phase 2 — S43, S44, FR-007a, SC-009
      **Done**, in `backend/tests/integration/test_insights_api.py` alongside T018's own tests.
      Every failure is driven through `run_digest` with an `invoke` that raises, rather than by
      writing an `agent_run` row by hand — a hand-written row would assert that the API renders a
      failed run correctly while leaving unproven the thing that matters, that a failed invocation
      *produces* one.

**Checkpoint**: Any capability can now run, be capped, be recorded, and have its output validated
— and the two guarantees that let P1 ship without a reachable model (FR-007a/SC-009) and keep the
deterministic core model-free (FR-007) are asserted rather than assumed.

---

## Phase 3: User Story 1 — Insight Digest (Priority: P1)

**Goal**: A daily plain-language digest on the dashboard whose every reference is real (S43,
FR-008, FR-008a, FR-009, FR-010).

**Independent Test**: Run a digest against a store with known findings, a known compliance
movement and a known spend delta; confirm it renders, and that every identifier and figure exists
in the store.

### Tests for User Story 1

- [X] T013 [P] [US1] Write `backend/tests/unit/test_digest_selection.py` — FR-008a's deterministic
      order: severity descending, then escalated before not, then oldest first; the same finding
      set always selects the same digest set; the agent is not consulted for ranking — S43,
      FR-008a, R-606a
      **Done**, 25 tests, and they cover FR-008b's notability thresholds as well as FR-008a's
      ranking — both are platform decisions made before the agent is invoked, so they belong
      together. Two guards worth naming: severity ranks by an explicit map rather than the enum's
      string values, which would sort `low` above `medium` and `critical` below both; and the
      full three-key order is exercised in one test, since each pairwise test alone passes under
      several wrong orderings.
      FR-008b's "either bar" rule is tested at both blind spots — $500 on a $10,000 project clears
      the absolute bar but not the percentage, $40 on a $100 project the reverse — and a project's
      first spend is notable only on the absolute bar, since treating a zero baseline as an
      infinite percentage increase would make every new project's first day notable.
- [X] T014 [P] [US1] Write `backend/tests/integration/test_digest_pipeline.py` — a run produces
      one digest per tenant per day; a re-run replaces rather than duplicating; a draft naming an
      absent resource is rejected and recorded in `grounding_rejection` with no digest stored; a
      tenant whose inputs cross no FR-008b threshold gets `is_empty = true` rather than an empty
      card, and one that crosses a threshold does not; a truncated digest run discards its partial
      output entirely (FR-004a) — S43, FR-001, FR-004a, FR-008, FR-008b, FR-010
      **Done**, 14 tests, driven through `run_digest` with an `invoke` callable rather than a
      mocked Bedrock client — the pipeline has to be provable with no cloud client present at all.
      Three tests the task did not name but the listed ones are weak without: two periods each keep
      their own digest (otherwise "replaces rather than duplicates" would still pass if the upsert
      keyed on tenant alone, and the platform would hold one digest ever); a correct digest quoting
      a real platform figure is *stored* (R-607 — a validator that only ever refuses is as useless
      as one that only ever accepts); and a notable spend move with no open findings still invokes,
      since a digest firing only on findings would miss the whole cost half of FR-008.

### Implementation for User Story 1

- [X] T015 [US1] Write `backend/app/governance/digest.py` — select findings per T013's order,
      assemble the compliance and spend inputs, invoke through T011, validate through T007, and
      persist an `insight_digest` row plus its `agent_run`. FR-008b's notability thresholds are
      computed here, before the agent is invoked, and read from the environment per R-612 rather
      than from literals or `Settings` — the agent never decides what counts as notable — S43,
      FR-008, FR-008a, FR-008b, FR-009, FR-010, R-612
      **Done.** Every path writes exactly one `agent_run` row, including the ones that store no
      digest: a run that produced nothing still happened and still cost something, and a digest
      that silently did not appear is indistinguishable from a scheduler that never fired.
      Three decisions worth naming. **The nothing-notable branch never invokes the model** —
      FR-010's answer is already known before any spend is incurred, so paying for it would be
      paying for an answer the platform computed itself. **A grounding rejection is recorded as a
      `failed` run, not a `succeeded` one** — nothing was stored, and a run reporting success while
      storing nothing reads exactly like a quiet day; truncation stays separate from both, because
      FR-007a needs an ordinary budget stop to remain distinguishable from an unreachable model.
      **`parse_sections` is fail-closed** — a best-effort read of malformed output would drop the
      broken section silently, and a fabricated reference inside it would then never reach the
      validator at all, so the check would pass by never seeing the thing it exists to catch.
- [X] T016 [US1] Write `agents/definitions/digest.json`, `agents/prompts/digest.md` and
      `agents/action-groups/digest_tools.py` — the action group reads findings, compliance and
      spend through the platform API only (R-602), never the database — S43, FR-003, R-601, R-602
      **Done**, three operations in the schema and no more — each backed by an endpoint specs
      002–005 already ship, per `agents/definitions/README.md`.
      **How the action group authenticates, since neither the plan nor research names it.** It
      needs a Cognito token for the `custom:agent_id` principal, which needs a client secret. Every
      obvious route to that secret is an SDK call, and `agents/action-groups/README.md` forbids a
      provider SDK in this tree. The AWS Parameters and Secrets Lambda Extension resolves it: the
      secret arrives over `localhost` HTTP, so the module holds no credential, imports no SDK, and
      the rule stands as written. The extension layer is a new infra dependency, provisioned in
      T020 and left empty by default.
      The prompt is explicit that a *derived* number is rejected even when the arithmetic is right.
      That is the likeliest honest failure — a model that adds two real figures correctly and
      states a total nothing on the platform computed.
- [X] T017 [US1] Write `backend/handlers/digest_worker_handler.py` — the daily EventBridge
      entrypoint — S43, FR-008, R-605
      **Done.** Covers **yesterday**, not today: a run firing at 09:00 that summarised the current
      date would compare a few hours of spend against a full previous day and call the difference
      a collapse. The definition hash covers the prompt *and* the definition file — a change to the
      action-group schema changes what the agent can read and therefore what it can say, and a hash
      that moved only on prompt edits would leave that unexplainable.
      One thing recorded rather than papered over: `connectors/aws.py`'s `invoke_agent` has no
      truncation signal to report, because Bedrock's event stream ends the same way whether the
      model finished or hit its output limit. For the digest that costs nothing — a summary cut off
      mid-JSON fails to parse and is discarded whole, which is what FR-004a prescribes for a
      whole-artifact capability anyway. It will matter for T021's suggester, which is item-wise and
      must not inherit the assumption.
- [X] T017a [US1] Add `tenant_compliance_score` to `backend/app/governance/scoring.py` — the digest
      reports one score for the whole estate, and spec 003 only ever computed per-account and
      per-SDA ones. Weighted by resource rather than by averaging per-account scores, so an account
      holding three resources cannot move the headline as much as one holding three thousand —
      S43, FR-008, FR-018
      **Not anticipated by this list**, and recorded here rather than folded silently into T015.
      It also forced a second decision: FR-008b's compliance movement needs a *previous* score, and
      nothing stores one. Recomputing history from `resource.created_at` would date a resource to
      when the scanner first saw it, not to when it existed — so the digest row now carries the
      platform figures that produced it, and the next run reads its baseline from there. "Since the
      last digest" is a weaker claim than "since yesterday" and it is the one the data supports.
- [X] T017b [US1] Quantise the compliance figure in `backend/app/governance/digest.py`'s
      `build_inputs` before it becomes a known figure — S43, FR-001a, R-607
      **Found in the Phase 3 self-review, after CI was green.** Compliance is a float ratio, and
      `score * 100` for two resources out of three is `66.66666666666666`. That went to the agent
      as a declared figure, and the prompt forbids rounding — so the model would either write
      sixteen digits into prose or round to `66.7` and have the **entire digest rejected** for a
      figure that was correct. Every tenant whose score is not a clean fraction would have hit it.
      This is R-607's failure direction — rejecting correct output — and the same class of error as
      T007a: the tests asserted the pipeline's *logic* thoroughly and never asked whether the
      numbers it handed the agent were ones a person could write. Quantised to one decimal place,
      with a regression test that seeds a two-thirds score and asserts a digest stating `66.7`
      validates rather than being refused.
- [X] T018 [US1] Write `backend/app/api/routers/insights.py` — `GET /insights/digest`,
      `GET /insights/runs`, `GET /insights/rejections`, all `require_viewer`-gated. Regenerate
      `backend/openapi.generated.yaml` and the frontend client — S43, FR-009, FR-006
      **Done.** Contract regenerated: 346 lines added, none removed — purely additive, so
      `contract-compat` has nothing to object to. Tests are in
      `backend/tests/integration/test_insights_api.py` (10, shared with T018a).
      The digest is ordered by **period**, not by insert time: a backfill run for an older day must
      not displace the current digest just by being written most recently.
      `platform_figures` is stored on the row but deliberately not served. It is the platform's own
      working, not part of the digest, and exposing it would invite a frontend to render a number
      the grounding validator never checked as prose. There is a test pinning that.
- [X] T019 [P] [US1] Extend `frontend/src/app/features/overview/compliance-overview.component.ts`
      with the digest card, labelled with the run that produced it so a stale digest is never
      mistaken for current — S43, FR-009
      **Done.** The digest is fetched separately from the rest of the overview and fails quietly:
      an unreachable intelligence layer must not take the compliance page down with it (FR-007a),
      and a null digest renders no card at all — exactly what the page showed before this spec.
      Period and prompt hash are on the card itself, not behind a tooltip. `ng lint` and `ng build`
      both pass.
- [X] T020 [US1] Extend `infra/modules/agents/{main.tf,scheduler.tf}` — the digest agent, its
      alias, its guardrail, the action-group Lambda and the daily schedule — S43, R-601, R-605,
      R-606
      `terraform fmt -check -recursive infra/` and `terraform validate` must pass.
      **Done**, and wired into both `envs/dev` and `envs/prod`. `fmt -check` clean; `validate`
      passes for the module and for both environments.
      The agent's instruction is read from `agents/prompts/digest.md` with `file()` rather than
      restated in Terraform — `definition_hash.py` hashes that same file onto every `agent_run`
      row, and a duplicated prompt would let the deployed instruction and the recorded hash
      disagree. The action group's schema comes from `digest.json` the same way.
      The digest worker's `bedrock:InvokeAgent` is scoped to this one alias. A worker permitted to
      invoke any agent could run the suggester's prompt against the digest's budget, and the
      `agent_run` row would name the wrong capability.
      `platform_api_base_url` and the Cognito machine-client variables are left empty: provisioning
      a machine app client belongs to the identity module and is outside this task. The action
      group deploys and refuses to call anything, which is honest — a Lambda pointed at a guessed
      host is not.
      The schedule takes **one** retry where every other worker takes two: a retried digest spends
      its token budget again for the same day, and R-606 makes the model call the dominant cost.
- [X] T020a [US1] Copy `agents/action-groups/*.py` into the Lambda package in
      `.github/workflows/deploy-{dev,prod}.yml` — S43, R-601
      **Not anticipated by this list.** The package build copies `app connectors handlers
      migrations alembic.ini`; the action-group handlers live under `agents/` because
      `agents/README.md` owns their no-provider-SDK rule, so T020's `digest_tools.handler` would
      have resolved to nothing at runtime. Caught by reading the deploy workflow while wiring the
      Lambda, not by a test — nothing in CI executes a Lambda handler from the built zip.

**Checkpoint**: SC-001 and SC-004 provable at the mocked-test level.

---

## Phase 4: User Story 2 — Remediation Suggester (Priority: P1)

**Goal**: Every open finding carries an AI-drafted fix and blast-radius note, and nothing can
apply it (S44, FR-011–FR-014).

**Independent Test**: With open findings across every class, run the suggester; confirm each gets
a resource-specific suggestion marked `ai_generated`, and that no endpoint or control applies one.

### Tests for User Story 2

- [X] T021 [P] [US2] Write `backend/tests/unit/test_suggester_rules.py` — a suggestion is drafted
      per individual finding and names that finding's own resource (Clarification 2026-09-05); an
      existing `admin_seeded` suggestion is never overwritten; a finding no longer open is skipped
      — S44, FR-011, FR-013, FR-014
      **Done**, 13 tests. Two of the three rules the task names are enforced by a query and a
      conflict clause rather than by pure logic, so they are proved in T022 against a real
      PostgreSQL — asserting them against a stub session here would prove only that the stub agreed
      with the test. What is pure, and is proved here, is the vocabulary: a suggestion may cite
      **only its own finding's resource**. A tenant-wide vocabulary would let a suggestion name a
      real ARN belonging to a different finding and still validate — grounded, and still not about
      the thing it claims to be about, which is exactly what the 2026-09-05 clarification rules
      out.
      Also pinned: the fix and the blast-radius note are validated as **one** body. Validating only
      the fix would let a fabricated ARN sit in the note — the half a reader consults precisely
      because they are about to change something.
- [X] T022 [P] [US2] Write `backend/tests/integration/test_suggester_pipeline.py` — an
      `ai_generated` suggestion is written and rendered distinctly from `admin_seeded`; a
      suggestion failing grounding is rejected and the finding shows none; a truncated run keeps
      every validated suggestion produced before the cap (FR-004a) and the remainder are picked
      up next run — S44, FR-001, FR-004a, FR-011, FR-012
      **Done**, 14 tests. The cap is checked **before** each call, not after charging — a check
      that ran only afterwards would let every pass overspend once and report the overrun as if it
      had been authorised. There is a test counting invocations to prove it.
      Two tests the task did not name. One rejected suggestion must not withhold the others (the
      run still succeeds — item-wise means item-wise in both directions), and an agent suggestion
      must still be able to replace an *earlier agent* one: a conflict clause narrow enough to
      refuse admin-seeded rows could easily freeze the agent's own, making every re-run a no-op and
      the suggestion permanently stale.

### Implementation for User Story 2

- [X] T023 [US2] Extend `backend/app/governance/suggestions.py` with the `ai_generated` writer —
      the seam spec 003 defined and spec 004 rendered, which no code path has ever produced. Must
      not be reachable from any human-facing endpoint — S44, FR-011, FR-012, FR-013
      **Done.** FR-013 is enforced by the `on_conflict_do_update`'s `where`, not by reading first.
      A read-then-write leaves a window in which an admin seeds a suggestion between the check and
      the insert and the agent overwrites it — rare, silent, and exactly what the requirement
      forbids. The database refuses it instead, so the race cannot exist.
      Two writers now, and neither has a parameter that could make it write the other's `source`.
      FR-012's "distinguishable in the interface" is therefore true at the write layer rather than
      trusted to stay accurate at display time.
- [X] T024 [US2] Write `agents/definitions/suggester.json`, `agents/prompts/suggester.md` and
      `agents/action-groups/suggester_tools.py` — reads the finding, its resource and its rule
      through the platform API — S44, FR-003, R-602
      **Done.** The suggester's allowlist has no spend endpoint, unlike the digest's: this agent has
      no platform-computed figures and its prompt forbids stating numbers, so an endpoint returning
      amounts would only offer it something it must not use. Narrowing the surface is cheaper than
      relying on the prompt alone.
      The prompt is explicit that the platform executes nothing and that phrasing implying otherwise
      ("approve to apply") describes a capability that does not exist — T026 is what makes that
      instruction true rather than merely stated.
- [X] T024a [US2] Extract `agents/action-groups/_platform_api.py` from `digest_tools.py` — S43,
      S44, FR-056, R-602
      **Not anticipated by this list.** The suggester's action group differs from the digest's only
      in which paths it exposes; copying the token exchange, the HTTPS check and the response
      envelope into it would mean a fix to one silently not reaching the other — and those are the
      parts where a mistake is a security mistake rather than a wrong answer. Each handler is now
      about twenty lines: an allowlist and a delegation.
- [X] T025 [US2] Write `backend/handlers/suggester_worker_handler.py` — daily entrypoint,
      processing findings in priority order until the cost cap — S44, FR-004, FR-011
      **Done.** Priority order is the **digest's** order, not a second ranking. Two rankings would
      eventually disagree, and a user reading a digest and a suggestion queue would get two
      different accounts of what is urgent.
      One session per finding, not one per pass. A shared session would carry the previous
      finding's resource into this one's context, which is precisely how a suggestion stops being
      specific to its own resource (FR-011).
- [X] T026 [P] [US2] Verify no apply/execute control exists for a suggestion anywhere in
      `frontend/src/app/features/findings/` or the API surface, and add
      `backend/tests/integration/test_no_remediation_execution.py` asserting it — S44, FR-002,
      SC-005
      **Done**, 5 tests, asserted **structurally** rather than by calling an apply endpoint and
      expecting a 404 — that would prove one URL absent, where FR-002 claims no such capability
      exists. The tests enumerate the generated contract and the findings workbench's real source
      and fail on a plausible future addition.
      The first draft was too broad and **failed on `applyFilters()`** — applying a filter, not a
      fix. A test that flags that gets switched off within a week, taking the real check with it,
      so the matcher is now two-tier: `remediate`/`autofix` stand alone, while `apply`/`execute`
      count only alongside a remediation noun. Verified against twelve names, including
      `applySuggestion` (caught) and `applyFilters` (not).
      This became load-bearing with this phase rather than theoretical: before spec 006 no
      suggestion had an author who might imply it could be actioned.
- [X] T027 [US2] Extend `infra/modules/agents/` with the suggester agent, alias, guardrail,
      action-group Lambda and schedule — S44, R-601, R-606
      **Done**, `fmt -check` clean and `validate` passing for the module and both environments.
      A second agent rather than a second action group on the digest's: different prompts, tool
      surfaces and cost profiles, and sharing one would make `agent_run.definition_hash` ambiguous
      about which instruction produced a given output (FR-005). The guardrail *is* shared, because
      it encodes a property of the tenant's data rather than of a capability.
      The worker's timeout is 900s against the digest's 300s — this pass makes one invocation per
      open finding. It only needs to be long enough that the **cost cap** is what stops the pass,
      since a wall-clock timeout would kill it without recording an outcome. The schedule takes no
      retries at all: a suggester pass is resumable by design, so retrying would re-spend budget to
      reach findings tomorrow's pass reaches anyway.

**Checkpoint**: SC-002 and SC-005 provable at the mocked-test level. 🏁 Both P1 stories complete.

---

## Phase 5: P1 Completion — Role Matrix, Live Verification, Teardown

- [X] T028 Write `backend/tests/integration/test_role_matrix_insights.py` — the full matrix across
      this spec's P1 read surfaces (`GET /insights/digest`, `/insights/runs`,
      `/insights/rejections`): all three roles read; an unauthenticated caller gets 401; an
      authenticated caller with no recognised group gets 403. Assert response bodies, not just
      status codes, so an empty result cannot pass as success — S43, S44, FR-009
      **Done**, 16 tests. Two cells beyond the ones the task names.
      The no-group cell uses an **unrecognised** group rather than an empty list: a membership check
      that asks "does this token have groups?" passes an empty-list test and still admits a token
      carrying somebody else's. That shape matters here specifically — it is how an agent's machine
      principal would arrive if `build_agent_principal` were ever bypassed, and defaulting it to
      viewer would hand the intelligence layer a readable surface nobody granted it.
      A correctly-authorised admin **of another tenant** is also asserted across all three surfaces.
      A role matrix alone would miss it: every role check passes and the wrong tenant's data is
      served. Each surface queries independently, so each needs its own cell.
      The seeded run history contains a `failed` run as well as a succeeded one — a history holding
      only successes would let a surface that filtered failures out look identical to one that does
      not (FR-007a).
- [X] T029 [P] Run R-604's verification and record the result in research.md **before** any
      funding claim is made either way:
      `aws ec2 describe-vpc-endpoint-services --query 'ServiceNames' --output text | tr '\t' '\n' | grep -iE 'bedrock|monitoring'`
      A planning-time attempt returned a false "0 available" for every service because an expired
      SSO token was swallowed by `2>/dev/null || echo 0`. Do not repeat that pattern — let the
      command fail loudly — S43, R-604
      **Done, 2026-09-09, and the answer is the opposite of the working assumption.** Every service
      checked publishes an **Interface** endpoint in `us-east-1` across all six AZs —
      `bedrock-agent-runtime` (what `invoke_agent` needs) and `execute-api` (what the action-group
      Lambdas need) included. R-604 rewritten with the table.
      The command failed loudly first, exactly as intended: the SSO token had expired, and
      `InvalidClientTokenId` is what a real failure looks like instead of a plausible zero.
- [X] T029a [P] Correct spec 005's R-503 — S43, R-604a
      **Not anticipated by this list, and the more consequential half of T029.** R-503 states that
      "neither Cost Explorer nor IAM publishes an interface-endpoint service name" and predicts
      that the exact command T029 runs "would return nothing". It returns
      `com.amazonaws.us-east-1.ce` and `com.amazonaws.iam`, both Interface, both six AZs — along
      with `sts` and `tagging`, which spec 005's T051a treated as unfixable-without-NAT.
      IAM's service name has **no region prefix** because IAM is global; a check filtering on
      `com.amazonaws.<region>.` finds nothing and reads as absence. The grep was wrong, not the API.
      Why this outranks the factual error: R-503 reframed a **funding** decision as a **platform**
      limitation. A gap that costs money is a decision the maintainer makes; a gap AWS makes
      impossible is not a decision at all. That removed a real option from the table, silently,
      across three specs. R-407's own wording survives intact — it describes what is *provisioned*,
      which is still accurate and still verified.
- [X] T029b [P] Add the `bedrock-agent-runtime` and `execute-api` interface endpoints to
      `infra/modules/network/`, gated behind `enable_agent_endpoints` (default **off**), and expose
      the toggle as a `Deploy dev` dispatch input — S43, R-604, R-605
      **Not anticipated by this list**, and only possible because T029 falsified the assumption the
      list was written under. T030's own wording — "per T029's result, either exercise a real agent
      invocation or record ... at the mocked-test level" — has a branch that could not be taken
      until the endpoints were known to exist.
      **Default off, and that is the point.** An interface endpoint bills per AZ-hour whether or not
      anything calls it, and the standing decision not to fund this VPC's egress gap is unchanged.
      The dispatch input defaults false and a `push`-triggered run has no inputs at all, so a merge
      can never silently provision one — the same discipline `DEV_AUTO_DEPLOY` exists for, applied
      to a cost that accrues while idle rather than one that starts on merge.
      Both endpoints or neither: with Bedrock reachable but not `execute-api`, the agent reasons
      with no working action group and produces output that fails grounding — a worse signal than
      not running at all, because it looks like a model problem.

- [X] T030 **Live-verification.** Deploy to dev (dispatch `Deploy dev`). Confirm the deploy is
      healthy and the version matches trunk HEAD; confirm the digest and suggester Lambdas,
      their schedules and their log groups exist with the intended shape; confirm
      `GET /insights/digest` is reachable and correctly role-gated. **Per T029's result**, either
      exercise a real agent invocation or record SC-001/SC-002/SC-004 as proven at the
      mocked-test level with the R-605 bound stated — do not attempt a live invocation blind.
      **The precondition is two-deep, and both halves are blocked**: the model may be unreachable,
      *and* the findings/spend a digest summarises cannot be produced by a live scan, because
      account registration calls STS and the Tagging API with no route out of the VPC (spec 005
      T051a). Seed fixture data rather than expecting a live scan to supply it, and say so in the
      outcome — quickstart.md's Prerequisites now states this.
      Note: a `Deploy dev` run labelled *cancelled* may still have applied — check AWS directly
      rather than trusting the label (spec 005's own live-verification task found exactly that: a
      job timeout after `terraform apply` had completed, leaving an environment up and billing) — S43, S44, SC-001, SC-002, SC-004
      **Run, and it found a hard blocker that ends this spec's architecture.** Deployed from trunk
      `b3dc94c` with `enable_agent_endpoints=true`. Both `aws_bedrockagent_agent` resources failed:
      `AccessDeniedException: Bedrock Agents is in Maintenance Mode. New agent creation is not
      available for accounts without prior service usage.` 403 on `CreateAgent`, both agents. Not a
      permissions gap, not a retry candidate — an AWS service state change.
      **What was proven before the blocker.** The Terraform applies; the guardrail, both
      action-group Lambdas, both interface endpoints and all four log groups were created with the
      intended shape and correct 30-day retention. 8 of 12 shape checks passed. What could not be
      verified: agents, aliases, worker Lambdas, schedules, `GET /insights/digest` reachability, and
      the live invocation itself.
      **SC-001, SC-002 and SC-004 remain proven at the mocked-test level only**, and now
      permanently in this account rather than pending R-407 funding. FR-007a and SC-009 already make
      that a specified, tested state — 63 tests prove both pipelines with no model reachable — so P1
      is still honestly shippable. That is the requirement doing exactly the job it was written for.
      The first attempt (run 34405814425) was killed by a 30-minute job timeout mid-apply — see
      T030a — leaving a half-built environment, a stale state lock, and two resources in AWS that
      were never written to state. The second attempt (34408878706) then failed on that drift as
      well as the maintenance-mode error.
      **Consequence: constitution amended to v3.0.0.** Principle II mandated Bedrock Agents for the
      entire product GenAI layer, so it was mandating a service this account cannot use. It now
      names Bedrock AgentCore Runtime. Spec 006's agent layer needs re-planning; roughly 1,159 lines
      change and all 3,893 lines of its tests survive.
- [X] T030a Raise the deploy job timeouts — `deploy-dev.yml` 30 to 60, `deploy-prod.yml` 45 to 60 —
      S43, playbook §0.5.3
      **Found by T030 failing, and it is spec 005's failure recurring rather than a new one.** The
      dev apply ran 21:14:39 to 21:45:03 — 30.4 minutes against a 30-minute job timeout — and was
      killed **mid-`terraform apply`**.
      A job timeout during an apply rolls nothing back. It abandons the apply where it stands and
      reports the run as `cancelled`, a label that reads like "nothing happened". What existed
      afterwards: VPC, Aurora, both interface endpoints, the guardrail, both action-group Lambdas
      and all four log groups — no agents, no aliases, no worker Lambdas, no schedules. A half-built
      environment, billing.
      **It also left a stale state lock**, which is the part worth naming: a held lock blocks
      `destroy` as well as `apply`, so an unrecovered timeout does not merely leave an environment
      up — it leaves one that cannot be torn down. Released with `terraform force-unlock` (the
      holder was a runner that had already exited) before anything else could proceed.
      Spec 005's task list already said to check AWS directly rather than trust the run label, and
      that advice is what caught this — but nobody fixed the cause, so it cost a second environment.
      prod is raised too: it has never been built from scratch, so its first apply would be the cold
      one 45 minutes was never measured against.

- [X] T031 **Teardown and cost sweep**, immediately following T030, never separated from it by
      other work: full playbook §0.5.3 sweep, extended to confirm this spec's agents, aliases,
      guardrails, action-group Lambdas, schedules and log groups are gone. Take a baseline sweep
      *before* deploying so the post-teardown sweep is a real before/after. Check
      `retentionInDays==null` log groups specifically — spec 005's teardown found an RDS-created
      orphan Terraform never managed and `destroy` never touched — playbook §0.5.3
      **Done. The account is byte-identical to the pre-deploy baseline** — `diff` of the before and
      after sweeps is empty across Lambdas, agents, guardrails, schedules, RDS, VPCs, NAT gateways,
      VPC endpoints, API Gateways, Step Functions and log groups. `Destroy complete! Resources: 129
      destroyed.` Nothing bills. The only thing in the account is `serverlessrepo-RDKlib-Layer`,
      which predates this work and was in the baseline too.
      **131 resources went, not 129.** Two were invisible to `destroy`:
      `cloudpulse-dev-notification-worker` and the `cloudpulse-dev-daily-scan` schedule, created by
      the timed-out apply and never written to state. `destroy` cannot remove what it cannot see, so
      it would have reported complete while leaving them — and the Lambda was VPC-attached across
      two subnets, so its ENIs were pinning the VPC the teardown was waiting on. A teardown that
      trusts its own summary would have left a VPC behind and called it clean.
      **The baseline sweep is what made this checkable.** Taken before anything deployed, so the
      final check is a diff rather than someone eyeballing a list and deciding it looks empty.
      Zero-checks on manual RDS snapshots and EBS volumes are in the sweep too — both classic
      teardown survivors, both absent here.

**Checkpoint**: 🏁 **P1 complete.** Every P1 criterion provable; live-verification honestly bounded.

---

## Phase 5a: AgentCore Migration (T061–T067; Priority: P1, deferred — runs after P2)

**Why this phase exists**: AWS placed Bedrock Agents (classic) in maintenance mode and closed new
agent creation to accounts without prior usage (T030). Constitution v3.0.0 moved the GenAI layer to
Bedrock AgentCore Runtime; research R-613 records the decision and R-601 is superseded.

**Why it is scheduled after Phase 6 rather than before**: P2's coverage advisor, forecasts and
narratives are unaffected by which runtime hosts an agent — they are governance logic behind the
same grounding validator and run accounting. Rewriting the agent layer first would block work that
does not depend on it, and T061's outcome could still change the shape of T062–T067.

**What is NOT in this phase, deliberately**: nothing under `app/governance/`, `app/api/`,
`frontend/`, or `backend/tests/`. Those are runtime-agnostic and stay untouched (R-613). If a task
here starts wanting to change one, that is the signal the migration has slipped its boundary.

- [ ] T061 **Spike, before anything is rewritten.** Deploy a minimal agent to AgentCore Runtime in
      dev and invoke it once, end to end. Record the result in research.md as R-613a **whether it
      works or not** — S43, R-613
      This is the task that stops R-503's error from repeating. AgentCore's control plane answering
      a `list` call is not evidence that a runtime deploys, and T029a exists precisely because
      somebody once recorded a capability claim nobody had exercised. **No T062–T067 work starts
      until this returns.** Deploy the smallest possible runtime, invoke it, tear it down in the
      same session per playbook §0.5.3, and state the cost.
- [ ] T062 [P] Rewrite `agents/definitions/{digest,suggester}.json` for AgentCore's definition
      format; keep R-608's content-hash contract intact — S43, S44, FR-005, R-608, R-613
- [ ] T063 Replace `connectors/aws.py::invoke_agent` with its AgentCore equivalent — still the only
      place the Bedrock SDK appears (Principle V, FR-054), still raising rather than returning a
      partial (FR-007a) — S43, S44, FR-003, R-613
      If the AgentCore response reports truncation, wire it through: `digest_worker_handler.py`
      records that Bedrock Agents had no such signal, and T021's suggester is item-wise and would
      genuinely benefit.
- [ ] T064 Adapt `agents/action-groups/_platform_api.py` from the Bedrock Agents event envelope to
      AgentCore tool calls. **R-602 is unchanged** — the platform API only, never the database, no
      cloud credential, no provider SDK — S43, S44, FR-003, FR-056, R-602
- [ ] T065 Rewrite `infra/modules/agents/` for AgentCore: runtime, its execution role, guardrail
      attachment and both schedules. `terraform fmt -check -recursive infra/`, `terraform validate`
      and `terraform-ascii` must pass — S43, S44, R-605, R-606, R-613
- [ ] T066 [P] Re-run the full suite unchanged and confirm it still passes. **This is the
      assertion, not a formality**: R-613 claims the governance core, both pipelines, the
      `/insights` API and all 3,893 lines of tests are runtime-agnostic. A test file needing an edit
      falsifies that claim and should be reported, not quietly edited — S43, S44, SC-009
- [ ] T067 Live-verify the migrated layer and tear down immediately after, per playbook §0.5.3 and
      the T030/T031 pattern: baseline sweep first, check AWS directly rather than trusting a run
      label, and diff the after-sweep against the baseline — S43, S44, SC-001, SC-002, SC-004

**Checkpoint**: the P1 stories run on a runtime this account can actually create.

---

## Phase 6: User Story 3 — Coverage Advisor (Priority: P2)

**⚠️ P2 — STRETCH ONLY**: Per Principle VIII, nothing here may block or destabilise the P1 path.

- [X] T032 [P] [US3] **[P2]** Write `backend/tests/unit/test_coverage_advisor.py` — a gap
      closeable by a rule extension is proposed; one closeable by enabling an existing enricher is
      proposed; a type with **no** existing enrichment routine is surfaced as advisory only and
      never as an acceptable proposal (FR-015a, R-603) — S43, FR-015, FR-015a
- [X] T033 [P] [US3] **[P2]** Write `backend/tests/integration/test_coverage_proposal_flow.py` —
      accept applies tenant-wide on the next scan with no code change; reject is not re-proposed;
      a non-admin can read but not decide; an advisory gap has no decision endpoint at all — S43,
      FR-016, FR-017, FR-018
- [X] T034 [US3] **[P2]** Write `backend/app/governance/coverage_advisor.py` — gap detection
      against `coverage_definitions.json` and the rule registry, proposal creation, and the
      accept/reject transition — S43, FR-015, FR-016, FR-017, FR-018
- [X] T035 [US3] **[P2]** Write `agents/definitions/advisor.json`, `agents/prompts/advisor.md`
      and `agents/action-groups/advisor_tools.py` — S43, FR-003
- [X] T036 [US3] **[P2]** Write `backend/app/api/routers/coverage_proposals.py` —
      `GET /coverage-proposals`, `GET /coverage-proposals/advisory-gaps` (no decision endpoint, by
      design), `POST /coverage-proposals/{proposalId}/decision` admin-gated. Regenerate the
      contract and client — S43, FR-016, FR-017, FR-015a
- [X] T037 [P] [US3] **[P2]** Write `frontend/src/app/features/coverage-proposals/` — proposals
      with accept/reject for admins, advisory gaps rendered distinctly with no control at all;
      wire the route into `app.config.ts` — S43, FR-016, FR-015a
- [ ] T038 [US3] **[P2]** Extend `infra/modules/agents/` with the advisor agent and its schedule —
      S43, R-606
- [ ] T038b [US3] **[P2]** Write `backend/app/governance/advisor.py` and
      `backend/handlers/advisor_worker_handler.py` — the run that assembles inventory, calls
      `detect_gaps`, invokes the agent for the prose, and persists proposals and advisory gaps.
      **Blocks T038**: Phase 6 as generated has no advisor worker anywhere, and T038's schedule
      needs a Lambda to target. The enrichment registry is read in the handler, which
      `check_connector_boundary.py` already permits, and passed into `detect_gaps` as names — the
      shape T034 was written for — S43, FR-015, FR-015a, FR-003
- [ ] T038c [US3] **[P2]** Resolve how a **rule-extension** coverage gap is detected, or narrow
      FR-015 to drop the class. **Blocked, needs a decision, not code.** R-603 class 1 says a gap
      can be closed by "a new or widened rule over already-collected fields", and `advisor.md`
      instructs the agent to draft that rule. But a spec 003 rule (`RuleDefinition`: `required`,
      `allowedValues`, `formatPattern`, `severity`, keyed by tag key) has no resource-type scope —
      it applies to every resource in the tenant. So there is no rule a proposal could carry that
      covers *one uncovered resource type*, and `detect_gaps` correspondingly has no code path
      that emits `RULE_EXTENSION`. Either spec 003's rule model gains a resource-type scope (a
      cross-spec schema change), or FR-015 narrows to the enricher class and R-603's class 1 is
      struck — S43, FR-015, R-603
- [ ] T038d [US3] **[P2]** Decide where the enricher-candidate map lives, or record that the class
      is currently empty. `detect_gaps` takes `enricher_for_type` — which existing enrichment
      routine would suit a type not yet mapped to one — and nothing in the repository supplies it.
      Today it would legitimately be empty: `connectors/aws.py` notes its ten enrichers are tied
      1:1 to the ten types `coverage_definitions.json` already covers, so no existing routine is
      unmapped. With T038c open as well, this means the advisor currently produces **only**
      advisory gaps, and SC-003's accept path has no live source of proposals — which T058 half
      anticipates ("runs against seeded fixture inventory"). Worth stating in the spec rather than
      discovering at live verification — S43, FR-015, SC-003
- [X] T038a [US3] **[P2]** Add the `coverage_advisory_gap` entity — model in
      `backend/app/models/core.py`, its migration, the ERD regeneration, and the table's row in
      `specs/006-agentic-insights/data-model.md`. Surfaced by T036: FR-015a requires advisory gaps
      be displayed with the reason the advisor computed, and there is nowhere to keep one.
      `data-model.md` says advisory gaps are never a row in `coverage_proposal` and defines no
      other home; they cannot be recomputed at request time because the deciding input is
      `ENRICHMENT_FUNCTIONS` behind the connector boundary (Principle V), and deriving them from
      "uncovered type with no proposal row" would mean displaying a reason the platform invented
      rather than one it determined — S43, FR-015a
- [X] T038e [US3] **[P2]** Fix `record_advisory_gaps` writing a duplicate row when one uncovered
      resource type appears in two accounts. Inventory is per account, so `detect_gaps` returns one
      `AdvisoryGap` per account per type, and the table's uniqueness is per tenant — the second
      insert failed the whole advisor run on a duplicate rather than on anything wrong. Found in
      self-review after CI was green; `record_proposals` already guarded the same case with its
      `pending` set — S43, FR-015a

**Checkpoint**: SC-003 provable.

---

## Phase 7: User Story 4 — Metrics Collection (Priority: P2)

- [ ] T039 [P] [US4] **[P2]** Write `backend/tests/unit/test_metrics_collection.py` — a period
      already collected is not duplicated; a resource with no measurement is recorded as unknown,
      never zero (FR-020) — S50, FR-019, FR-020
- [ ] T040 [US4] **[P2]** Write `backend/app/governance/metrics.py` — normalise and persist
      `resource_metric` rows per resource and period — S50, FR-019, FR-020
- [ ] T041 [US4] **[P2]** Extend `backend/connectors/aws.py` with `get_metric_data(...)` —
      CloudWatch `GetMetricData`, the only place that SDK call appears — S50, FR-019, R-606
- [ ] T042 [US4] **[P2]** Write `backend/handlers/metrics_collector_handler.py` — scheduled
      collection; per-account failure isolated so one account's failure does not stop others —
      S50, FR-019
- [ ] T043 [US4] **[P2]** Extend `infra/modules/agents/` with the collector Lambda, its schedule
      and `cloudwatch:GetMetricData` — S50, R-606
      Note R-606: this is the one P2 cost that grows with inventory (resources × metrics ×
      periods). State the dev posture explicitly in the module.

---

## Phase 8: User Story 5 — Forecasting (Priority: P2)

- [ ] T044 [P] [US5] **[P2]** Write `backend/tests/unit/test_forecasting.py` — the calculation is
      deterministic: the same history always yields the same forecast (FR-022); a project below
      FR-021a's configured minimum period count yields "not enough data", never a projection from
      too few points, and one exactly at the minimum does forecast — S51, FR-021, FR-021a,
      FR-022
- [ ] T045 [P] [US5] **[P2]** Write `backend/tests/integration/test_forecast_backtest.py` —
      backtesting against held-out actuals reports a measured error, and re-running reproduces it
      exactly — S51, FR-022, SC-006
- [ ] T046 [US5] **[P2]** Write `backend/app/governance/forecasting.py` — the deterministic
      calculation, with FR-021a's minimum-period threshold read from the environment per R-612.
      **No model
      call may produce or alter a forecast figure** (FR-021, Clarification 2026-09-05) — S51,
      FR-021, FR-021a, FR-022
- [ ] T047 [US5] **[P2]** Write `backend/app/api/routers/forecasts.py` — `GET /forecasts`,
      `require_viewer`-gated. Regenerate the contract and client — S51, FR-021

---

## Phase 9: User Story 6 — Rightsizing (Priority: P2)

- [ ] T048 [P] [US6] **[P2]** Write `backend/tests/unit/test_rightsizing.py` — a persistently
      low-utilization resource is recommended down with its evidence and an estimated monthly
      saving; a high or variable resource is never recommended down (FR-023) — S52, FR-023
- [ ] T049 [US6] **[P2]** Write `backend/app/governance/rightsizing.py` — S52, FR-023
- [ ] T050 [US6] **[P2]** Write `backend/app/api/routers/rightsizing.py` — `GET /rightsizing`,
      `require_viewer`-gated, no apply control (FR-002). Regenerate the contract and client — S52,
      FR-023, FR-002
- [ ] T051 [P] [US6] **[P2]** Write `frontend/src/app/features/insights/` — rightsizing
      recommendations with their evidence inline; wire the route — S52, FR-023

---

## Phase 10: User Story 7 — Forecast Narratives (Priority: P2)

- [ ] T052 [P] [US7] **[P2]** Write `backend/tests/unit/test_narrative_validation.py` — a
      narrative whose figures match the chart passes; one introducing any figure the deterministic
      calculation did not produce is rejected and not displayed (FR-024) — S53, FR-024
- [ ] T053 [US7] **[P2]** Write the narrator agent definition, prompt and action group in
      `agents/`, reusing T007's validator with an exact-figure-match mode — S53, FR-024, FR-001
- [ ] T054 [P] [US7] **[P2]** Render narratives on the cost and forecast pages in
      `frontend/src/app/features/cost/`, suppressed entirely when validation fails — S53, FR-024,
      SC-007

**Checkpoint**: SC-007 provable. P2 scope complete.

---

## Final Phase: Polish & Cross-Cutting

- [ ] T055 [P] Write `agents/evals/` cases and wire the eval suite into `.github/workflows/ci.yml`
      — runs against recorded fixtures, never live Bedrock, so CI stays deterministic and free
      (R-609). A prompt change that breaks a grounding expectation must fail the PR — S43, S44,
      FR-005, R-609
- [ ] T056 [P] Update `backend/README.md`, `frontend/src/app/features/README.md`,
      `infra/README.md` and `agents/README.md` — the new governance modules, the three worker
      handlers, `infra/modules/agents/`, the new frontend areas, and what `agents/` now holds —
      Principle I
- [ ] T057 Add the spec 006 section to `AI_WORKFLOW_JOURNAL.md`. Spec 003's second analyze pass
      raised a missing journal section as **H1 CRITICAL** (a Principle I violation) and spec 002's
      H1 caught it before that; spec 005 had to add it retroactively as T026a. Written as its own
      task this time rather than discovered a fourth time — Principle I
- [ ] T058 **Live-verify P2** — deploy and exercise the coverage-proposal accept path end to end.
      SC-003 needs no model call, which makes it the P2 criterion most likely to be provable live
      — **but its input is not free either**: the advisor detects gaps from scanned inventory, so
      the accept path runs against seeded fixture inventory unless R-407 is funded. Verify the
      acceptance transition and its effect on the next scan's configuration; record explicitly
      what was proven against real AWS and what against fixtures. Do not repeat spec 005's R-511
      error of calling a capability live-verifiable because the capability itself makes no AWS
      call — S43, SC-003, FR-015a
- [ ] T059 **Teardown and cost sweep**, immediately following T058, never separated from it —
      playbook §0.5.3
- [ ] T060 Re-run `/speckit-analyze` on spec 006 and resolve any finding. Check *data
      preconditions*, not only API shapes: spec 005's analyze pass compared shapes and still
      missed that utilization's live verification was impossible because its input could not be
      produced live — Governance

**Checkpoint**: 🏁 **P1 and P2 complete at the mocked-test level**, with live-provability bounded
by whatever T029 establishes about Bedrock's VPC reachability.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → Phase 3+**: strictly sequential. Phase 2 is blocking for every story.
- **US1 and US2 are independent of each other** — different agents, different tables, different
  surfaces. Either could ship first; US1 is sequenced first only because the digest is the
  showcase capability.
- **US3 depends on nothing but Phase 2.** US4 feeds US5, US6 and US7 (metrics are the history
  forecasts and rightsizing both read). US7 depends on US5 for the figures a narrative states, and
  additionally on US6 wherever rightsizing figures are narrated — matching the spec's own wording
  for those stories rather than the narrower "US7 depends on US5" this line previously carried.
- **`infra/modules/agents/` is a shared-file lineage**: T020, T027, T038 and T043 each append to
  it. Sequential, never concurrent — each should pull latest trunk before editing rather than
  assume the file is as its branch found it. This is the same discipline spec 005 used for
  `infra/modules/cost/` after T009/T016/T047.
- **`connectors/aws.py` is touched twice** — T011 (P1) and T041 (P2). Not concurrent.
- **T030/T031 must stay adjacent**, and **T058/T059** likewise. Do not let Phase 6 work begin
  between a live-verification task and its teardown.
- **T029 gates T030's shape**: what live verification can even attempt depends on R-604's answer.

## Parallel Execution Example

Each story's test files are independent and can be written together:

```text
T013 [P] [US1] backend/tests/unit/test_digest_selection.py
T014 [P] [US1] backend/tests/integration/test_digest_pipeline.py
T021 [P] [US2] backend/tests/unit/test_suggester_rules.py
T022 [P] [US2] backend/tests/integration/test_suggester_pipeline.py
```

Phases 6 and 7 can proceed on separate branches once Phase 5 merges — neither touches a file the
other does, except `infra/modules/agents/` (see the lineage note above).

## Implementation Strategy

**MVP**: Phases 1–5 alone deliver the whole P1 demo path — a grounded daily digest and a
per-finding suggester, with every safety guarantee Principle IV requires and no P2 dependency.

**Incremental delivery**: Phase 2's shared foundation means each later story adds one agent, one
set of tools and one surface, rather than re-deriving grounding and cost accounting. P2 is
additive polish; none of it is a prerequisite for declaring P1 complete.
