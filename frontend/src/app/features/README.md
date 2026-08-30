# `features/` — feature routes

Populated incrementally by specs 002–005: `accounts/` (spec 002, account admin),
`sdas/` (spec 003, SDA admin and "No SDA" triage — findings/scores/ownership stay
API-only for P1; a dedicated workbench is future-spec scope), and the remaining
governance dashboard / cost views by specs 004–005.

Every screen added here inherits the FR-047a accessibility baseline: semantic markup with correct
roles and labels, full keyboard operability, and a visible focus indicator. The
`@angular-eslint` template rules gate the static half; keyboard operability and focus visibility
remain a reviewer's responsibility (FR-047b is explicit that automated rules do not prove them).
