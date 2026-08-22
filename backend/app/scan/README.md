# `app/scan/` — reserved package

Empty by design. The discovery engine is added here by **spec 002**: the Resource Groups Tagging
API sweep, Cloud Control API enumeration, targeted enrichment, and Step Functions orchestration.

Constitution Principle IV applies to everything in this package: discovery is **deterministic and
reproducible** — the same account state always yields the same inventory. No model call belongs on
this path.

Coverage definitions are **data, not code** (Principle V).
