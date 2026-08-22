# `backend/` — API, workers, and the governance data model

Python 3.12 on AWS Lambda (arm64). FastAPI + Mangum behind an API Gateway HTTP API.

## Layout and ownership

| Path | Owner | Contents |
|---|---|---|
| `app/api/` | spec 001 | FastAPI app, error envelope, correlation middleware, routers |
| `app/core/` | spec 001 | config, db session, security, audit, logging, deployments, agent access |
| `app/models/` | spec 001 | SQLAlchemy models for all 11 tables |
| `migrations/` | spec 001 (extended additively by 002–006) | Alembic revisions |
| `handlers/` | spec 001 | Lambda entrypoints: api, migrate, pre-token |
| `connectors/` | **spec 002** | reserved — see its README before adding anything |
| `app/scan/` | **spec 002** | discovery engine |
| `app/workers/` | **specs 003, 005** | SQS workers |

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
