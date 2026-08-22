# Runbook — provisioning a CloudPulse AI environment

**Target: a fresh AWS account reaches a working dev environment in under 60 minutes
using only this repository (SC-001).**

Written to be followed by someone who did not write it. If a step needs knowledge that
is not on this page, that is a defect in the runbook (FR-006), not in the reader.

> **Status:** steps 0–2 are complete and executable. Steps 3–7 depend on tasks in
> Phases 4–8 that are not yet implemented; each is marked with the task that fills it.

---

## 0. Prerequisites — gather before starting (~5 min)

| Need | Why | Blocks |
|---|---|---|
| An AWS account, empty | The target | everything |
| Console/CLI access with account-level permissions | The one-time bootstrap only | step 1 |
| Terraform ≥ 1.9, Python 3.12, Node 20, Docker | Toolchain | steps 2+ |
| An organisational identity provider emitting group membership | Sign-in and roles | step 5 |
| Directory rights to create three groups and manage membership | FR-039, and any later role change | step 5 |
| GitHub repository admin rights | To make CI checks required (SC-003) | step 6 |
| An alert email address | P2 alerting only (S7) | step 7 |

**No AWS access keys are needed at any point.** The bootstrap uses your own console
session; everything afterwards uses GitHub OIDC federation. If a step appears to ask
you for a long-lived key, stop — that is a constitution Principle III violation, not a
missing instruction.

---

## 0b. Authenticate (every session)

```bash
export AWS_PROFILE=cloudpulse-dev
aws sso login
aws sts get-caller-identity        # must show assumed-role/..., NEVER :root
```

**`AWS_PROFILE` must be exported before any terraform command.** Without it the AWS
provider walks the default credential chain and picks up whatever sits in
`~/.aws/credentials` — which is a different identity than the one you just verified.
The symptom is `InvalidClientTokenId ... security token is invalid` at plan time.

The profile is deliberately **not** hardcoded in the provider block: CI authenticates
through GitHub OIDC with no profile at all (FR-022), and the same definitions must work
both ways. Environment, not repository.

If `~/.aws/credentials` still holds a `[default]` block with static keys, delete it.
Anything left there silently outranks SSO whenever `AWS_PROFILE` is unset, and a stale
entry that is still live means an `apply` can run as the wrong identity.

---

## 1. Bootstrap — the one manual step (~10 min)

FR-001a permits exactly one manual step, and this is it. A remote state backend cannot
store its own creation, and an OIDC trust cannot be created by a workflow that has no
role to assume yet (research.md R-001). It is applied **once per account** and never
again.

```bash
cd infra/bootstrap
terraform init
terraform apply -var="environment=dev"
```

Creates: the versioned, encrypted, public-access-blocked S3 state bucket; the DynamoDB
lock table; the GitHub OIDC provider; and the deploy role whose trust is scoped to this
repository and the `pods/pod73` trunk.

**Record the two outputs.**

```bash
terraform output state_bucket
terraform output deploy_role_arn
```

- `state_bucket` and `lock_table` → uncomment and fill in `infra/envs/dev/backend.tf`.
- `deploy_role_arn` → add as the repository **variable** `AWS_DEPLOY_ROLE_ARN`.
  A *variable*, not a secret: a role ARN is an identifier, not a credential.

The plan creates **8 resources**: the state bucket plus its three configuration
resources (versioning, encryption, public-access block), the lock table, the OIDC
provider, the deploy role, and its policy attachment.

**Verify no long-lived credential was created:**

```bash
aws iam list-users --query 'Users[?contains(UserName, `cloudpulse`)]'
```

Expect `[]`. Anything else is a Principle III violation and must be removed.

---

## 2. Provision the environment (~15 min)

Normally the pipeline's job. Run by hand for the first apply or a fresh-account demo.

**Decide the cost profile first.** This is the first step that spends real money, and
the default is more expensive than it looks.

| Setting | Default | Effect |
|---|---|---|
| `enable_rds_proxy` | `true` | RDS Proxy is priced per ACU-hour with an **8-ACU minimum**, so it costs roughly twice the 0.5-ACU cluster it pools for — about **$88/mo** |
| `min_acu` | `0.5` | The cluster never scales below the floor, so it bills continuously — about **$44/mo** |
| VPC interface endpoint | always on | ~$15/mo (Secrets Manager, 2 AZs) |

Defaults total roughly **$147/mo (~$5/day)**, about **$70 for a two-week build**.
Confirm against current pricing before committing — these are estimates.

Two levers, both already wired:

```hcl
# infra/envs/dev/terraform.tfvars
enable_rds_proxy = false   # research.md R-003 records this as the documented
                           # fallback at demo scale (~10 users, NullPool).
                           # Saves ~$88/mo.
min_acu          = 0       # Aurora Serverless v2 scale-to-zero with auto-pause.
                           # Saves most of the remaining $44/mo while idle, at the
                           # cost of a cold start on the first request after idle —
                           # which matters for a live demo unless you warm it first.
```

Then:

```bash
cd infra/envs/dev
terraform init
terraform plan -out=dev.tfplan     # read it before applying
terraform apply dev.tfplan
```

**What this creates (29 resources):** VPC with two private subnets and two VPC
endpoints; Aurora Serverless v2 PostgreSQL 16 with an RDS-managed master credential;
optionally RDS Proxy; the raw-snapshot bucket; and the S3 + CloudFront frontend origin.

**The database password is never in Terraform state.** `manage_master_user_password`
makes RDS generate, store and rotate it in Secrets Manager. There is deliberately no
`master_password` argument anywhere in the module (Principle III).

**Confirm reproducibility before moving on (FR-003, SC-002):**

```bash
infra/tests/test_plan_idempotent.sh dev
```

Expect **PASS**. The script uses `terraform plan -detailed-exitcode`, so "no changes"
is an exit code rather than a phrase to grep for. A non-empty plan is a defect in the
definitions, not a diff to review away.

---

## 3. Apply the database schema — *task T074*

```bash
aws lambda invoke --function-name cloudpulse-dev-migrate \
  --payload '{"command":"upgrade","revision":"head"}' /dev/stdout
```

Runs inside the VPC because Aurora has no public endpoint and no database password ever
reaches a CI runner (R-002).

---

## 4. Deploy the application — *tasks T100–T101*

Merging to `pods/pod73` deploys dev automatically, **provided the `DEV_AUTO_DEPLOY` repository
variable is `true`** (task T133). It defaults to `false` on a fresh account so a routine merge
never silently re-provisions — and re-bills — a torn-down environment. Check or set it:

```bash
gh variable list                                  # look for DEV_AUTO_DEPLOY
gh variable set DEV_AUTO_DEPLOY --body "true"      # turn auto-deploy on
gh variable set DEV_AUTO_DEPLOY --body "false"     # turn it back off
```

With the variable `false`, deploy dev explicitly instead:

```bash
gh workflow run "Deploy dev" --ref pods/pod73
```

---

## 5. Create the first administrator

**This is done in the identity provider, not in the platform.**

```bash
terraform output cognito_user_pool_id
terraform output cognito_group_names     # the three groups, created from role_group_map
```

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <pool-id> --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
```

```bash
aws cognito-idp admin-add-user-to-group \
  --user-pool-id <pool-id> --username you@example.com --group-name cloudpulse-admins
```

**There is no in-platform way to do this, and that is deliberate.** FR-039 forbids a
bootstrap path, a seeded account, and a break-glass credential. The pool is created with
`allow_admin_create_user_only = true`, so Cognito's public sign-up is off — leaving it
on would have been an FR-031 violation shipped by omission.

Until someone is in a group, signing in yields a **signed-in but unauthorised** state.
That is expected behaviour, not a defect: the API returns 403 because no role resolves.

**Add the user to exactly one group.** A user in no mapped group, or in two, is
*refused* rather than resolved (FR-032a) — the platform will not pick one for them, in
either direction.

### Second apply: wire the pre-token trigger

The Cognito pool and the pre-token Lambda reference each other, so the first apply
leaves the trigger unset. After the API module exists:

```bash
terraform output pre_token_function_arn
```

Set `pre_token_lambda_arn` in the `identity` module block and re-apply. The platform is
fully functional without it — `app/core/security.py` enforces FR-032a independently
(research.md R-004, layer 2) — so this is an optimisation, not a prerequisite.

---

## 6. Make the CI checks required — *task T033*

In repository settings, protect `pods/pod73`:

- require all CI checks (FR-011 — no administrative bypass, no exceptions);
- block direct pushes;
- do **not** require a human approval — there is no second human. Constitution v2.0.0
  Principle VII makes the gate **green CI + a recorded AI review**.

---

## 7. Observability — *tasks T117–T122* (**P2**)

Subscribe the alert address to the SNS topic. P2: if it is skipped entirely, every P1
success criterion still holds.

---

## Confirm it works

```bash
curl -s https://<api-id>.execute-api.<region>.amazonaws.com/health | jq
```

Expect `status: healthy`, a healthy `database` check, and a `correlationId`.

Then walk `specs/001-platform-foundation/quickstart.md` V1–V8.

---

## Tearing down

```bash
./ops/teardown.sh dev
```

**Dev only.** Pointing it at prod refuses before touching anything (FR-005a, R-010).
Destroying prod requires a deliberate step outside this runbook, which is the point —
registered accounts, tagging rules, the SDA registry, and the append-only audit trail
are not rebuildable by re-scanning.

---

## Time budget (SC-001: under 60 minutes)

| Step | Budget |
|---|---|
| 0 Prerequisites | 5 min |
| 1 Bootstrap | 10 min |
| 2 Provision | 15 min |
| 3 Schema | 5 min |
| 4 Deploy | 10 min |
| 5 First admin | 5 min |
| Verify | 5 min |
| **Total** | **55 min** |

Record the actual per-step breakdown at task T046. If a step overruns, the breakdown is
what tells you which one.
