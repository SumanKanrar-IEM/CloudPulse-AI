# Phase 1 Data Model: Platform Foundation

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-22

This spec owns the *shape* of the governance record (FR-024). The behaviour that fills these tables
belongs to specs 2–6. Every table below is created by this spec's migrations so that five people
can build against a settled schema from day one; most arrive empty and stay empty until their
owning spec lands.

**Engine**: Aurora Serverless v2 PostgreSQL 16 · **ORM**: SQLAlchemy 2.0 declarative ·
**Migrations**: Alembic, ordered, each declaring reversibility (FR-025, FR-027)

---

## Cross-cutting conventions

These apply to every table and are enforced by review and by the migration template, not restated
per entity.

| Convention | Rule | Requirement |
|---|---|---|
| Primary key | `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` | — |
| Tenant scoping | Every table except `tenant` carries `tenant_id UUID NOT NULL REFERENCES tenant(id)`, indexed, and every query filters on it | FR-030 |
| Timestamps | `created_at`, `updated_at` — `TIMESTAMPTZ NOT NULL DEFAULT now()` | — |
| Soft delete | Not used. Records are either live or genuinely removed; audit events are never removed at all | FR-029 |
| Naming | Singular snake_case table names, `*_id` foreign keys | — |
| Enums | PostgreSQL native `ENUM` types, extended by migration | — |
| Naming across artifacts | One concept, three deliberate names: spec §Key Entities calls it **User**, this document's table is **`app_user`** (`user` is reserved in PostgreSQL), and the API contract's response schema is **`CurrentUser`**. Same concept throughout; the divergence is intentional, not drift | — |

**Tenant isolation is a query-layer responsibility in this MVP.** A shared SQLAlchemy session
dependency injects the caller's `tenant_id` and every repository filters on it. PostgreSQL
row-level security was considered and deferred — it is the stronger control, but with one seeded
tenant and a single application role it adds ceremony without changing observable behaviour.
Recorded here because it is the natural hardening step if multi-tenancy ever becomes real.

---

## Entities

### 1. `tenant` — owned by this spec

The organisational boundary. Exactly one row is seeded by migration in the MVP.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `name` | TEXT | NOT NULL, UNIQUE | |
| `status` | ENUM(`active`,`suspended`) | NOT NULL, default `active` | |

**Validation**: `name` non-empty, 1–200 chars. **Lifecycle**: `active` ⇄ `suspended`. No delete.

---

### 2. `app_user` — owned by this spec

A projection of a Cognito identity, existing to attribute audit events and display a human-readable
name. **Holds no password and no role** — the role is derived from the directory group claim on
every request (FR-031a, FR-038).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tenant_id` | UUID | FK, NOT NULL | |
| `cognito_sub` | TEXT | NOT NULL, UNIQUE | Cognito subject claim |
| `email` | TEXT | NOT NULL | |
| `display_name` | TEXT | NULL | |
| `last_seen_at` | TIMESTAMPTZ | NULL | Updated on authenticated request |

**Validation**: `cognito_sub` immutable once written. **Note**: there is deliberately no `role`
column — adding one would create a second source of truth and violate FR-031a. A reviewer should
treat any PR introducing one as a constitution violation.

**Lifecycle**: created on first authenticated request (just-in-time), never deleted. Access is
governed entirely by directory group membership, so removing a person from the directory ends
their access without touching this table (FR-038a).

---

### 3. `audit_event` — owned by this spec, written by every spec

Append-only, never expires (FR-029, FR-029a).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tenant_id` | UUID | FK, NOT NULL | |
| `actor_user_id` | UUID | FK → `app_user`, NULL | NULL for system/pipeline actors |
| `actor_label` | TEXT | NOT NULL | Human-readable actor, incl. non-user actors |
| `action` | TEXT | NOT NULL | e.g. `account.register`, `deploy.approve` |
| `target_type` | TEXT | NOT NULL | |
| `target_id` | TEXT | NULL | |
| `correlation_id` | UUID | NULL | Ties the event to its request (FR-044) |
| `payload` | JSONB | NULL | Redacted; never credentials or raw tag values |
| `occurred_at` | TIMESTAMPTZ | NOT NULL, default `now()` | |

**Enforcement of append-only (FR-029)** — three layers, because a single one is bypassable:

1. The application role is granted `INSERT` and `SELECT` on this table and **not** `UPDATE` or
   `DELETE`, via a grant applied in migration.
2. A `BEFORE UPDATE OR DELETE` trigger raises an exception.
3. No ORM model method or repository exposes update or delete.

No lifecycle policy, no partition dropping, no purge job — per FR-029a, the correct implementation
is the *absence* of any expiry mechanism.

---

### 4. `deployment` — owned by this spec

Satisfies FR-023 (record what was deployed, where, when, by whom) and FR-018 (approver identity for
prod, as an immutable record).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `environment` | ENUM(`dev`,`prod`) | NOT NULL | |
| `git_sha` | TEXT | NOT NULL | |
| `triggered_by` | TEXT | NOT NULL | GitHub actor |
| `approved_by` | TEXT | NULL | Required for `prod` |
| `approved_at` | TIMESTAMPTZ | NULL | Required for `prod` |
| `self_approved` | BOOLEAN | NOT NULL, default false | Per spec Assumptions, permitted but recorded |
| `migration_revision` | TEXT | NULL | Alembic revision after deploy |
| `status` | ENUM(`running`,`succeeded`,`failed`) | NOT NULL | |
| `started_at` / `finished_at` | TIMESTAMPTZ | NOT NULL / NULL | |

**Validation**: `CHECK (environment <> 'prod' OR (approved_by IS NOT NULL AND approved_at IS NOT
NULL))` — a prod deployment row cannot exist without a recorded approver (FR-017, FR-018).
Approval also writes an `audit_event`.

**Lifecycle**: `running` → `succeeded` | `failed`. Terminal states are immutable.

---

### 5–10. Downstream entities — schema owned here, behaviour owned elsewhere

**Delegation is now explicit in the spec** (FR-055): the `finding` lifecycle states and the SDA
grouping and roll-up semantics are spec 3's to define. The states shown below are the schema's
accommodation of them, not the authoritative definition — spec 3 may extend the enum by additive
migration without renegotiating this table.

Created empty by this spec's migrations so downstream specs start against a settled shape. Column
lists here are the agreed minimum; owning specs extend them by additive migration.

| # | Table | Owning spec | Minimum shape | Key constraints |
|---|---|---|---|---|
| 5 | `cloud_account` | 2 | `tenant_id`, `aws_account_id`, `alias`, `connection_mode` ENUM(`local`,`assume_role`), `role_arn`, `external_id_ref`, `scan_regions` TEXT[], `status` | UNIQUE(`tenant_id`,`aws_account_id`). **No credential columns** — `external_id_ref` is a Secrets Manager reference, never a value (FR-007, Principle III) |
| 6 | `resource` | 2 | `tenant_id`, `cloud_account_id`, `arn`, `resource_type`, `region`, `service`, `tags` JSONB, `parent_resource_id`, `first_seen_at`, `last_seen_at` | UNIQUE(`tenant_id`,`arn`); self-FK for parent; GIN index on `tags` |
| 7 | `rule` | 3 | `tenant_id`, `key`, `version`, `definition` JSONB, `enabled`, `effective_from` | UNIQUE(`tenant_id`,`key`,`version`). Rules are **data** (Principle V); `definition` holds the rule body |
| 8 | `finding` | 3 | `tenant_id`, `resource_id`, `rule_id`, `rule_version`, `severity`, `status` ENUM(`open`,`resolved`,`suppressed`), `opened_at`, `resolved_at` | UNIQUE(`tenant_id`,`resource_id`,`rule_id`) for open findings; `rule_version` pinned so a finding always traces to the rule version that produced it |
| 9 | `sda` + `resource_owner` | 3 | `sda`: `tenant_id`, `name`, `owner_email`, `team`, `tag_values` JSONB · `resource_owner`: `tenant_id`, `resource_id`, `owner_email`, `evidence` JSONB, `confidence`, `attributed_at` | UNIQUE(`tenant_id`,`name`); one current owner row per resource |
| 10 | `scan` | 2 | `tenant_id`, `cloud_account_id`, `trigger` ENUM(`scheduled`,`manual`), `started_at`, `finished_at`, `status`, `resource_count`, `snapshot_s3_key` | `snapshot_s3_key` points at the immutable raw snapshot |

---

## Relationships

```text
tenant 1──* app_user
tenant 1──* audit_event          app_user 0..1──* audit_event (actor)
tenant 1──* cloud_account
       cloud_account 1──* resource        resource 0..1──* resource (parent)
       cloud_account 1──* scan
tenant 1──* rule
       resource 1──* finding *──1 rule
tenant 1──* sda
       resource 1──1 resource_owner
deployment — standalone, not tenant-scoped (infrastructure record)
```

`deployment` is the one table without a `tenant_id`: it records an act on the platform itself, not
on a tenant's data. Called out explicitly so it does not read as an oversight against FR-030.

The rendered ERD lives at `ops/erd/` and must be updated in the same pull request as any schema
change (FR-028). CI checks that a migration touching `backend/migrations/versions/` is accompanied
by a change under `ops/erd/`.

---

## Migration plan (M2)

| Revision | Contents | Reversible |
|---|---|---|
| `0001_extensions_and_enums` | `pgcrypto`, all ENUM types | Yes |
| `0002_tenant_and_user` | `tenant`, `app_user`, seed the single tenant | Yes |
| `0003_audit_event` | Table, append-only trigger, role grants | **No** — the trigger and revoked grants are the point |
| `0004_deployment` | Table + prod-approval CHECK | Yes |
| `0005_accounts_and_resources` | `cloud_account`, `resource`, GIN index | Yes |
| `0006_rules_and_findings` | `rule`, `finding` | Yes |
| `0007_sda_and_ownership` | `sda`, `resource_owner` | Yes |
| `0008_scan` | `scan` | Yes |

Each revision declares reversibility in its docstring, and CI extracts it (FR-027). `0003` is
deliberately irreversible: a downgrade that restores UPDATE/DELETE grants on the audit table would
undo the control FR-029 exists to provide.

**Verification (FR-026, SC-007)**: integration tests apply `0001`→head against an empty
Testcontainers PostgreSQL and assert the resulting shape matches the committed ERD; then seed
representative rows, apply head again, and assert zero rows lost.
