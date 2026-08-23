# Data Model: Account Onboarding and Discovery

Spec 1 already created `cloud_account`, `resource`, and `scan` empty (migrations 0005, 0008), with
their enum types defined up front in 0001 — including `disabled` on `account_status` and `partial`
on `scan_status`, both of which this spec needs and neither of which needs a new migration to add.
This document covers what already exists, what this spec adds, and why the addition is smaller
than a first read of the spec's Key Entities section might suggest.

## Cross-cutting conventions (unchanged from spec 1)

Every table here is tenant-scoped (`tenant_id` FK, NOT NULL) per spec 1's FR-030. `created_at`/
`updated_at` on every row. No table in this spec introduces a role column — role continues to come
from Cognito claims only (spec 1 FR-031a), unchanged.

## `cloud_account` — existing table, no schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `aws_account_id`, `alias`, `created_at`, `updated_at` | — | — | migration 0005 |
| `connection_mode` | ENUM `connection_mode` (`local`, `assume_role`) | NOT NULL | migration 0005 |
| `role_arn` | VARCHAR(2048) | NULL; required when `connection_mode='assume_role'` (existing CHECK) | migration 0005 |
| `external_id_ref` | VARCHAR(2048) | NULL | migration 0005 — **this spec populates it**: a Secrets Manager ARN holding the platform-generated ExternalId (FR-003a), never a plaintext value (Principle III) |
| `scan_regions` | TEXT[] | NOT NULL, default `{}` | migration 0005 — FR-006/FR-008 |
| `status` | ENUM `account_status` (`pending`, `verified`, `failed`, `disabled`) | NOT NULL, default `pending` | migration 0005 — **this spec uses `disabled` for FR-009a's deactivation** |

**Why `disabled` needs no new migration**: spec 1's enum already anticipated this exact need. This
spec's behavioral contribution is entirely in how the four values transition, not in adding a
fifth:

```text
        register (FR-006/FR-007)
              │
              ▼
          pending ──verify succeeds──▶ verified ◀──reactivate (FR-009c)──┐
              │                            │                             │
       verify fails                  role goes bad                  deactivate
              │                     (US1 scenario 6)                 (FR-009a)
              ▼                            │                             │
           failed ◀───────────────────────┘                             │
                                                                          │
                                        disabled ◀────────────────────────┘
```

**Validation additions this spec makes** (behavioral, not schema): registering (FR-006/FR-007) is
the only path into `pending`; only a successful or failed verification attempt (US1 scenarios 1–2
vs 5) moves it to `verified`/`failed`; only deactivation (FR-009a) moves *any* state to `disabled`;
only reactivation (FR-009c) moves `disabled` back to `verified` — optimistically, not
re-verified — and the very next scan attempt corrects it to `failed` if the underlying role has
actually gone stale in the meantime (Edge Cases: "a reactivated account whose role was deleted or
changed while it was deactivated"), exactly the same mechanism that already handles a role going
bad on an active, never-deactivated account (US1 scenario 6). No new state-detection code path —
one mechanism covers both cases.

## `resource` — existing table, additive migration `0009_resource_lifecycle_and_detail`

| Column | Type | Constraints | Status |
|---|---|---|---|
| `id`, `tenant_id`, `cloud_account_id`, `arn`, `resource_type`, `service`, `region`, `tags`, `parent_resource_id`, `first_seen_at`, `last_seen_at`, `created_at`, `updated_at` | — | — | Existing (migration 0005) |
| `state` | VARCHAR(100) | NULL | **NEW** — FR-013's normalized "current state" field. Free-text, service-reported (e.g. `running`, `available`, `terminated`) rather than a cross-service enum, because AWS resource states genuinely don't share a common vocabulary — normalizing further would lose information FR-019's enrichment scenarios need. |
| `deleted_at` | TIMESTAMPTZ | NULL | **NEW** — FR-030's deleted marker. `NULL` = currently present; non-null = the timestamp of the scan that first failed to find it. A soft marker, never a row deletion, matching FR-030's explicit "marked deleted rather than removed from the record." |
| `detail` | JSONB | NOT NULL, default `{}` | **NEW** — FR-013's "service-specific detail payload." Holds FR-019's enrichment output (instance type, volume size, attachment state, etc.) per resource type; deliberately schemaless at the SQL level since it varies per `resource_type` by design — `coverage.py` (research.md R-202) is what gives it structure at the application layer. |

**Why `arn` remains the identity column, unchanged**: FR-015 requires a unique identifier stable
for the life of the underlying resource. AWS ARNs already satisfy this for every resource type this
spec's P1 scope touches (EC2, EBS, EIP, S3, RDS, Lambda) — the existing
`UNIQUE(tenant_id, arn)` constraint from migration 0005 is exactly FR-015's requirement, already
built. Edge Cases' "resource that changes identity-relevant fields between scans" (e.g. a
delete-then-recreate masquerading as a move) is handled by that same uniqueness constraint doing
its job: a genuinely new ARN is a genuinely new row, first-seen from that point — which is the
*correct* behavior FR-015 asks for, not a bug to work around.

**Migration is additive-only** (constitution Principle I / spec 1's FR-048a-style discipline
applied to schema, not just the API contract): three nullable/defaulted columns, no rewrite of
existing rows, no data migration needed since the table is currently empty.

## `scan` — existing table, no schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `cloud_account_id`, `trigger`, `resource_count`, `snapshot_s3_key`, `started_at`, `finished_at`, `created_at`, `updated_at` | — | — | migration 0008 |
| `status` | ENUM `scan_status` (`running`, `succeeded`, `partial`, `failed`) | NOT NULL | migration 0008 — **`partial` (research.md R-204) needs no new migration; it was already there** |
| `trigger` | ENUM `scan_trigger` (`scheduled`, `manual`) | NOT NULL | migration 0008 — FR-026's two trigger kinds map directly onto this existing enum |

**Diffing rule this spec implements** (behavioral): FR-030's deleted-marker sweep runs against a
scan whose `status` is `succeeded` or `partial`, scoped to the units of work (research.md R-201/
R-204) that actually completed for a `partial` scan — never against `failed`. This is the concrete
implementation of R-204's decision; no schema change carries it, the scan-completion code path
does.

## Unit of work — not a persisted entity, an in-flight orchestration concept

FR-023 requires independent units of work (one per account × region × service group) each able to
succeed/fail/retry without requiring every other unit to re-run. This spec does **not** add a
database table for units of work — Step Functions' own Map-state execution history already is that
record for the duration of a running scan (research.md R-203's reasoning for choosing Standard
over Express: its per-state history is exactly this). Only the *aggregate* outcome (how many units
succeeded/failed, feeding `scan.status`) is persisted, via `scan.resource_count` and `status` —
adding a second, redundant per-unit table would duplicate what Step Functions Standard already
retains and exposes via `DescribeExecution`, with no FR requiring that duplication.

## Connector interface — `backend/connectors/base.py` (FR-014)

Not a database entity — the typed contract spec 1's FR-054 reserved the package for. Shape (Python
protocol, illustrative — exact typing is an implementation detail for `/speckit-tasks` to size, not
a spec/plan-level decision):

- `NormalizedResource`: the FR-013 shape — `provider`, `account_id`, `resource_id` (provider-native
  unique id, mapped to `resource.arn` for AWS), `service`, `resource_type`, `region`, `name`,
  `tags`, `state`, `created_at`, `detail` — a 1:1 mapping onto the `resource` table's columns, so
  the persistence layer never needs a provider-specific translation step.
- `Connector` protocol: `discover(account, region) -> Iterable[NormalizedResource]` (R-201's
  combined sweep) and `enrich(resource) -> NormalizedResource` (R-202's targeted describes,
  returning the same resource with `detail` populated). `backend/connectors/aws.py` is the only
  implementation this spec ships; a second provider means a second file implementing the same
  protocol, touching no code that consumes `NormalizedResource` (Principle V's own test).

## Coverage Definition — versioned repository data, not a table (research.md R-203)

Not a database entity. Lives as versioned JSON in the repository (research.md R-203's decision),
loaded at scan-orchestration time by `backend/app/scan/coverage.py`. Shape: a mapping from
`resource_type` to the enrichment function that applies to it, plus which fields that function
populates in `resource.detail` — data an operator (in the generic sense: whoever maintains the
repository, not a specific CloudPulse role) or spec 6's future coverage advisor extends via a PR,
never via a runtime API this spec does not build.
