# Data Model: Tag Compliance and Ownership

Spec 1 already created `rule`, `finding`, `sda`, and `resource_owner` with their full shape
(migration 0006/0007-class work) and their enum types (`finding_severity`, `finding_status`,
`owner_confidence`) up front — this spec adds zero new columns to any of the four. This document
covers what already exists, the one behavioral use this spec makes of an existing-but-unpopulated
column on `resource`, and the two small P2-only additions.

## Cross-cutting conventions (unchanged from specs 1–2)

Every table here is tenant-scoped (`tenant_id` FK, NOT NULL) per spec 1's FR-030. `created_at`/
`updated_at` on every row that already has them. No table in this spec introduces a role column —
role continues to come from Cognito claims only (spec 1 FR-031a), unchanged.

## `rule` — existing table, no schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `key`, `enabled`, `effective_from`, `created_at`, `updated_at` | — | — | spec 1's schema |
| `version` | INTEGER | NOT NULL, default 1 | spec 1's schema — **this spec increments it on every edit** (FR-006) |
| `definition` | JSONB | NOT NULL | spec 1's schema — **this spec gives it structure**: `{"required": bool, "allowed_values": [str] \| null, "format_pattern": str \| null, "severity": "low"\|"medium"\|"high"\|"critical"}` (FR-004; severity default `medium` per spec.md's Assumptions) |

**Unique on** `(tenant_id, key, version)` — already spec 1's constraint. This is exactly what makes
"a rule's key is its stable identity, each edit a new version" (Clarifications session 2026-08-25)
a schema fact, not just a convention this spec promises to follow: there is no way to construct two
rows sharing a key and version, and no way for a `key` to *not* have a stable identity across its
versions, since the key itself never changes row-to-row.

**Seed data** (FR-003): four rows at `version=1`, `enabled=true`, `required=true` — keys
`project_name`, `owner`, `project_id`, `created_by` — plus one row for `environment` at
`required=false`. Delivered as a migration-time data seed (an `INSERT` in the same migration that
first creates demo/seed data, matching spec 1's own tenant-seeding precedent), not application
code — consistent with FR-001's "rules are data the platform reads," seeding included.

## `finding` — existing table, no schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `resource_id`, `rule_version`, `opened_at`, `resolved_at`, `created_at`, `updated_at` | — | — | spec 1's schema |
| `rule_id` | UUID | FK → `rule.id`, NOT NULL | spec 1's schema — **this spec re-points it** (research.md R-301) on re-evaluation, rather than treating it as immutable once set |
| `severity` | ENUM `finding_severity` | NOT NULL | spec 1's schema — **this spec sets it** from `rule.definition.severity` at the moment a finding opens or is re-evaluated |
| `status` | ENUM `finding_status` (`open`, `resolved`, `suppressed` — spec 1's existing members) | NOT NULL, default `open` | spec 1's schema — this spec's auto-close (FR-016) is the only mechanism that ever sets `resolved`; nothing in this spec's P1 or P2 scope uses `suppressed` (no requirement calls for dismissing a finding without fixing it) — reserved for a later spec, unused here |

**Unique, partial index on** `(tenant_id, resource_id, rule_id)` **where** `status = 'open'` —
already spec 1's constraint (FR-015's dedup guarantee). Because R-301 re-points `rule_id` to the
*current* version on re-evaluation rather than leaving it pinned, this existing index continues to
mean exactly what its name says at any point in time — no query needs to reason about historical
`rule_id` values, only the current one.

**How an evaluation cycle actually reads/writes this table** (behavioral, not schema): for one
resource and one enabled rule (identified by `key`), the validation engine looks up an open finding
via `JOIN rule ON finding.rule_id = rule.id WHERE rule.key = :key AND finding.resource_id = :rid
AND finding.status = 'open'` — not `WHERE finding.rule_id = :specific_row_id`. If found and the
violation still holds, `rule_id`/`rule_version`/`severity` are updated to the current version's
values (no-op if nothing changed) and no new row is created (FR-015). If found and the violation no
longer holds, `status` becomes `resolved` and `resolved_at` is set (FR-016). If not found and the
violation holds, a new row is created.

## `sda` — existing table, no schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `name`, `owner_email`, `team`, `created_at`, `updated_at` | — | — | spec 1's schema |
| `tag_values` | JSONB | NOT NULL, default `{}` | spec 1's schema — **this spec gives it structure**: `{tagKey: requiredValue, ...}`, an implicit AND across every key present — a resource matches when every key in the mapping is present on the resource with exactly that value (FR-008) |

**Unique on** `(tenant_id, name)` — already spec 1's constraint (prevents duplicate SDA names; a
separate, application-level check enforces the *mapping*-overlap rule research.md R-305 defines,
since overlap is a property of two mappings' contents, not expressible as a SQL uniqueness
constraint on JSONB).

**"No SDA" is not a row.** A resource with no matching SDA has no `sda_id` set on its own record
(see the `resource` section below) rather than being linked to a synthetic "unassigned" `Sda` row —
simpler, and it means SC-006's "visible in the No SDA bucket" is just a `WHERE sda_id IS NULL`
query, not a lookup against a magic-value row that would need protecting from accidental deletion
or renaming.

**Removing an `sda` row is unrestricted** (FR-010b) — no check against resources currently
referencing it, unlike FR-010a's overlap check on create/edit. This is a deliberate asymmetry: an
overlapping mapping would silently corrupt future classification if allowed, which is worth
refusing; a resource losing its SDA on removal is neither silent nor corrupting — it lands exactly
in the "No SDA" bucket FR-009 already makes visible, the same well-defined state a never-matched
resource is in. The FK's `ON DELETE SET NULL` (see `resource.sda_id` below) is what makes "removal
is always allowed, and always safe" true at the database level, not just a policy this spec asserts.

## `resource_owner` — existing table, no schema change

| Column | Type | Constraints | Already defined by |
|---|---|---|---|
| `id`, `tenant_id`, `resource_id`, `attributed_at`, `created_at`, `updated_at` | — | — | spec 1's schema |
| `owner_email` | VARCHAR(320), nullable | spec 1's schema — **null while queued unattributed** (FR-022/FR-026), populated once identity resolution (FR-027) succeeds |
| `confidence` | ENUM `owner_confidence` (`high`, `medium`, `low` — spec 1's existing members) | NOT NULL | spec 1's schema — **this spec's mapping**: `high` = direct creator attribution (FR-021), `medium`/`low` = fallback attribution (FR-025, exact level left to `/speckit-tasks` sizing — the spec only requires it be *lower* than direct attribution, not a specific one of the two) |
| `evidence` | JSONB | NOT NULL, default `{}` | spec 1's schema — **this spec's shape**: `{"kind": "direct"\|"fallback", "cloudtrail_event_id": str, "principal": str, "event_time": timestamp, ...}` — enough for FR-021/FR-025's "with evidence" requirement to mean something concrete and inspectable, not an opaque blob |

**Unique on** `(tenant_id, resource_id)` — already spec 1's constraint: one owner record per
resource, matching FR-023 ("an existing attribution MUST NOT be silently overwritten by a
later, lower-confidence result") directly — the write path is an `UPDATE ... WHERE confidence <=
:new_confidence`-style guarded update, never a blind upsert, so a lower-confidence result on a later
scan simply doesn't touch an existing higher-confidence row.

## `resource` — existing table (spec 002), one column this spec starts populating

| Column | Type | Constraints | Status |
|---|---|---|---|
| `parent_resource_id` | UUID, nullable | FK → `resource.id` (`ON DELETE SET NULL`) | **Already exists** (spec 1's original schema, migration 0005) — reserved but never populated by spec 002. **This spec is the first to populate it** (FR-013a), during validation: a resource whose enrichment `detail` identifies an owning resource (for example, an EBS volume's `attached_instance_id`, an Elastic IP's `associated_instance_id` — both already captured by spec 002's P1 enrichment) has `parent_resource_id` set to that owning resource's row; everything else keeps it `NULL`. |
| `sda_id` | UUID, nullable | FK → `sda.id` (`ON DELETE SET NULL`) | **NEW** — additive migration `0010_resource_sda_and_tenant_identity_pattern` (bundled with the two P2 additions below since they're small enough to ship in one migration file, per spec 002's own precedent of bundling several small additive changes into migration 0009). `NULL` = "No SDA" bucket (FR-009). Set at scan time by the SDA-matching step (FR-008), re-evaluated on every scan so a newly-registered or edited SDA reclassifies matching resources by the next scan (FR-010). **`ON DELETE SET NULL` is not just a technically-safe default — it is FR-010b's actual mechanism**: removing an SDA row is what immediately reverts every resource that referenced it to `NULL` ("No SDA"), with no application code needed to do the reverting and no wait for the next scan, since the database enforces it the instant the row is deleted. |

**Why `parent_resource_id` needs no migration but `sda_id` does**: the former already exists,
unused; the latter is a genuinely new relationship spec 002 never anticipated on `resource` (its own
data-model.md lists `sda_id` nowhere). Both changes are additive — nullable, no rewrite of existing
rows, no data loss risk.

**"Top-level resource" (FR-013), concretely**: `resource.parent_resource_id IS NULL`. Validation,
scoring, and the "total top-level resources" denominator (FR-018) all filter on this condition —
one canonical definition, queried the same way everywhere, matching FR-013a's own requirement that
"top-level resource" not be re-derived differently by every caller.

## P2-only additions

### `owner_identity_override` — NEW table (S23a, FR-027)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | FK → `tenant.id`, NOT NULL |
| `principal_id` | VARCHAR(2048) | NOT NULL — the raw audit-trail identity string (an IAM ARN or equivalent), not a reference to any platform table (research.md R-304) |
| `owner_email` | VARCHAR(320) | NOT NULL |
| `created_at`, `updated_at` | TIMESTAMPTZ | NOT NULL |

Unique on `(tenant_id, principal_id)` — one override per identity per tenant. Consulted last in
FR-027's resolution chain, after the owner tag and the configured pattern both fail to produce a
usable email.

### `tenant.owner_identity_pattern` — NEW column (S23a, FR-028)

| Column | Type | Constraints |
|---|---|---|
| `owner_identity_pattern` | VARCHAR(500), nullable | Admin-editable template string (for example, `{principal_local_part}@example.com`), applied to the audit-trail identity when the owner tag isn't a usable email and no override row exists for that identity. `NULL` means the pattern step is skipped, falling straight through to the override table (and, if that also misses, the resource stays unattributed rather than an empty pattern producing a garbage email). |

Both P2 additions ship in one migration file since neither is large enough to warrant its own PR
per spec 002's own "bundle small additive changes" precedent (its migration 0009 bundled three
unrelated-but-small `resource` columns the same way).

## Ownership attribution's working data — not persisted, an in-flight correlation concept

R-302's bulk CloudTrail sweep produces an in-memory map from resource identifier to
`{principal, event_name, event_time, is_write}` for the scan's 90-day window — this is not a new
database table. It exists only for the duration of the ownership-attribution worker's invocation,
consumed to produce `resource_owner` rows (or leave a resource queued unattributed, which is simply
the *absence* of a `resource_owner` row for that resource — no separate "unattributed" status or
table is needed, matching how spec 002's own `resource.deleted_at IS NULL` pattern uses absence of
a marker rather than an explicit "not deleted" enum value).
