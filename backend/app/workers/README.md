# `app/workers/` — reserved package, unused so far

Spec 003's own SQS-triggered Lambda workers (tag validation, compliance scoring,
ownership attribution) landed in `handlers/` instead, as
`compliance_validation_worker_handler.py`/`ownership_attribution_worker_handler.py`
— matching `scan_worker_handler.py`'s existing one-file-per-Lambda convention rather
than this package's original plan-time placeholder. Decided during spec 003's
`/speckit-tasks`, not an implementation-time improvisation.

Still reserved for **spec 005** (cost and utilization ingestion) unless that spec also
prefers `handlers/`.

Spec 001 provides the surrounding contracts a worker uses either way: the
tenant-scoped session (`app/core/db.py`), the append-only audit helper
(`app/core/audit.py`), and the structured logger with redaction
(`app/core/logging.py`).
