#!/usr/bin/env bash
#
# FR-003 / SC-002: applying unchanged definitions must report NO CHANGES AT ALL.
#
# Not "no unintended changes" -- FR-003 was deliberately tightened during analyze
# remediation, because "unintended" is a judgement call and a non-empty plan is a
# defect in the definitions, not a diff to review away.
#
# Usage: infra/tests/test_plan_idempotent.sh <dev|prod>
#   Requires AWS_PROFILE (or OIDC creds in CI) and an already-applied environment.

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
terraform init -input=false >/dev/null

# -detailed-exitcode: 0 = no changes, 1 = error, 2 = changes present.
# That third state is what makes this assertable rather than a grep over prose.
set +e
terraform plan -input=false -detailed-exitcode \
  -var="environment=${TARGET}" -out=/tmp/idempotency.tfplan >/tmp/idempotency.log 2>&1
PLAN_EXIT=$?
set -e
readonly PLAN_EXIT

case "${PLAN_EXIT}" in
  0)
    echo "PASS: '${TARGET}' is idempotent - plan reports no changes (FR-003, SC-002)."
    exit 0
    ;;
  2)
    echo "FAIL: '${TARGET}' is NOT idempotent - plan wants to change something." >&2
    echo >&2
    terraform show -no-color /tmp/idempotency.tfplan 2>/dev/null \
      | grep -E '^[[:space:]]+#|^Plan:' | head -40 >&2 || true
    echo >&2
    echo "FR-003: applying unchanged definitions must report no changes at all." >&2
    exit 1
    ;;
  *)
    echo "ERROR: terraform plan failed (exit ${PLAN_EXIT}):" >&2
    tail -20 /tmp/idempotency.log >&2
    exit 2
    ;;
esac
