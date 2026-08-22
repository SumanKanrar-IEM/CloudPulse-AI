# Runbook — changing the API contract (FR-048c, FR-057)

The OpenAPI document is **one unversioned, additive-only document** (FR-048a). CI fails
any pull request that makes a breaking change (FR-048b):

- removing a field
- renaming a field
- removing an endpoint
- making an existing parameter required
- narrowing a type

This runbook exists because a gate with no documented route forward gets bypassed. FR-057
requires the path to be written down *before* someone is tempted to disable the check.

---

## Additive changes — just do them

No ceremony required:

- a new endpoint
- a new **optional** field on an existing schema
- a **widened** type (`string` → `string | integer`)
- a new enum member *(see the caveat below)*

```bash
cd backend && python -c "import json; from app.api.main import openapi_document; print(json.dumps(openapi_document()))" > /tmp/openapi.json
oasdiff breaking specs/001-platform-foundation/contracts/openapi.yaml /tmp/openapi.json
```

**Enum caveat.** Adding a member is additive for a *request* field and breaking for a
*response* field — an existing client may switch exhaustively over the values it knows.
Treat a new response enum member as breaking unless every consumer handles unknowns.

---

## Breaking changes — add new, then remove old

Never a single edit. Three pull requests:

### PR 1 — add the replacement

Introduce the new field or endpoint alongside the old one. The old one keeps working.
Mark the old one `deprecated: true` so it is visible in the generated client.

```yaml
properties:
  ownerEmail:   { type: string }                  # existing, still populated
  owner:                                          # new shape
    type: object
    properties: { email: { type: string }, confidence: { type: string } }
```

Both are populated. This PR passes the gate because it is purely additive.

### PR 2 — move every consumer

Update all callers to the new shape. `frontend/src/app/api/` is generated, so this is a
change to the code that *uses* the client, not to the client itself. Grep for the old
field name and confirm zero remaining references.

### PR 3 — remove the old shape

Only once nothing references it. This PR *is* breaking, and CI will flag it — which is
correct and expected. Record in the PR description:

- the PR that added the replacement,
- evidence that no consumer references the old shape,
- that PRs 1 and 2 have merged.

**Do not disable the gate.** Use `oasdiff`'s explicit per-change exception, so the
allowance is scoped to that change and visible in the diff:

```bash
oasdiff breaking base.yaml revision.yaml --exclude-elements <specific-element>
```

---

## Two specs adding the same path

Each PR passes independently against the trunk, then conflicts once both merge. The
second to merge **must fail** rather than silently overwrite the first.

Because the contract is *generated* from the FastAPI routers, this surfaces as a Python
merge conflict or a duplicate `operation_id` — FastAPI rejects duplicates at startup, so
the app fails to build rather than shipping a contract where one endpoint has quietly
replaced another.

If it does reach the contract check: the second author rebases on the trunk, regenerates,
and resolves the overlap with the first author's shape. Do not merge both by renaming one
path — that leaves two endpoints doing the same job, which is how an API becomes
unlearnable.

---

## The rules, restated

| Rule | Where |
|---|---|
| One unversioned document, additive only | FR-048a |
| CI fails on the five breaking change kinds | FR-048b |
| Necessary breaks go add-new → migrate → remove-old | FR-048c |
| This procedure must exist in the repository | FR-057 |
| The contract is the binding frontend/backend contract | Principle V |
