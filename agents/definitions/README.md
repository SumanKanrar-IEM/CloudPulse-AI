# `agents/definitions/`

One Bedrock Agent definition and action-group schema per capability: `digest`, `suggester`,
`advisor`, `narrator`.

A definition is content-hashed and the hash is stored on every `agent_run` row (FR-005, R-608), so
a change in behaviour traces to a change in definition rather than being unexplainable.

Action-group schemas may only expose operations backed by APIs specs 002, 003 and 005 already
deliver, reached through the read-only principal (R-602). A schema that would need a new data path
is a spec change, not a definition change.
