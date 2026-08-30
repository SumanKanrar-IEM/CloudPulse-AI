# Data Model: Governance Dashboard

This spec adds two small, additive pieces — acknowledgment metadata on `finding`, and one new
table, `finding_remediation_suggestion` — and reads everything else it needs from tables specs
001–003 already built and populated: `cloud_account`, `resource`, `resource_owner`, `sda`,
`scan`. No existing table's meaning changes; this spec only exposes more of what already exists
through new API surface (`GET /resources`, primarily — research.md's own Summary confirms no
general resource-listing endpoint existed before this spec).

## Cross-cutting conventions (unchanged from specs 1–3)

Every table here is tenant-scoped (`tenant_id` FK, NOT NULL) per spec 1's FR-030. `created_at`/
`updated_at` on every row that already has them. No table in this spec introduces a role column —
role continues to come from Cognito claims only (spec 1 FR-031a), unchanged.

## `finding` — two new nullable columns, no other schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `resource_id`, `rule_id`, `rule_version`, `severity`, `status`, `opened_at`, `resolved_at`, `created_at`, `updated_at` | — | — | spec 1/3's schema, unchanged |
| `acknowledged_at` | TIMESTAMPTZ | nullable | **new (FR-016)** — set the first time an admin or operator acknowledges the finding; parallel in shape to the existing `resolved_at`, but orthogonal to it — a finding can be acknowledged while still `status = 'open'`, and acknowledging never sets `resolved_at` or changes `status` (FR-017; research.md R-404) |
| `acknowledged_by` | UUID | FK → `app_user.id`, `ON DELETE SET NULL`, nullable | **new (FR-016)** — who acknowledged it; `SET NULL` rather than `RESTRICT` since losing the identity of an old acknowledgment is acceptable, losing the fact that one happened is not |

**Behavioral note**: acknowledging a finding is an `UPDATE ... SET acknowledged_at = now(),
acknowledged_by = :user WHERE id = :finding_id AND acknowledged_at IS NULL` — the `WHERE
acknowledged_at IS NULL` guard is what makes a near-simultaneous second acknowledgment attempt
(FR-020) a no-op rather than an error or a second write: the first writer's `UPDATE` matches one
row and succeeds; a second, near-simultaneous attempt matches zero rows (the guard clause no
longer holds) and succeeds trivially with no row affected, rather than raising a constraint
violation — no unique index needed for this guarantee, the guard clause alone provides it.

## `finding_remediation_suggestion` — new table

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK → `tenant.id`, NOT NULL |
| `finding_id` | UUID | FK → `finding.id`, `ON DELETE CASCADE`, NOT NULL, **UNIQUE** |
| `suggestion_text` | TEXT | NOT NULL |
| `blast_radius_note` | TEXT | NOT NULL |
| `source` | ENUM `suggestion_source` (`ai_generated`, `admin_seeded`) | NOT NULL |
| `created_at`, `updated_at` | TIMESTAMPTZ | NOT NULL |

**Unique on `finding_id`**: one suggestion per finding, matching FR-018's singular "a platform-
generated remediation suggestion" — this spec has no requirement for a history of superseded
suggestions, so the simplest shape (an upsert target, not an append-only log) is what FR-018/
FR-020a actually need. If a later spec regenerates a suggestion, that is an `UPDATE`, not a new
row — data-model.md deliberately leaves this open rather than over-specifying a versioning scheme
this spec's own requirements don't call for.

**`source` distinguishes FR-018's real path from FR-020a's demo/QA path** — never at the
database level a difference of *content*, only of *provenance*, so the display path (FR-018) can
render both identically while a small "test data" badge (FR-020a's own visible-marking requirement)
reads directly off this column rather than inferring provenance some other way. `ai_generated` is
reserved for the AI-insights capability (a later spec) to write; this spec's own `POST
/findings/{findingId}/suggestion` endpoint (FR-020a, admin-only) always writes `admin_seeded` —
it has no path to writing `ai_generated`, so the two provenances can never be confused at the
write layer, not merely trusted to stay accurate at the display layer.

## `resource` — no schema change; this spec is the first to expose it broadly

| Column | Type | Already defined by |
|---|---|---|
| `id`, `tenant_id`, `cloud_account_id`, `arn`, `resource_type`, `service`, `region`, `tags`, `sda_id`, `parent_resource_id`, `first_seen_at`, `last_seen_at`, `state`, `deleted_at`, `detail` | — | specs 002/003's schema, unchanged |

**How `GET /resources` filters (FR-010, behavioral, not schema)**: `account`/`service`/`region`/
`sda` filter directly on their matching columns. `tagStatus` filters via a `LEFT JOIN` to
`finding` (an open finding against any enabled rule ⇒ non-compliant; no open finding ⇒
compliant — the same "top-level, zero open findings" definition tag compliance and ownership's
own compliance-scoring formula already uses, reused here rather than re-derived). `ownerStatus=
unattributed` filters via a `LEFT JOIN ... WHERE resource_owner.id IS NULL` — deliberately a
separate filter from `tagStatus`, not a value of it (research.md R-403). `parent_resource_id IS
NOT NULL` rows (children) are included in listings by default — unlike compliance scoring and
validation, which are top-level-only by FR-013/FR-018's own explicit scoping, nothing in this
spec's inventory-explorer requirements restricts the *browsable* inventory to parents only; a
child resource remains findable and its own detail panel remains meaningful (it still has tags,
enrichment, and potentially its own owner).

**Deleted resources** (`deleted_at IS NOT NULL`): excluded from `GET /resources`'s default
listing (a "gone" resource has no governance action to take), but a soft-deleted resource's
`GET /resources/{resourceId}` detail view remains reachable directly by ID (for example, from an
older finding or scan-history reference still citing it) — showing its last-known state rather
than a 404, consistent with account onboarding and discovery's own "soft marker, never a row
deletion" precedent for `deleted_at`.

## `resource_owner` — no schema change

| Column | Type | Already defined by |
|---|---|---|
| `id`, `tenant_id`, `resource_id`, `owner_email`, `confidence`, `evidence`, `created_at`, `updated_at` | — | spec 003's schema, unchanged |

Read directly by `GET /resources/{resourceId}` (FR-012's "owner + evidence") and by
`GET /resources`'s `ownerStatus=unattributed` filter (research.md R-403) — no new column, no new
query pattern beyond what tag compliance and ownership's own `GET /resources/{resourceId}/owner`
endpoint already proves works.

## `scan` — no schema change; deltas computed at query time (research.md R-405)

| Column | Type | Already defined by |
|---|---|---|
| `id`, `tenant_id`, `cloud_account_id`, `trigger`, `status`, `resource_count`, `started_at`, `finished_at` | — | spec 002's schema, unchanged |

`GET /accounts/{accountId}/scans`'s response gains three response-model-only fields (`added`/
`removed`/`changed`, FR-021) computed from `resource.first_seen_at`/`last_seen_at`/`deleted_at`
against `[scan.started_at, scan.finished_at]` — no new column on this table, per R-405.

## Seed data

None. Unlike specs 002/003, this spec introduces no new rule, no new tenant-wide default, no
row that must exist before the platform is useful — every new table is populated only by user
action (an acknowledgment, a seeded suggestion), never by a migration-time `INSERT`.
