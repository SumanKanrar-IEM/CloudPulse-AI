# Entity-Relationship Diagram (FR-028)

`schema.mmd` is the committed ERD for the governance record. **It must be updated in
the same pull request as any schema change** — the `erd-current` job in CI fails a PR
that touches `backend/migrations/versions/` without touching this directory.

## Ownership

This spec (001) owns the *shape* of every table. The behaviour that fills them belongs
to specs 002–006, which extend the schema by additive migration:

| Table | Filled by |
|---|---|
| `tenant`, `app_user`, `audit_event`, `deployment` | **spec 001** |
| `cloud_account`, `resource`, `scan` | spec 002 |
| `rule`, `finding`, `sda`, `resource_owner` | spec 003 |
| `spend_record`, `budget`, `notification`, `iam_hygiene_flag` | spec 005 |

## Two things that look like mistakes and are not

**`deployment` has no `tenant_id`.** It records an act on the platform itself, not on a
tenant's data — the one deliberate exception to FR-030. Every other table is
tenant-scoped.

**`app_user` has no `role` column.** FR-031a makes the identity provider the sole
authority for a person's role; it is derived from the directory group claim on every
request. A column here would be a second, drifting source of truth and a
privilege-escalation surface. Adding one is a constitution violation, and
`test_tenant_scoping.py::test_app_user_has_no_role_column` fails if anyone tries.

## Rendering

The diagram is Mermaid. GitHub renders `.mmd` in a fenced ```mermaid block, and most
editors preview it directly. It is kept as source rather than a checked-in image so a
schema change produces a reviewable diff rather than an opaque binary.
