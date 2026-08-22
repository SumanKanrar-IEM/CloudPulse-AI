# CI fixtures — proving each gate fails on its own

Nine check categories run on every pull request (FR-009). A gate that fails
everything is as useless as one that fails nothing, so **SC-003** requires each to be
shown failing *independently*, and FR-048a requires the contract gate to be shown
*passing* on an additive-only change.

Each file here breaks exactly one category. They are never imported, linted, or built
by the normal pipeline — `ops/ci-fixtures/` is excluded from every tool's scope.

## How to use them (task T034)

Copy one fixture into the tree it targets, open a pull request, confirm **exactly one**
check goes red and merge is unavailable, then revert. One PR per fixture.

| # | Fixture | Copy to | Expected failing check |
|---|---------|---------|------------------------|
| 1 | `01_style_violation.py.txt` | `backend/app/core/` | `lint` (ruff) |
| 2 | `02_type_violation.py.txt` | `backend/app/core/` | `typecheck` (mypy) |
| 3 | `03_failing_test.py.txt` | `backend/tests/unit/` | `test` (pytest) |
| 4 | `04_frontend_break.ts.txt` | `frontend/src/app/` | `frontend-build` |
| 5 | `05_invalid_terraform.tf.txt` | `infra/modules/network/` | `terraform-validate` |
| 6 | `06_breaking_contract.yaml.txt` | replace contract | `contract-compat` (oasdiff) |
| 7 | `07_inaccessible.html.txt` | a component template | `frontend-lint` (a11y) |
| 8 | `08_leaked_credential.tf.txt` | `infra/modules/network/` | `secret-scan` |
| 9 | `09_banned_dependency.toml.txt` | merge into `backend/pyproject.toml` | `dependency-allowlist` |
| 10 | `10_connector_leak.py.txt` | `backend/app/api/` | `connector-boundary` |
| ✅ | `11_additive_contract.yaml.txt` | merge into contract | **all green** — proves FR-048a |

Fixtures 9 and 10 are already verified locally: `ops/scripts/check_dependencies.py` and
`ops/scripts/check_connector_boundary.py` both exit 1 on them and 0 once reverted.
