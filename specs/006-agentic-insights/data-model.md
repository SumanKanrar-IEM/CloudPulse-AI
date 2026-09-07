# Data Model — Agentic Insights (spec 006)

New tables only. Every table is tenant-scoped and inherits `TenantScoped`, the same as every
table specs 001–005 added. No existing table's shape changes except where noted under
**Reused, unchanged**.

## `agent_run` — one execution of one agent capability

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `capability` | ENUM `agent_capability` (`digest`, `suggester`, `advisor`, `narrator`) | NOT NULL |
| `definition_hash` | VARCHAR(64) | NOT NULL — content hash of the prompt/definition that ran (R-608, FR-005) |
| `status` | ENUM `agent_run_status` (`succeeded`, `truncated`, `failed`) | NOT NULL |
| `cost_units` | NUMERIC(12,4) | NOT NULL — what the run consumed against its cap |
| `cost_cap_units` | NUMERIC(12,4) | NOT NULL — the cap in force for this run |
| `failure_reason` | TEXT | nullable — populated exactly when `status = 'failed'` |
| `started_at` | TIMESTAMPTZ | NOT NULL |
| `finished_at` | TIMESTAMPTZ | nullable — NULL while in flight |

`truncated` is a first-class status, not a failure: FR-004 requires a run reaching its cap to stop
and say so. Recording `cost_cap_units` alongside `cost_units` means a later reader can tell "hit
the cap" from "the cap was lowered" without consulting configuration history.

**Retention**: 30 days (FR-006a).

## `insight_digest` — one daily summary per tenant

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `agent_run_id` | UUID | FK → `agent_run.id`, NOT NULL |
| `period_date` | DATE | NOT NULL — the day summarised |
| `content` | JSONB | NOT NULL — structured sections, not rendered markup (R-610) |
| `is_empty` | BOOLEAN | NOT NULL — true when there was nothing notable (FR-010) |
| `created_at` | TIMESTAMPTZ | NOT NULL |

**Unique on** `(tenant_id, period_date)`. One digest per tenant per day; a re-run replaces rather
than appends, which is what stops two overlapping runs producing a duplicate (Edge Cases).

`is_empty` is stored rather than derived from empty content, so "the agent found nothing notable"
and "the agent produced nothing" stay distinguishable.

**Retention**: 30 days (FR-006a). A digest ages out with its run — the dashboard then shows the
"not enough data yet" state rather than a digest whose provenance was deleted.

## `grounding_rejection` — an output refused before display

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `agent_run_id` | UUID | FK → `agent_run.id`, NOT NULL |
| `rejected_reference` | TEXT | NOT NULL — the identifier or figure that could not be validated |
| `reference_kind` | ENUM `grounding_reference_kind` (`arn`, `resource_id`, `finding_id`, `sda`, `figure`) | NOT NULL |
| `rejected_at` | TIMESTAMPTZ | NOT NULL |

The rejected output itself is deliberately **not** stored. It is unvalidated model text; keeping
it creates a place where fabricated ARNs live inside the platform, which is the exact thing FR-001
exists to prevent. The reference that failed is enough to diagnose.

**Retention**: 30 days (FR-006a).

## `coverage_proposal` — a proposed configuration extension (P2)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `agent_run_id` | UUID | FK → `agent_run.id`, NOT NULL |
| `proposal_kind` | ENUM `coverage_proposal_kind` (`rule_extension`, `enable_existing_enricher`) | NOT NULL |
| `resource_type` | VARCHAR(200) | NOT NULL — the type whose gap was detected |
| `evidence_account_id` | UUID | FK → `cloud_account.id`, NOT NULL — which account revealed it |
| `proposed_change` | JSONB | NOT NULL — the configuration to apply |
| `review_state` | ENUM `proposal_review_state` (`pending`, `accepted`, `rejected`) | NOT NULL, default `pending` |
| `decided_by` | UUID | FK → `app_user.id`, nullable — NULL exactly while `pending` |
| `decided_at` | TIMESTAMPTZ | nullable — NULL exactly while `pending` |
| `applied_at` | TIMESTAMPTZ | nullable — set when a scan first applied it |

**Unique on** `(tenant_id, resource_type, proposal_kind) WHERE review_state = 'pending'` — a
partial index, so the advisor cannot raise the same pending proposal twice while keeping every
decided one as history. Same shape as `iam_hygiene_flag`'s active-flag index (spec 005).

**`proposal_kind` has exactly two values, deliberately.** R-603: a resource type with no existing
enricher cannot be proposed at all, because accepting it could not take effect without a code
change — FR-017 would be unsatisfiable. Those gaps surface as read-only advisory content, never
as an acceptable row.

`evidence_account_id` is evidence, not scope: acceptance applies tenant-wide (Clarifications,
2026-09-05).

**Retention**: not expired. A proposal is a governance decision record, not an operational one —
the same reason a finding's suggestion is excluded from FR-006a.

## `resource_metric` — one utilization measurement (P2)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `resource_id` | UUID | FK → `resource.id`, NOT NULL |
| `metric` | ENUM `resource_metric_kind` (`cpu`, `memory`, `network`, `storage`) | NOT NULL |
| `period_start` | TIMESTAMPTZ | NOT NULL |
| `value` | NUMERIC(12,4) | nullable — **NULL exactly when `is_unavailable`** |
| `is_unavailable` | BOOLEAN | NOT NULL, default false — FR-020: unknown, never zero |
| `collected_at` | TIMESTAMPTZ | NOT NULL |

**Unique on** `(tenant_id, resource_id, metric, period_start)` — FR-019's no-duplicate rule
enforced at the database, so a re-run updates rather than appends.

The `value`/`is_unavailable` pairing is the same discipline `spend_record.amount_usd`/`is_gap`
already uses (spec 005): a missing measurement is recorded as missing, never as a zero that would
drag an average down and understate utilization.

**Retention**: 30 days (FR-006a), which also bounds the forecast window.

## `forecast` — a projected figure (P2)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `sda_id` | UUID | FK → `sda.id`, NOT NULL |
| `kind` | ENUM `forecast_kind` (`spend`, `capacity`) | NOT NULL |
| `period_start` / `period_end` | DATE | NOT NULL |
| `projected_value` | NUMERIC(14,4) | NOT NULL |
| `history_days` | INTEGER | NOT NULL — how much history it was derived from |
| `actual_value` | NUMERIC(14,4) | nullable — filled once the period closes |
| `absolute_percentage_error` | NUMERIC(6,3) | nullable — computed when `actual_value` lands |

No `agent_run_id`: forecasts are produced by deterministic calculation, not by an agent
(Clarifications, 2026-09-05; FR-021). The agent narrates them and the narrative is a separate
concern. Storing `history_days` is what makes FR-021's "not enough data" state auditable rather
than a runtime-only decision.

## `rightsizing_recommendation` — a proposed instance class (P2)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK, NOT NULL |
| `resource_id` | UUID | FK → `resource.id`, NOT NULL |
| `current_class` / `recommended_class` | VARCHAR(100) | NOT NULL |
| `evidence` | JSONB | NOT NULL — the measurements justifying it |
| `estimated_monthly_saving_usd` | NUMERIC(12,2) | NOT NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |

**Unique on** `(tenant_id, resource_id) WHERE superseded_at IS NULL`, with `superseded_at`
TIMESTAMPTZ nullable — one live recommendation per resource, earlier ones kept as history.
`evidence` is NOT NULL because FR-023 requires it: a recommendation to downsize something,
without the measurements behind it, is a guess presented as a fact.

## Reused, unchanged

* **`finding_remediation_suggestion`** (spec 003, rendered by spec 004) — this spec finally writes
  `source = 'ai_generated'`, the value spec 003 defined and nothing has ever produced. **No shape
  change.** FR-013's "must not overwrite an admin-seeded suggestion" is enforced on write.
* **`rule`** (spec 003) — an accepted `rule_extension` proposal writes a new rule version through
  spec 003's existing versioning. No shape change.
* **`app/scan/coverage_definitions.json`** (spec 002) — an accepted `enable_existing_enricher`
  proposal adds an entry mapping a type to an **already-existing** enricher. See R-603.

## Enum additions

`agent_capability`, `agent_run_status`, `grounding_reference_kind`, `coverage_proposal_kind`,
`proposal_review_state`, `resource_metric_kind`, `forecast_kind`. All created by this spec's
migration; none extends an existing type. Migration 0014 (spec 005) is the parent.

Adding a value to a native Postgres enum later is additive; **removing** one requires the
rename-create-recast-drop dance migration 0014 had to perform. Every enum above is therefore
defined with only the values something can actually write today — the lesson T017a/T017b recorded
when `withheld_bounced` shipped with no writer.
