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

Every screen added here inherits the FR-047a accessibility baseline: semantic markup with correct
roles and labels, full keyboard operability, and a visible focus indicator. The
`@angular-eslint` template rules gate the static half; keyboard operability and focus visibility
remain a reviewer's responsibility (FR-047b is explicit that automated rules do not prove them).
