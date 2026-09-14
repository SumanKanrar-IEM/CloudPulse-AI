# `agents/action-groups/`

The tool allowlists (`<capability>_tools.py`, each one `ALLOWED_PATHS`) and the HTTP client every
tool call goes through (`_platform_api.py`). Named for Bedrock Agents' action groups, which these
were until T064; under AgentCore Runtime the tool calls are served inside `agents/runtime/main.py`
and this directory holds what the runtime consults.

**These call the platform HTTP API, never the database** (R-602). Reaching the data store directly
would bypass the tenant scoping and the read-only enforcement that
`backend/app/core/agent_access.py` exists to provide, and FR-056 forbids it.

**One provider-SDK call, and the reason it is allowed.** `_platform_api.client_secret()` reads the
agent's own Cognito client secret from Secrets Manager with boto3, under the runtime's execution
role. It replaced the Lambda Parameters-and-Secrets extension, which is Lambda-only; R-613b verified
the role reaches boto3 inside the runtime with no credential environment variables. This is the
same class of exception `backend/app/core/db.py` holds for the platform's own database credential
and `ops/scripts/check_connector_boundary.py` names: it operates the platform's own
infrastructure, never a scanned account. Nothing here can assume a scanner role or read an
ExternalId, and `backend/tests/unit/test_agent_runtime.py` asserts that against the source. No
other SDK use belongs here — cloud discovery stays inside `backend/connectors/` (Principle V,
FR-054).
