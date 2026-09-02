# Data Model: Cost, Utilization, and Notifications

Three new tables (`spend_record`, `budget`, `notification`), one new small table
(`iam_hygiene_flag`), and one extended existing table (`finding` — spec 003's, extended
additively per R-508). Utilization (User Story 6) introduces **no new table** — it is computed
live from `resource.state`, already persisted by spec 002 (R-509).

## Cross-cutting conventions (unchanged from specs 1–4)

Every table here is tenant-scoped (`tenant_id` FK, NOT NULL) per spec 1's FR-030. `created_at`/
`updated_at` on every row that already has them (existing tables) or gets them (new tables). No
table introduces a role column — role continues to come from Cognito claims only.

## `finding` — existing table, extended (spec 003's schema, spec 005's additions)

| Column | Type | Constraints | Owner |
|---|---|---|---|
| `id`, `tenant_id`, `severity`, `status`, `opened_at`, `resolved_at`, `acknowledged_at`, `acknowledged_by`, `created_at`, `updated_at` | — | — | spec 003/004's schema, unchanged |
| `resource_id` | UUID | FK → `resource.id`, **now NULLABLE** | was NOT NULL (spec 003) — R-508 |
| `rule_id` | UUID | FK → `rule.id`, **now NULLABLE** | was NOT NULL (spec 003) — R-508 |
| `rule_version` | INTEGER | **now NULLABLE** | was NOT NULL (spec 003) — R-508 |
| `kind` | ENUM `finding_kind` (`tag_violation`, `budget_overrun`) | NOT NULL, default `tag_violation` | **NEW**, spec 005 (R-508) |
| `sda_id` | UUID | FK → `sda.id`, nullable | **NEW**, spec 005 (R-508) — populated only for `kind = 'budget_overrun'` |
| `escalated_at` | TIMESTAMPTZ | nullable | **NEW**, spec 005 (FR-008/FR-009) — set once, the first time a still-open finding's day-4 reminder is sent; cleared (`NULL`) the moment the finding leaves the `open` status by any means |

**New CHECK constraint**, `ck_finding_kind_shape`:

```sql
(kind = 'tag_violation' AND resource_id IS NOT NULL AND rule_id IS NOT NULL
   AND rule_version IS NOT NULL AND sda_id IS NULL)
OR
(kind = 'budget_overrun' AND sda_id IS NOT NULL AND resource_id IS NULL
   AND rule_id IS NULL AND rule_version IS NULL)
```

**New partial unique index**, `uq_finding_open_overrun_per_sda`: `(tenant_id, sda_id) WHERE
status = 'open' AND kind = 'budget_overrun'` — one open overrun finding per project at a time,
the per-project mirror of the existing `uq_finding_open_per_resource_rule` index (unchanged,
still correct: a `budget_overrun` row's `resource_id`/`rule_id` are both `NULL`, which a
Postgres unique index never treats as a match against any other row's `NULL`s or values).

**Existing index `ix_finding_tenant_status_severity`** (unchanged) continues to serve both kinds
— severity is still set on every finding regardless of kind (an overrun finding's severity is a
plan-level default, e.g. always `high`, set by `cost-ingestion-worker` at open time, not
user-configurable in this release).

**API-visible consequence** (`app/api/routers/findings.py`, `contracts/openapi.yaml`): the
`Finding` response model's `resource`/`ruleKey`/`ruleVersion` fields become optional, a new
`kind` field is added, and a new optional `sda` summary field (id, name) is populated exactly
when `kind = 'budget_overrun'` — the same one-or-the-other shape the schema itself now enforces.
`list_findings`'s query changes its `JOIN Resource` to a `LEFT JOIN` (an overrun finding has no
`resource_id` to join against) and adds an equivalent join against `Sda` for the `sda` field.

## `budget` — new table (FR-015, User Story 4)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `sda_id` | UUID | FK → `sda.id`, NOT NULL, UNIQUE per tenant (one budget per project — R-502) |
| `amount_usd` | NUMERIC(12,2) | NOT NULL — the monthly cap both actual and forecast percentages are measured against |
| `actual_80_crossed_at` | TIMESTAMPTZ | nullable |
| `actual_100_crossed_at` | TIMESTAMPTZ | nullable |
| `forecast_80_crossed_at` | TIMESTAMPTZ | nullable |
| `forecast_100_crossed_at` | TIMESTAMPTZ | nullable |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL |

**Unique on** `(tenant_id, sda_id)` — R-502's "one budget per project," created synchronously at
SDA-registration time. The four `*_crossed_at` columns are set the first time each threshold is
crossed within a calendar month and reset to `NULL` at the start of the next month (by
`cost-ingestion-worker`'s own daily run recognizing a new month) — R-507's "only actual-100 opens
a finding" reads `actual_100_crossed_at` transitioning from `NULL` to non-`NULL` as the trigger
condition, not a separate event feed.

**`amount_usd` is set once at creation and is not itself editable by this spec** — FR-015/the
spec's own Assumptions fix the auto-created budget's thresholds (80%/100%) as platform-wide
defaults; the cap amount itself is a plan-level detail (a configured default, e.g. from an
environment variable, or a simple heuristic) belonging to `tasks.md`, not restated as an FR here
since the spec never claims per-project custom caps are in scope this release.

## `spend_record` — new table (FR-001, FR-002, FR-002a, User Story 1)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `cloud_account_id` | UUID | FK → `cloud_account.id`, NOT NULL |
| `sda_id` | UUID | FK → `sda.id`, nullable — "No SDA" bucket, mirrors `resource.sda_id`'s own nullability exactly |
| `service` | VARCHAR(100) | NOT NULL — e.g. `AmazonEC2`, matching Cost Explorer's own service-name strings verbatim, not a platform-normalized enum |
| `spend_date` | DATE | NOT NULL |
| `amount_usd` | NUMERIC(12,4) | nullable — `NULL` exactly when `is_gap = true` (FR-002a); never a guessed or zeroed value for a gap day |
| `is_gap` | BOOLEAN | NOT NULL, default `false` |
| `ingested_at` | TIMESTAMPTZ | NOT NULL, default `now()` — last write time, so a correction (FR edge case) is visible as "this record was updated," not silently indistinguishable from its first ingestion |

**Unique on** `(tenant_id, cloud_account_id, service, spend_date, sda_id)`. `sda_id` is part of
the key (not left out as "attribution metadata only") because Cost Explorer's own tag-group
response can legitimately return more than one spend line for the same account/service/day when
grouped by a tag whose value differs per resource — each becomes its own record, attributed
independently via `sda_matching.find_matching_sda`. A day's correction (edge case) updates the
matching existing row (`ingested_at` bumped, `amount_usd` replaced) rather than inserting a
second row for the same key.

**`is_gap = true` rows** carry `amount_usd = NULL` and are surfaced on the cost dashboard as an
explicit gap (FR-002a) — `cost-ingestion-worker` writes one gap row per (account, service-less,
day) it could not ingest after retries exhaust, distinguishable at read time from "this
account/day genuinely had zero services with spend," which is a normal, non-gap absence of rows.

## `notification` — new table (FR-004–FR-013, User Stories 2/3)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `finding_id` | UUID | FK → `finding.id`, NOT NULL |
| `cadence_point` | ENUM `notification_cadence_point` (`day_0`, `day_2`, `day_4`) | NOT NULL |
| `outcome` | ENUM `notification_outcome` (`sent`, `withheld_no_owner_email`, `withheld_bounced`, `suppressed_finding_closed`) | NOT NULL |
| `recipient_email` | VARCHAR(320) | nullable — populated only when `outcome = 'sent'` |
| `attempted_at` | TIMESTAMPTZ | NOT NULL, default `now()` |

**Unique on** `(tenant_id, finding_id, cadence_point)`. At most one notification attempt per
finding per cadence point, ever — `notification-worker`'s daily query for "what's due today"
excludes any `(finding_id, cadence_point)` pair already present here, which is what makes FR-011
("a reopened finding starts its own independent cadence") correct by construction: a reopened
finding is, per spec 003's own re-open semantics, a **new** `Finding` row (a fresh `id`), so it
naturally has no prior `notification` rows to collide with — no explicit "cycle number" column is
needed. `outcome = 'suppressed_finding_closed'` is written (not simply skipped) so FR-013's
audit trail can distinguish "we checked and correctly didn't send" from "we never checked at
all."

## `iam_hygiene_flag` — new table (FR-019, FR-020, User Story 7)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `cloud_account_id` | UUID | FK → `cloud_account.id`, NOT NULL |
| `principal_type` | ENUM `iam_principal_type` (`role`, `user`, `access_key`) | NOT NULL |
| `principal_identifier` | VARCHAR(2048) | NOT NULL — the role/user ARN, or the access key ID for an `access_key` flag |
| `evidence` | JSONB | NOT NULL — `{"last_used_at": ..., "reason": "no activity in last-used analysis"}`, the same evidence-not-assertion discipline `resource_owner.evidence` already established (spec 003) |
| `flagged_at` | TIMESTAMPTZ | NOT NULL, default `now()` |
| `cleared_at` | TIMESTAMPTZ | nullable — set when a later weekly run no longer finds this principal unused (it started being used again, or was deleted) |

**Unique, partial index on** `(tenant_id, cloud_account_id, principal_identifier) WHERE cleared_at
IS NULL` — one active flag per principal at a time, re-flagged with a fresh `flagged_at` if it
clears and later becomes unused again, rather than silently reusing a stale row. **Deliberately
not a `Finding`** (no `kind` value here) — the spec's own FR-019 fixes this as "flag-only," never
entering the acknowledge/notify/escalate pipeline; a stricter, narrower guarantee than any
`Finding` row carries, and mixing the two would blur that line.

## Utilization — no new table (User Story 6, FR-018, R-509)

Computed live, per account or per project, as:

```sql
SELECT
  COUNT(*) FILTER (WHERE state IN ('running','available','ACTIVE','active', ...known-active...))
    AS used,
  COUNT(*) AS provisioned  -- WHERE state IS NOT NULL, scoping both counts identically
FROM resource
WHERE cloud_account_id = :account_id AND deleted_at IS NULL AND state IS NOT NULL
  [AND sda_id = :sda_id]  -- project-level drill-down
```

The known-idle/known-active state-string sets live in `app/governance/utilization.py` as a
plain Python `dict`/`set` (data, not an `if/elif` chain — matching `coverage_definitions.json`'s
existing data-driven precedent), not a new table — there is exactly one platform-wide
classification, not a per-tenant configurable one, and the spec names no requirement for the
latter.
