# `features/` — reserved

Empty by design. Feature routes are added here by specs 002–005 (accounts admin, findings
workbench, governance dashboard, cost views).

Every screen added here inherits the FR-047a accessibility baseline: semantic markup with correct
roles and labels, full keyboard operability, and a visible focus indicator. The
`@angular-eslint` template rules gate the static half; keyboard operability and focus visibility
remain a reviewer's responsibility (FR-047b is explicit that automated rules do not prove them).
