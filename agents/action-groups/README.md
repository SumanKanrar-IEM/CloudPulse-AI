# `agents/action-groups/`

Lambda handlers backing each action group.

**These call the platform HTTP API, never the database** (R-602). Reaching the data store directly
would bypass the tenant scoping and the read-only enforcement that
`backend/app/core/agent_access.py` exists to provide, and FR-056 forbids it.

No provider SDK call belongs here beyond the HTTP client — cloud SDK use stays inside
`backend/connectors/` (Principle V, FR-054).
