# `infra/` — Terraform

Two environments (FR-002), one shared module set. If a change is needed in an
environment that is not a variable, it belongs in the module.

## Layout

| Path | Contents |
|---|---|
| `bootstrap/` | **applied by hand, once per account.** State backend + GitHub OIDC trust |
| `modules/network/` | VPC, private subnets, S3 and Secrets Manager endpoints. Two opt-in switches, both off by default and billed per hour while on: `enable_agent_endpoints` (a `bedrock-agentcore` interface endpoint) and `enable_egress` (**a single-AZ NAT gateway**, T143) — the latter is what a live-verification window turns on so the Lambdas can reach STS, the Tagging API, Cost Explorer, SES and AgentCore (R-407). `Deploy dev` exposes both as dispatch inputs; a push-triggered deploy never sets them |
| `modules/database/` | Aurora Serverless v2, optional RDS Proxy (`enable_rds_proxy`, off), RDS-managed credential |
| `modules/identity/` | Cognito pool, three role groups, app client |
| `modules/api/` | HTTP API, Lambda authorizer, api/migrate/pre-token/authorizer Lambdas |
| `modules/frontend/` | S3 origin + CloudFront with OAC |
| `modules/storage/` | raw scan snapshot bucket (versioned; `force_destroy` in dev only, so a teardown after real scans completes — T146), 30-day-class lifecycle rule (spec 002, research.md R-207) |
| `modules/scan/` | **spec 002** — scan-worker Lambda, Step Functions Standard state machine (`scan_workflow.asl.json`, validated by `ops/scripts/check_stepfunctions_asl.py`), EventBridge Scheduler daily trigger, cross-account onboarding CloudFormation template. Since spec 003: also grants the scan-worker `sqs:SendMessage` on the two governance queues below (`finalize_scan`'s enqueue, research.md R-303) |
| `modules/governance/` | **spec 003** — two SQS queues + DLQs (`compliance-validation`, `ownership-attribution`; Standard not FIFO, research.md R-306) and their Lambda workers (arm64, sized like the scan-worker). Declared *before* `modules/scan/` in each `envs/{dev,prod}/main.tf` so its queue ARN/URL outputs can feed into `modules/scan/`'s variables — the reverse order would be a Terraform dependency cycle |
| `modules/cost/` | **spec 005** — three EventBridge Scheduler-triggered Lambdas (arm64, 512MB, VPC-attached, research.md R-510): `cost-ingestion-worker` (daily, `ce:GetCostAndUsage`), `notification-worker` (daily, `ses:SendEmail` scoped to the one configured sending identity), and `iam-hygiene-worker` (**weekly**, five `iam:*` **read** calls and deliberately no `iam:Delete*`/`Update*`/`Put*` — FR-019's flag-only rule is enforced by the IAM policy, not merely by the code). **None of the three can reach its AWS API without egress**: Cost Explorer and IAM publish no VPC interface endpoint at all (an AWS platform limitation), and SES's was priced and declined (research.md R-503/R-504/R-511, R-407). With `enable_egress` on they can — cost ingestion ran live that way in T144 |
| `modules/agents/` | **spec 006** — the intelligence layer's compute. **One Bedrock AgentCore Runtime** hosting every agent capability (`agents/runtime/main.py`), deployed from a code zip in a versioned private bucket — no container, no ECR (R-613a); its execution role scoped to the inference profile *and* the regional foundation model the definitions name (R-613b); its log group declared with a retention so `destroy` removes it. The guardrail it applies. A worker Lambda per capability; EventBridge Scheduler daily triggers ordered scan (06:00) → metrics (07:30) → advisor (08:00) → digest (09:00) → suggester (10:00). The advisor deploys a worker and a schedule and no runtime call — its run is deterministic (tasks.md T038f). The metrics collector carries `cloudwatch:GetMetricData` and the same ExternalId/scanner-role scope every account-touching worker has; it is the one P2 cost that grows with inventory, and the module states the dev posture (R-606). **Before deploying**: the workers are VPC-attached, so they reach `bedrock-agentcore:InvokeAgentRuntime` only with `enable_egress` (T143) or the gated `bedrock-agentcore` endpoint (R-605); the runtime itself reaches the platform API publicly, so `execute-api` is gone. The model is Amazon Nova 2 Lite, which needs no Marketplace subscription (R-613c, replacing the Anthropic model R-613b found blocked on this account). The full worker → runtime → model → grounding path ran live with real findings in T144. Requires provider `~> 6.0` (T065) |
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

## Frontend runtime config (spec 004, research.md R-401)

`modules/identity/`'s `client_id`/`hosted_ui_domain` outputs are re-exported at the
env level (`cognito_client_id`/`cognito_hosted_ui_domain` in `envs/{dev,prod}/outputs.tf`)
so the deploy workflows (`.github/workflows/deploy-{dev,prod}.yml`, not this directory)
can inject them, alongside `api_endpoint`/`frontend_url`, into the already-built
`index.html` as `window.__CLOUDPULSE_CONFIG__` — the API Gateway URL isn't known until
after `terraform apply`, which runs after the frontend build, so this can't be baked in
at build time the way the rest of the Angular bundle is.

## Local use

```bash
export AWS_PROFILE=cloudpulse-dev && aws sso login
```

`AWS_PROFILE` must be exported before any terraform command — otherwise the provider
walks the default credential chain and picks up a different identity than you verified.

```bash
terraform fmt -check -recursive infra/ && terraform -chdir=infra/envs/dev validate
```
