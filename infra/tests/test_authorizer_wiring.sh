#!/usr/bin/env bash
#
# FR-043 / SC-009: a pre-authorizer rejection must use the uniform error envelope, not
# API Gateway's fixed `{"message":"Unauthorized"}`.
#
# This is deliberately a black-box HTTP check against the live endpoint, not an
# `aws apigatewayv2 get-authorizers` inspection of `identity_sources`. Two real bugs
# hit this exact seam (research.md R-004 addendum): a native JWT authorizer that could
# not customise its 401, and -- after replacing it with a Lambda authorizer -- an
# `identity_sources` misconfiguration that let a request with NO Authorization header
# skip the authorizer function entirely. A resource-shape check would have caught
# neither; only the actual response body would. No `terraform validate`/`plan` run
# would have caught either -- both were found live, against an applied environment.
#
# Usage: infra/tests/test_authorizer_wiring.sh <dev|prod>
#   Requires an already-applied environment. No AWS credentials needed for the checks
#   themselves (they're unauthenticated HTTP requests by design), but the environment
#   directory needs `terraform output` access to find the API endpoint.

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <dev|prod>" >&2
  exit 2
fi

TARGET="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
readonly TARGET
readonly ENV_DIR="${REPO_ROOT}/infra/envs/${TARGET}"

[[ -d "${ENV_DIR}" ]] || { echo "No such environment: ${TARGET}" >&2; exit 2; }

cd "${ENV_DIR}"
API_ENDPOINT="$(terraform output -raw api_endpoint)"
readonly API_ENDPOINT

FAILURES=0

# --- 1. No Authorization header at all must still get the uniform envelope ---
BODY=$(curl -sS -o - -w '\n%{http_code}' "${API_ENDPOINT}/me" 2>/dev/null || true)
STATUS="${BODY##*$'\n'}"
JSON="${BODY%$'\n'*}"

if [[ "${STATUS}" != "401" ]] || ! echo "${JSON}" | jq -e '.error.code == "UNAUTHORIZED"' >/dev/null 2>&1; then
  echo "FAIL: a request with NO Authorization header did not get the uniform envelope." >&2
  echo "      status=${STATUS} body=${JSON}" >&2
  echo "      This is the identity_sources bug (FR-043) -- the authorizer was likely" >&2
  echo "      never invoked. Check infra/modules/api/main.tf's identity_sources." >&2
  FAILURES=$((FAILURES + 1))
else
  echo "  ok: missing Authorization header -> uniform envelope"
fi

# --- 2. An invalid/malformed token must also get the uniform envelope -----
BODY=$(curl -sS -o - -w '\n%{http_code}' -H "Authorization: Bearer not-a-real-jwt" \
  "${API_ENDPOINT}/me" 2>/dev/null || true)
STATUS="${BODY##*$'\n'}"
JSON="${BODY%$'\n'*}"

if [[ "${STATUS}" != "401" ]] || ! echo "${JSON}" | jq -e '.error.code == "UNAUTHORIZED"' >/dev/null 2>&1; then
  echo "FAIL: a request with an invalid token did not get the uniform envelope." >&2
  echo "      status=${STATUS} body=${JSON}" >&2
  FAILURES=$((FAILURES + 1))
else
  echo "  ok: invalid token -> uniform envelope"
fi

# --- 3. /health must remain public regardless (FR-033a) --------------------
STATUS=$(curl -sS -o /dev/null -w '%{http_code}' "${API_ENDPOINT}/health" 2>/dev/null || echo "000")
if [[ "${STATUS}" != "200" ]]; then
  echo "FAIL: /health returned ${STATUS}, expected 200. It must stay public (FR-033a)." >&2
  FAILURES=$((FAILURES + 1))
else
  echo "  ok: /health still public"
fi

if [[ "${FAILURES}" -gt 0 ]]; then
  echo "${FAILURES} authorizer wiring problem(s) found." >&2
  exit 1
fi

echo "PASS: the authorizer is invoked for every case and every rejection uses FR-043's envelope."
