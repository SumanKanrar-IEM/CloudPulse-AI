#!/usr/bin/env bash
#
# Destroy a CloudPulse AI environment.
#
# FR-005a / R-010, protection layer 3 of 3 — and the only one that refuses BEFORE
# touching anything. That ordering is the whole point:
#
#   layer 1  aws_rds_cluster.deletion_protection  -> refuses at the cluster, last
#   layer 2  lifecycle { prevent_destroy }        -> fails partway through a plan
#   layer 3  this guard                            -> refuses before terraform runs
#
# The "teardown aimed at prod" edge case requires refusal before anything is touched,
# not a partial destroy that stops at the protected resource. Layers 1 and 2 cannot
# provide that; this can.
#
# Usage: ops/teardown.sh <dev>

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly PROTECTED_ENVIRONMENTS=("prod" "production")

usage() {
  cat >&2 <<'USAGE'
Usage: ops/teardown.sh <environment>

  environment   Must be 'dev'. Production teardown is refused by design (FR-005a).

Destroys everything in infra/envs/<environment>. The Terraform state backend and the
OIDC role created by infra/bootstrap/ are NOT touched — tearing those down is a
separate, deliberate act.
USAGE
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

# Lowercase via tr, not ${1,,}: that expansion needs bash 4+, and macOS ships bash 3.2.
# A guard that errors out instead of refusing fails OPEN, which is worse than no guard.
TARGET="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
readonly TARGET

# --- The guard. Deliberately the first thing that happens after argument parsing:
# --- no terraform invocation, no init, no state read, nothing.
for protected in "${PROTECTED_ENVIRONMENTS[@]}"; do
  if [[ "${TARGET}" == "${protected}" ]]; then
    cat >&2 <<EOF
REFUSED: '${TARGET}' is a protected environment (FR-005a).

Nothing has been touched. No terraform command was run.

The prod governance record holds data that cannot be rebuilt by re-scanning:
registered accounts, tagging rules, the SDA registry, and the append-only audit
trail. Destroying it is not a routine operation and is not available from this
script.

If you genuinely intend to destroy production, that is a deliberate out-of-band
act: disable deletion protection on the cluster, remove the prevent_destroy
lifecycle blocks, and run terraform destroy by hand — with a colleague watching.
EOF
    exit 1
  fi
done

readonly ENV_DIR="${REPO_ROOT}/infra/envs/${TARGET}"

if [[ ! -d "${ENV_DIR}" ]]; then
  echo "REFUSED: no environment directory at infra/envs/${TARGET}" >&2
  exit 1
fi

if [[ -z "${AWS_PROFILE:-}" ]] && [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && [[ -z "${AWS_ROLE_ARN:-}" ]]; then
  echo "REFUSED: no AWS credentials in the environment. Export AWS_PROFILE first." >&2
  exit 1
fi

echo "About to DESTROY the '${TARGET}' environment in:"
aws sts get-caller-identity --query '[Account,Arn]' --output text >&2 || {
  echo "REFUSED: could not resolve the AWS identity." >&2
  exit 1
}
echo
read -r -p "Type the environment name to confirm: " confirmation
if [[ "${confirmation}" != "${TARGET}" ]]; then
  echo "Aborted — confirmation did not match. Nothing destroyed." >&2
  exit 1
fi

cd "${ENV_DIR}"
terraform init -input=false
terraform destroy -input=false -var="environment=${TARGET}"
