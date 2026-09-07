# `agents/evals/`

Evaluation cases run in CI.

**Against recorded fixtures, never live Bedrock** (R-609). CI stays deterministic and free, and a
PR is never gated on a network call to a paid service. The trade is that these prove the
*handling* of model output — grounding, truncation, empty results — not the model's own quality,
which is what a live eval would measure and what this suite deliberately does not claim.
