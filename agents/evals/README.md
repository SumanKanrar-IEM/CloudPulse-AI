# `agents/evals/`

Evaluation cases run in CI.

**Against recorded fixtures, never live Bedrock** (R-609). CI stays deterministic and free, and a
PR is never gated on a network call to a paid service. The trade is that these prove the
*handling* of model output — grounding, truncation, empty results — not the model's own quality,
which is what a live eval would measure and what this suite deliberately does not claim.

## Layout

- `cases/*.json` — one recorded model reply each, with what the platform knew at the time
  (`known_references`, `known_figures`) and the verdict the pipeline must reach:
  `accept`, `reject` (optionally naming `rejected_reference`), or `parse_error`.
- `run_evals.py` — runs every case through the capability's own parser and the grounding
  validator, in the same mode the capability uses (`exact_figures` for the narrator). Exit 1 on
  any miss. The `agent-evals` CI job runs it on every PR.

## Editing a case

A prompt change that breaks a case is the case doing its job. If the expectation is genuinely
obsolete, edit it in the same PR as the prompt and say why in the case's `why` field — that
sentence is what a reader sees when the case fails, so it should explain the rule the case pins,
not restate the assertion.

Run locally from `backend/`:

```bash
python ../agents/evals/run_evals.py
```
