# `agents/prompts/`

Versioned prompt sources, one per capability.

Content-hashed by `backend/app/governance/definition_hash.py`; the hash lands on every
`agent_run` row (FR-005). Editing a prompt changes the hash, which is what makes "the digest reads
differently this week" traceable to a specific commit rather than to model drift.

A prompt change that breaks a grounding expectation must fail CI — see `../evals/`.
