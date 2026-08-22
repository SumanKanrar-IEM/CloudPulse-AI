#!/usr/bin/env bash
#
# Every alarm publishes to the alert topic, and the email subscription is CONFIRMED
# (S7, FR-051, FR-052). **P2.**
#
# The confirmation check is the point. AWS creates an email subscription in
# `PendingConfirmation` until the recipient clicks the link, and a pending subscription
# looks exactly like working alerting right up until the first real incident — at which
# point nothing is delivered and nobody knows why.
#
# Usage: infra/tests/test_alarm_wiring.sh <dev|prod>
#   Requires AWS_PROFILE (or OIDC in CI) and an applied environment.

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

if ! TOPIC_ARN=$(terraform output -raw alerts_topic_arn 2>/dev/null); then
  echo "SKIP: observability is not provisioned in '${TARGET}'. It is P2 (FR-049..FR-053)."
  exit 0
fi

echo "Alert topic: ${TOPIC_ARN}"
FAILURES=0

# --- 1. Every alarm has an SNS action, and an OK action (FR-051, FR-052) ---
ALARMS=$(aws cloudwatch describe-alarms \
  --alarm-name-prefix "cloudpulse-${TARGET}" \
  --query 'MetricAlarms[].[AlarmName,length(AlarmActions),length(OKActions)]' \
  --output text)

if [[ -z "${ALARMS}" ]]; then
  echo "FAIL: no alarms found for cloudpulse-${TARGET}" >&2
  exit 1
fi

while read -r name alarm_actions ok_actions; do
  [[ -z "${name}" ]] && continue
  if [[ "${alarm_actions}" -lt 1 ]]; then
    echo "FAIL: ${name} has no alarm action -- it is a dashboard widget, not an alert (FR-051)" >&2
    FAILURES=$((FAILURES + 1))
  fi
  if [[ "${ok_actions}" -lt 1 ]]; then
    echo "FAIL: ${name} has no OK action -- recovery would be invisible (FR-052)" >&2
    FAILURES=$((FAILURES + 1))
  fi
  echo "  ok: ${name} (alarm=${alarm_actions} ok=${ok_actions})"
done <<< "${ALARMS}"

# --- 2. The email subscription is CONFIRMED, not merely created ------------
SUBS=$(aws sns list-subscriptions-by-topic --topic-arn "${TOPIC_ARN}" \
  --query 'Subscriptions[].[Protocol,SubscriptionArn]' --output text)

if [[ -z "${SUBS}" ]]; then
  echo "FAIL: the alert topic has no subscriptions -- alarms fire into nothing (FR-051)" >&2
  FAILURES=$((FAILURES + 1))
else
  while read -r protocol arn; do
    [[ -z "${protocol}" ]] && continue
    if [[ "${arn}" == "PendingConfirmation" ]]; then
      echo "FAIL: the ${protocol} subscription is PENDING. Someone must click the AWS" >&2
      echo "      confirmation email. Until then alerting is inert and looks healthy." >&2
      FAILURES=$((FAILURES + 1))
    else
      echo "  ok: ${protocol} subscription confirmed"
    fi
  done <<< "${SUBS}"
fi

# --- 3. The heartbeat alarm treats missing data as breaching (FR-053) ------
HEARTBEAT_MISSING=$(aws cloudwatch describe-alarms \
  --alarm-names "cloudpulse-${TARGET}-alerting-heartbeat" \
  --query 'MetricAlarms[0].TreatMissingData' --output text 2>/dev/null || echo "none")

if [[ "${HEARTBEAT_MISSING}" != "breaching" ]]; then
  echo "FAIL: the heartbeat alarm treats missing data as '${HEARTBEAT_MISSING}'." >&2
  echo "      It must be 'breaching' -- a missing heartbeat IS the failure (FR-053)." >&2
  FAILURES=$((FAILURES + 1))
else
  echo "  ok: heartbeat treats missing data as breaching"
fi

if [[ "${FAILURES}" -gt 0 ]]; then
  echo "${FAILURES} alerting problem(s) found." >&2
  exit 1
fi

echo "PASS: alerting is wired and confirmed."
