# `app/workers/` — reserved package

Empty by design. SQS-triggered Lambda workers are added here by:

- **spec 003** — tag validation, compliance scoring, ownership attribution
- **spec 005** — cost and utilization ingestion

Spec 001 provides the surrounding contracts these workers use: the tenant-scoped session
(`app/core/db.py`), the append-only audit helper (`app/core/audit.py`), and the structured
logger with redaction (`app/core/logging.py`).
