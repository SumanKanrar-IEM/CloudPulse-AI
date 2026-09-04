# `features/` — feature routes

Populated incrementally by specs 002–005: `accounts/` (spec 002, account admin),
`sdas/` (spec 003, SDA admin and "No SDA" triage — findings/scores/ownership stay
API-only for P1; a dedicated workbench is future-spec scope), and the governance
dashboard (spec 004) / cost views (spec 005).

**Spec 004** adds four feature areas: `overview/` (compliance score cards and
findings-by-type/severity charts, S28), `inventory/` (the paged/filtered resource
explorer and its detail panel, S29), `findings/` (the findings workbench —
filter, acknowledge, and view/attach a remediation suggestion, S30), and
`scans/` (per-account scan history with computed deltas and an on-demand
trigger, S31, P2). Each wraps its own slice of the OpenAPI-generated client in
a signal-based service (`*.service.ts`) rather than calling the generated
client directly from a component — the pattern every feature area here follows.

**Spec 005** adds three more: `cost/` (spend trend, per-project spend, per-project
budgets with their 80%/100% threshold state, and drill-down to the resources behind a
spend line — S39, S42, FR-003, FR-015), `utilization/` (overall, per-account and
per-project utilization with account → project → resource drill-down, S54, S55,
FR-018), and `iam-hygiene/` (flag-only unused-principal recommendations with their
evidence, S56, FR-019). Budget-overrun findings appear in the existing `findings/`
workbench, merged from `GET /budget-overruns` — they are the same `Finding` rows with
the same lifecycle, but they attach to a project rather than a resource, a shape
`GET /findings`'s response cannot carry (see tasks.md T036d).

Two presentation rules these screens follow, both because the underlying data cannot
support the simpler thing: a utilization figure is always rendered with the population
it was measured over ("2 of 4 enriched resources"), never as a bare percentage, since
resources with no known state are excluded from both halves of the ratio; and "not
enough data" is displayed as itself rather than as 0%.

Every screen added here inherits the FR-047a accessibility baseline: semantic markup with correct
roles and labels, full keyboard operability, and a visible focus indicator. The
`@angular-eslint` template rules gate the static half; keyboard operability and focus visibility
remain a reviewer's responsibility (FR-047b is explicit that automated rules do not prove them).
