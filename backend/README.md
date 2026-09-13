# `backend/` — API, workers, and the governance data model

Python 3.12 on AWS Lambda (arm64). FastAPI + Mangum behind an API Gateway HTTP API.

## Layout and ownership

| Path | Owner | Contents |
|---|---|---|
| `app/api/` | spec 001 (extended by 002–006) | FastAPI app, error envelope, correlation middleware, routers. `app/api/routers/resources.py` (**spec 004**) is the governance dashboard's inventory read surface (`GET /resources`, `GET /resources/{id}`) — paged/filtered server-side, never the full inventory into a client at once (FR-011) **Spec 006** adds `insights.py` (digest, run history, rejection log — read-only, every role), `coverage_proposals.py` (proposals for every role, `POST …/decision` admin-only, and **no** advisory decision route by design), `forecasts.py` and `rightsizing.py` (computed on request, viewer-gated, no apply control) |
| `app/core/` | spec 001 | config, db session, security, audit, logging, deployments, agent access |
| `app/models/` | spec 001 (extended additively by 002–006) | SQLAlchemy models. Spec 006 adds `agent_run`, `insight_digest`, `grounding_rejection`, `coverage_proposal`, `coverage_advisory_gap` (a separate table with no decision columns, so an advisory gap cannot be decided by construction — FR-015a, T038a), `resource_metric`, `forecast` and `rightsizing_recommendation` |
| `migrations/` | spec 001 (extended additively by 002–006) | Alembic revisions |
| `handlers/` | spec 001 (extended by 002, 003) | Lambda entrypoints: `api_handler.py`/`migrate_handler.py`/`pre_token_handler.py`/`authorizer_handler.py` (spec 001), `scan_worker_handler.py` (spec 002), `compliance_validation_worker_handler.py`/`ownership_attribution_worker_handler.py` (spec 003 — SQS-triggered, one message per finalized scan), and **spec 005**'s three scheduled workers: `cost_ingestion_worker_handler.py` (daily — ingests spend, then runs every budget's threshold check in the same transaction, research.md R-505), `notification_worker_handler.py` (daily — day-0, then reminders, then the escalation flag, in that order so a finding reaching day 4 today is flagged today), and `iam_hygiene_worker_handler.py` (**weekly**, not daily: IAM last-used data changes slowly against a 90-day window, research.md R-510). All three are EventBridge Scheduler-triggered rather than SQS-triggered — they query what is due themselves (R-501). **Spec 006** adds five more scheduled workers: `digest_worker_handler.py` (daily digest, one Bedrock invocation), `suggester_worker_handler.py` (daily, one invocation per open finding, item-wise under the cost cap), `advisor_worker_handler.py` (daily coverage-gap detection — **deterministic, no model call**, tasks.md T038f), `metrics_collector_handler.py` (daily `cloudwatch:GetMetricData` per account per region, one account's failure isolated from the next), and the narrator, whose worker is deferred (T054a). The model-invoking ones cannot reach Bedrock from inside the VPC until R-407 is funded (research.md R-605); FR-007a makes that a recorded run failure, not an outage |
| `connectors/` | **spec 002** | the provider-agnostic `Connector` protocol (`base.py`) plus the one AWS implementation (`aws.py`) — role verification, whole-account discovery, targeted enrichment, and — since spec 003 — the bulk CloudTrail sweeps ownership attribution runs on (`sweep_cloudtrail_events`/`sweep_write_events`). Spec 005 adds `get_daily_spend` (Cost Explorer) and `iam_unused_analysis` (IAM last-used evidence, returned raw — the unused/not-unused judgement is `app/governance/iam_hygiene.py`'s, which is what lets FR-020 be tested without an AWS client). Spec 006 adds `invoke_agent` (Bedrock) and `get_metric_data` (CloudWatch, chunked at the API's 500-query ceiling and paginated, returning id-and-values dicts only); `AwsConnector.enrich()` now merges a tenant's accepted coverage proposals over the shipped definitions at read time (FR-017, T038g). The **only** place `boto3`/`botocore` may be imported outside `handlers/`, `app/core/db.py`, `migrations/env.py`, and `app/scan/orchestrator.py` (FR-054, enforced by `ops/scripts/check_connector_boundary.py`) |
| `app/scan/` | **spec 002** (extended by 006) | scan orchestration: `discovery.py`/`enrichment.py` (thin, no AWS SDK import — dispatch only), `orchestrator.py` (Step Functions execution lifecycle, diffing, deleted-marker sweep, and — since spec 003 — enqueueing one message per finalized scan to each governance SQS queue). Spec 006: `coverage.py::load_coverage_definitions` takes a tenant's accepted overrides and merges them at read time (the shipped file wins on conflict, FR-017), and `enricher_candidates.json` — empty today, and its loader says why — is the advisor's only source of proposable gaps |
| `app/governance/` | spec 003 (extended by **spec 004**) | tag-compliance and ownership business logic, no Lambda-runtime concerns: `sda_matching.py` (FR-008–FR-010b), `validation.py` (rule evaluation and the finding lifecycle, FR-013–FR-017), `scoring.py` (FR-018–FR-019a), `ownership.py` (direct-creator attribution and its P2 fallback chain, FR-020–FR-026), `identity_resolution.py` (P2 owner-identity resolution chain, FR-027/FR-028). **Spec 004** adds `suggestions.py` (a finding's remediation suggestion: fetch-or-none, and an admin-seed write that can never produce `source=ai_generated`, FR-018–FR-020a) and `scan_deltas.py` (a scan's `added`/`removed`/`changed` resource counts, computed at query time from existing `resource` timestamp columns — no new persisted state, research.md R-405). **Spec 005** adds `spend.py` (Cost Explorer ingestion, SDA attribution, and explicit gap rows, FR-001–FR-003), `budgets.py` (auto-created guardrails, threshold crossing, and the overrun finding, FR-015–FR-017), `notifications.py` (the day-0 email, day-2/4 reminders, and the day-4 escalation flag, FR-004–FR-014), `utilization.py` (active/idle classification over spec 002's persisted `resource.state`, with unknown-state resources excluded from both halves of the ratio, FR-018), and `iam_hygiene.py` (flag-only unused-principal analysis, FR-019/FR-020). **Spec 006** adds `grounding.py` (the deterministic validator every agent output passes before display — references against the store, figures against what the platform computed, with an `exact_figures` mode for narratives beside a chart, FR-001/FR-001a/FR-024, R-607), `agent_runs.py` (the cost cap and run-outcome rules, FR-004/FR-004a), `definition_hash.py` (content hash of prompt + definition onto every run row, FR-005, R-608), `digest.py` and `suggester.py` (the two model-invoking pipelines: platform selects and computes, agent explains, validator gates), `coverage_advisor.py` and `advisor.py` (gap detection and the proposal/advisory split — `ProposableGap` and `AdvisoryGap` are two types, not a flag, FR-015/FR-015a), `metrics.py` (CloudWatch queries as data, every (resource, kind) gets a row and an absent measurement is `is_unavailable` never zero, FR-019/FR-020), `forecasting.py` (least-squares in `Decimal`, no model import, not-enough-data as a state, backtest by hold-out, FR-021–FR-022), and `rightsizing.py` (low-and-not-variable over CPU history, class ladders and prices as data in `rightsizing_classes.json`, evidence carries the thresholds, FR-023). Forecasts and rightsizing are computed on request and their tables are not written (tasks.md T047a, T050a) |
| `app/workers/` | reserved, unused so far | Spec 003's own SQS-triggered Lambda entrypoints landed in `handlers/` instead (below), matching `scan_worker_handler.py`'s existing one-file-per-Lambda convention rather than this package's original plan-time placeholder — decided during `/speckit-tasks`, not an implementation-time improvisation. Spec 005 also put its three workers in `handlers/`, so this package remains unused. |

## Rules that bind code added here

**No stored credentials (Principle III).** The database password is created and rotated
by RDS (`manage_master_user_password`) and fetched at runtime through the execution
role. There is no `master_password` anywhere, and `config.py` actively rejects a literal
value in `db_secret_arn`.

**Tenant scoping is fail-closed (FR-030).** Use `tenant_session(...)`. `TenantSession`
wraps rather than subclasses `Session`, so there is no unfiltered `.query`. `.raw` exists
for the two legitimate exceptions — `deployment` and migrations — and using it to skip a
tenant filter is a violation a reviewer should reject.

**`audit_event` is append-only and permanent (FR-029, FR-029a).** Write through
`app.core.audit.write_audit_event` only. There is no update, no delete, and no purge —
the *absence* of a retention mechanism is the correct implementation, so adding one is a
defect.

**No role is ever stored (FR-031a).** `app_user` has no `role` column. The role is
derived from the directory group claim on every request. Zero groups and two groups are
both refused, never resolved (FR-032a).

**No provider SDK outside `connectors/` (FR-054).** Enforced by
`ops/scripts/check_connector_boundary.py` in CI.

## Running things

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```bash
pytest tests/unit -m "not integration"
```

```bash
pytest tests/integration -m integration    # needs Docker
```

Unit tests run with no AWS credentials — `conftest.py` strips inherited ones, so a test
that tries to reach AWS fails rather than succeeding quietly (FR-010).

## The API contract

`openapi.generated.yaml` is generated from the Pydantic models and is the **binding**
contract (FR-048). The copy under `specs/` is a design-time reference and is not
authoritative. Regenerate after any model change, or CI's staleness check fails the PR.
