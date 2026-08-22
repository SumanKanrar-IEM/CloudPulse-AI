# `api/` — GENERATED, DO NOT EDIT

Every `.ts` file here is generated from **`backend/openapi.generated.yaml`**, which is
itself generated from the FastAPI application's Pydantic models. Regenerate with:

```bash
cd frontend && npm run generate:api
```

## Why hand-editing here is a merge-blocking failure

The contract is the binding artifact between frontend and backend (Principle V,
FR-048). CI regenerates this directory and **fails the pull request on any diff** — an
edit here does not survive, it just breaks the build.

To change the client, change the Pydantic models. The chain is one-directional by
design:

```
app/api/**.py (Pydantic)  →  openapi.generated.yaml  →  frontend/src/app/api/
```

## Contract rules

| Rule | Requirement |
|---|---|
| One unversioned document, additive only | FR-048a |
| CI fails on removed/renamed field, removed endpoint, newly-required parameter, narrowed type | FR-048b |
| A necessary break goes add-new → migrate → remove-old | FR-048c, `ops/runbooks/contract-changes.md` |

## Prerequisite

The generator is a Java tool. CI runners have a JRE; locally:

```bash
brew install openjdk
export JAVA_HOME=/opt/homebrew/opt/openjdk
```

`openjdk` is keg-only — set `JAVA_HOME` rather than `brew link`, which shadows the
macOS Java stub system-wide.
