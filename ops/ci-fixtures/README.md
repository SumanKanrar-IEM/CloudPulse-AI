# CI fixtures — proving each gate fails on its own

Thirteen check categories run on every pull request (FR-009). A gate that fails
everything is as useless as one that fails nothing, so **SC-003** requires each to be
shown failing *independently and blocking merge*, and FR-048a requires the contract
gate to be shown *passing* on an additive-only change.

Each file here breaks exactly one category. They are never imported, linted, or built
by the normal pipeline — `ops/ci-fixtures/` is excluded from every tool's scope.

## Verified (task T034, 2026-08-22)

All 11 fixtures were run as real PRs against the live, protected trunk (PRs #6–#16).
**Every broken fixture showed `mergeStateStatus: BLOCKED`** — not just a red check, but
merge genuinely unavailable, which is the half of SC-003 a `terraform validate`-style
dry run cannot prove. Fixture 11's additive change showed `CLEAN, MERGEABLE`.

| # | Fixture | Copy to | Verified failing check(s) |
|---|---------|---------|------------------------|
| 1 | `01_style_violation.py.txt` | `backend/app/core/` | `lint (ruff)` **and** `typecheck (mypy)` — see note below |
| 2 | `02_type_violation.py.txt` | `backend/app/core/` | `typecheck (mypy)` only |
| 3 | `03_failing_test.py.txt` | `backend/tests/unit/` | `test (pytest + moto)` only |
| 4 | `04_frontend_break.ts.txt` | `frontend/src/app/` | `frontend (build + a11y lint)` only |
| 5 | `05_invalid_terraform.tf.txt` | `infra/modules/network/` | `terraform (fmt + validate) (dev)` **and** `(prod)` — see note below |
| 6 | `06_breaking_contract.yaml.txt` | see note on §6/§11 below | `contract-compat (oasdiff)` only |
| 7 | `07_inaccessible.html.txt` | a component template | `frontend (build + a11y lint)` only |
| 8 | `08_leaked_credential.tf.txt` | `infra/modules/network/` | `secret-scan` **and** `test (pytest + moto)` — see note below |
| 9 | `09_banned_dependency.toml.txt` | merge into `backend/pyproject.toml` | `dependency-allowlist` only |
| 10 | `10_connector_leak.py.txt` | `backend/app/api/` | `connector-boundary` only |
| ✅ | `11_additive_contract.yaml.txt` | see note below | **all 13 green, MERGEABLE** — proves FR-048a |

### Three real cross-check couplings, not bugs

- **#1 and #8 fail two checks each, by design.** An untyped Python snippet fails both
  `ruff` and `mypy` because production code (`app/`) is held to strict typing —
  nothing makes that avoidable, and it isn't worth writing an artificially
  well-typed style violation just to isolate one gate. A credential fails both
  `secret-scan` (gitleaks) *and* `test` (this repo's own `test_no_credentials.py`,
  which runs as part of the unit suite) — deliberate defense in depth, per FR-013.
  Both are evidence the gates overlap where they should, not that they are broken.
- **#5 fails both terraform jobs together** because `infra/modules/network/` is
  shared by `dev` and `prod` — one module, two environments, both validate it.
- **#6 and #11 need the generated client regenerated in the same commit**, or
  `client-drift` fails alongside the intended check (or, for #11, instead of leaving
  it green). Copy the fixture's schema change into the relevant Pydantic model under
  `backend/app/api/`, regenerate `backend/openapi.generated.yaml` and
  `frontend/src/app/api/`, and commit all three together — exactly what a real
  contract-changing PR must do (FR-048).

### Two fixture-authoring bugs, fixed in the files below

`03_failing_test.py.txt` originally used a literal comparison (`assert 1 == 2`), which
mypy's `comparison-overlap` check correctly flags as always-false — coupling it to
`typecheck` unintentionally. Changed to a runtime-computed value so only `pytest`
fires. `10_connector_leak.py.txt` was missing a blank line after its import, which
ruff's import-sort rule flagged — added.

## How to use them (task T034)

Copy one fixture into the tree it targets, open a pull request against `pods/pod73`,
confirm the check(s) above go red and `mergeStateStatus` is `BLOCKED`, then close
without merging and delete the branch. One PR per fixture. `ops/scripts/check_dependencies.py`
and `ops/scripts/check_connector_boundary.py` can also be run directly against
fixtures 9 and 10 for a fast local check before opening the PR.
