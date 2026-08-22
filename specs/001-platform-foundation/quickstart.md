# Quickstart & Validation Guide: Platform Foundation

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-22

How to stand this up and how to prove it works. Every scenario below maps to a numbered success
criterion in the spec, so this file doubles as the acceptance script for the demo.

Details live elsewhere and are not repeated here: schema shape in [data-model.md](./data-model.md),
the API contract in [contracts/openapi.yaml](./contracts/openapi.yaml), and the reasoning behind
each design decision in [research.md](./research.md).

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Two AWS accounts | One dev, one prod (spec Dependencies) |
| Console access for the one-time bootstrap | Needed only for `infra/bootstrap/` — see R-001 |
| Terraform >= 1.9, Python 3.12, Node 20, Docker | Docker is for Testcontainers/LocalStack |
| Directory rights to create three groups | Prerequisite for FR-039 and any role change |
| Repository admin rights | To make CI checks required on `pods/pod73` (blocks SC-003) |
| An alert email address | For P2 alerting only |

---

## Local development

```bash
git clone <repo> && cd cloudpulse-ai
```

```bash
cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

```bash
cd frontend && npm ci
```

Run the full gate locally before opening a PR — these are the same seven checks `ci.yml` runs
(FR-009), so a green run here means a green run there:

```bash
make check
```

Individually:

```bash
ruff check backend && mypy backend && pytest backend/tests/unit
```

```bash
cd frontend && npm run lint && npm run build
```

```bash
cd infra/envs/dev && terraform validate && terraform plan
```

Integration tests need Docker running (Testcontainers PostgreSQL + LocalStack, per R-007):

```bash
pytest backend/tests/integration
```

---

## First-time provisioning (SC-001 — target: under 60 minutes)

### 1. Bootstrap, once per account, by a human

```bash
cd infra/bootstrap && terraform init && terraform apply -var="environment=dev"
```

Creates the state bucket, lock table, GitHub OIDC provider, and deploy role. This is the only step
requiring human credentials; everything after it runs through OIDC. Record the deploy role ARN as a
repository variable.

### 2. Provision the environment

Normally this is the pipeline's job. For the very first apply, or for a fresh-account demo:

```bash
cd infra/envs/dev && terraform init && terraform apply
```

### 3. Apply the schema

```bash
aws lambda invoke --function-name cloudpulse-dev-migrate \
  --payload '{"command":"upgrade","revision":"head"}' /tmp/migrate.json
cat /tmp/migrate.json
```

Invoke to a real file, never `/dev/stdout`: the CLI's own status metadata
(`{"StatusCode":200,...}`) and the Lambda's response payload land on the same stream and
concatenate into two JSON documents on one line, which breaks any `jq` parsing of the result
(playbook §0.5.1).

### 4. Create the first administrator

In the Cognito console (or by CLI), create your user and add them to the `admin` group. **There is
no in-platform way to do this** — that is FR-039 working as specified, not a missing feature. Until
someone is in a group, signing in yields a signed-in-but-unauthorised state.

**Get a token for the validation scenarios below** (V5, V6 use `$TOKEN`):

```bash
CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id <pool-id> \
  --query 'UserPoolClients[0].ClientId' --output text)
AUTH=$(aws cognito-idp admin-initiate-auth --user-pool-id <pool-id> --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=<your-email>,PASSWORD=<your-password>)
TOKEN=$(echo "$AUTH" | jq -r '.AuthenticationResult.IdToken')
```

Use the **ID token**, not the access token — Cognito's access token never carries an `email`
claim, so `/me` would return an empty email if you passed that one instead (playbook §0.5.4).
The Lambda authorizer accepts either token type (both are RS256-signed by the same pool), so
this is easy to get wrong silently: it will look like it works and the email will just be
missing.

### 5. Confirm

```bash
curl -s https://<api-id>.execute-api.<region>.amazonaws.com/health | jq
```

Expect `status: healthy`, a `database` check that is also healthy, and a `correlationId`.

---

## Validation scenarios

Each scenario states what to do and what proves it. Run them in order; later ones assume earlier
ones passed.

### V1 — Reproducibility (SC-002 · US1)

1. `terraform apply` a second time with no changes → expect **"No changes"**. Any non-empty plan is
   a defect in the definitions, not noise to accept.
2. Change something by hand in the console, re-run `terraform plan` → expect the drift reported.
3. Tear down dev and re-provision → expect a functionally identical environment.
4. Point the teardown script at prod → **expect it to refuse before touching anything** (R-010).

```bash
./ops/teardown.sh prod   # must exit non-zero, having changed nothing
```

### V2 — The merge gate (SC-003, SC-004 · US2)

Open one PR per check category, each breaking exactly one thing, and confirm each independently
turns the PR red and makes merge unavailable — **including for the author** (FR-011).

| # | Break this | Expected failing check |
|---|---|---|
| 1 | Add an unformatted file | ruff |
| 2 | Assign a `str` to an `int` | mypy |
| 3 | Invert an assertion in a unit test | pytest |
| 4 | Reference a missing Angular symbol | frontend build |
| 5 | Add an invalid Terraform attribute | terraform validate |
| 6 | Rename a field in a Pydantic response model | oasdiff (FR-048b) |
| 7 | Add a `<button>` with no accessible name | a11y lint (FR-047b) |
| 8 | Commit a plausible-looking AWS key | secret scanning (FR-013) |

Also confirm the inverse (FR-048a): a PR that only *adds* an optional field passes the contract
check. A gate that fails everything is as useless as one that fails nothing.

Time the suite — SC-004 requires a result within 10 minutes.

### V3 — Delivery (SC-005, SC-006 · US3)

1. Merge a visible change to `pods/pod73`. Expect dev updated with **zero human actions** within
   15 minutes, migrations applied before traffic shifts, and a `deployment` row recorded.
2. Trigger a prod release → expect it to **pause** at the environment approval gate.
3. While paused, confirm prod is byte-for-byte unchanged.
4. Approve → expect the release to proceed and `approved_by` / `approved_at` to be recorded, plus
   an `audit_event`.

### V4 — Schema and migrations (SC-007 · US4)

```bash
pytest backend/tests/integration/test_migrations.py -v
```

Covers: every revision applied in order to an empty database yields a shape matching the committed
ERD; the newest revisions applied to a *populated* database lose zero rows (FR-026); and the
audit-table append-only controls hold — an `UPDATE` and a `DELETE` against `audit_event` must both
raise (FR-029).

### V5 — Identity and roles (SC-008, SC-013 · US5)

Run the role matrix. Every cell must produce the expected allow or refuse:

| Caller | Admin action | Operator action | Read-only action |
|---|---|---|---|
| unauthenticated | 401 | 401 | 401 |
| viewer | 403 | 403 | 200 |
| operator | 403 | 200 | 200 |
| admin | 200 | 200 | 200 |
| **no mapped group** | 403 | 403 | 403 |
| **two mapped groups** | 403 | 403 | 403 |

The last two rows are the ones that matter most — they are FR-032a, and the failure mode they guard
against (silently picking one group) looks like success from every other angle.

Then confirm propagation (SC-013): move a user from `operator` to `viewer` in the directory, and
confirm operator actions are refused within 1 hour with no action taken inside the platform.

Finally, confirm the negative: **no endpoint and no screen exists through which any role can be
assigned.** Search the generated OpenAPI document for a role-mutating operation — there must be
none.

### V6 — API behaviour (SC-009, SC-010 · US6)

Force each failure kind and confirm all four return the identical `ErrorEnvelope` shape with a
`correlationId`: invalid input (422), unauthorised (401), forbidden (403), missing record (404).

```bash
curl -s -H "Authorization: Bearer $TOKEN" ".../me?bad=1" | jq '.error | keys'
```

Then take any `correlationId` from a response and find the complete request trace in the logs
within 2 minutes (SC-010). Confirm no log line contains a credential, token, or raw tag value
(FR-046).

Stop the database and re-check `/health` → expect **503 with `status: unhealthy`**, not a timeout
and not a false healthy (FR-042).

### V7 — Retention (SC-014)

Verify by inspecting the environment, not the code:

```bash
aws logs describe-log-groups --query 'logGroups[].{name:logGroupName,days:retentionInDays}'
```

Expect 30 days on every group. Expect `backup_retention_period` of 7 on the prod cluster. Expect
**no lifecycle rule, no expiry, and no purge job touching `audit_event`** — here the correct
finding is the absence of a mechanism (FR-029a), so a reviewer should treat discovering one as the
defect.

### V8 — Accessibility (SC-015 · P1 portion)

```bash
cd frontend && npx playwright test
```

Expect zero axe-core violations on the shell. Then operate the shell end to end **using only the
keyboard**, confirming the focused control is visible at every step — this half is manual by
design (FR-047b is explicit that automated rules do not prove it).

### V9 — Observability (SC-011) — **P2, run last**

Force each alarm condition and confirm an email is delivered within 5 minutes: drive the API
error rate above threshold, fail a scan, and push an item to the DLQ.

**If V9 is skipped entirely, V1–V8 must still all pass.** That is the Principle VIII check on this
spec: P1 stands alone.

---

## Definition of done for this spec

- [ ] V1–V8 pass (P1). V9 passes or is consciously dropped as P2.
- [ ] A fresh account reaches a working dev environment in under 60 minutes using only the repo.
- [ ] All seven CI checks are **required** on `pods/pod73` with no override path.
- [ ] The ERD in `ops/erd/` matches the schema at head.
- [ ] `agents/`, `app/workers/`, `app/scan/`, `connectors/`, and `features/` exist with their
      contracts in place and implementations empty, so specs 2–6 can start in parallel.
- [ ] A repo-wide scan finds zero credentials or long-lived keys (SC-012).
- [ ] The provisioning runbook has been followed by someone who did not write it.
