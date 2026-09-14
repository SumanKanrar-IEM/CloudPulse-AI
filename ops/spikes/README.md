# `ops/spikes/`

Throwaway experiments that answer one question against real AWS, kept because the answer
is recorded in a spec's `research.md` and a reader should be able to rerun the question.

Every spike here **tears down on exit whether it passed or not** and ends with a sweep that
prints what survived, per `SPECKIT_PLAYBOOK.md` §0.5.3. Nothing under this directory is
deployed by CI or imported by the platform.

| Spike | Question | Answer |
| --- | --- | --- |
| `agentcore/spike.sh` | Does an AgentCore Runtime deploy and answer in this account? (spec 006, T061) | Yes — research.md R-613a |
| `agentcore/spike2.sh` | From inside it: public HTTPS egress? role credentials and Secrets Manager? a model call? | Yes, yes, no for Anthropic (Marketplace block, R-613b) — **yes for Amazon Nova** (R-613c) |
