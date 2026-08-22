# `infra/` — Terraform

Two environments (FR-002), one shared module set. If a change is needed in an
environment that is not a variable, it belongs in the module.

## Layout

| Path | Contents |
|---|---|
| `bootstrap/` | **applied by hand, once per account.** State backend + GitHub OIDC trust |
| `modules/network/` | VPC, private subnets, VPC endpoints (no NAT gateway) |
| `modules/database/` | Aurora Serverless v2, RDS Proxy, RDS-managed credential |
| `modules/identity/` | Cognito pool, three role groups, app client |
| `modules/api/` | HTTP API, JWT authorizer, api/migrate/pre-token Lambdas |
| `modules/frontend/` | S3 origin + CloudFront with OAC |
| `modules/storage/` | raw scan snapshot bucket |
| `modules/observability/` | **P2** — dashboard and alarms; default off |
| `envs/{dev,prod}/` | root modules |

## Bootstrap is the one manual step

FR-001a permits exactly one. A state backend cannot store its own creation, and an OIDC
trust cannot be created by a workflow with no role to assume. It creates **no long-lived
credential**; everything after it runs through OIDC federation.

## Prod protection (FR-005a) — two layers, not three

1. `deletion_protection` on the prod cluster
2. `ops/teardown.sh` refuses a `prod` target **before invoking anything**

The originally-specified third layer, `lifecycle { prevent_destroy }`, is **not
implementable**: Terraform requires it to be a literal, so it cannot be conditional on
environment, and FR-002 mandates one shared module set. See research.md R-010 —
the spec was corrected rather than worked around.

Layer 2 is the important one. The "teardown aimed at prod" edge case requires refusal
*before* anything is touched, which neither of the others provides.

## Retention is declarative (SC-014)

| Data | Mechanism | Value |
|---|---|---|
| Logs | `retention_in_days` from a shared local | 30 days |
| Prod backups | `backup_retention_period` | 7 days |
| Audit events | **no mechanism at all** | indefinite |

The audit row is deliberate: FR-029a makes the *absence* of an expiry the correct
implementation. Treat any lifecycle rule appearing on that table as a defect.

## Local use

```bash
export AWS_PROFILE=cloudpulse-dev && aws sso login
```

`AWS_PROFILE` must be exported before any terraform command — otherwise the provider
walks the default credential chain and picks up a different identity than you verified.

```bash
terraform fmt -check -recursive infra/ && terraform -chdir=infra/envs/dev validate
```
