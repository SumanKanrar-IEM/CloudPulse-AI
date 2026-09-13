#!/usr/bin/env bash
# T061: deploy the smallest AgentCore Runtime agent, invoke it once, tear it
# down. Everything it creates is named with one suffix so the teardown at the
# bottom cannot miss anything, and the teardown runs on exit whether the spike
# passed or not (playbook 0.5.3). Prints every step so the transcript is the
# record for research.md R-613a.
#
# Usage: AWS_PROFILE=cloudpulse-dev ops/spikes/agentcore/spike.sh
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
SUFFIX="t061spike"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="cloudpulse-${SUFFIX}-${ACCOUNT}"
ROLE="cloudpulse-${SUFFIX}-runtime"
RUNTIME_NAME="cloudpulse_${SUFFIX}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
RUNTIME_ID=""

log() { printf '\n== %s\n' "$*"; }

cleanup() {
  set +e
  log "teardown"
  if [ -n "$RUNTIME_ID" ]; then
    aws bedrock-agentcore-control delete-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" >/dev/null && echo "deleted runtime $RUNTIME_ID"
  fi
  aws s3 rm "s3://$BUCKET" --recursive >/dev/null 2>&1
  aws s3api delete-bucket --bucket "$BUCKET" 2>/dev/null && echo "deleted bucket $BUCKET"
  aws iam delete-role-policy --role-name "$ROLE" --policy-name runtime 2>/dev/null
  aws iam delete-role --role-name "$ROLE" 2>/dev/null && echo "deleted role $ROLE"
  # The runtime creates its own log group (/aws/bedrock-agentcore/runtimes/<id>-DEFAULT)
  # with no retention -- the orphan class playbook 0.5.3 names, and the first run of
  # this spike left two behind. Delete by prefix so every runtime id this suffix ever
  # produced is covered, not only the one this run created.
  for lg in $(aws logs describe-log-groups --region "$REGION" --query "logGroups[?contains(logGroupName, '$SUFFIX')].logGroupName" --output text); do
    aws logs delete-log-group --region "$REGION" --log-group-name "$lg" && echo "deleted log group $lg"
  done
  rm -rf "$WORK"
  log "post-teardown sweep"
  aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" --query "agentRuntimes[?contains(agentRuntimeName, '$SUFFIX')].agentRuntimeName" --output text
  aws s3api list-buckets --query "Buckets[?contains(Name, '$SUFFIX')].Name" --output text
  aws iam list-roles --query "Roles[?contains(RoleName, '$SUFFIX')].RoleName" --output text
  aws logs describe-log-groups --region "$REGION" --query "logGroups[?contains(logGroupName, '$SUFFIX')].logGroupName" --output text
  echo "(four empty lines above = clean)"
}
trap cleanup EXIT

log "1. package"
(cd "$HERE" && zip -qj "$WORK/agent.zip" main.py)
ls -l "$WORK/agent.zip"

log "2. bucket + upload"
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
aws s3 cp "$WORK/agent.zip" "s3://$BUCKET/agent.zip" >/dev/null
echo "s3://$BUCKET/agent.zip"

log "3. execution role"
cat > "$WORK/trust.json" <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"$ACCOUNT"}}}]}
JSON
cat > "$WORK/policy.json" <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents","logs:DescribeLogGroups","logs:DescribeLogStreams"],"Resource":"*"},
 {"Effect":"Allow","Action":["s3:GetObject"],"Resource":"arn:aws:s3:::$BUCKET/*"}
]}
JSON
ROLE_ARN=$(aws iam create-role --role-name "$ROLE" --assume-role-policy-document "file://$WORK/trust.json" --query Role.Arn --output text)
aws iam put-role-policy --role-name "$ROLE" --policy-name runtime --policy-document "file://$WORK/policy.json"
echo "$ROLE_ARN"
sleep 10  # IAM propagation

log "4. create-agent-runtime (code deploy, PYTHON_3_12, PUBLIC, HTTP)"
CREATE=$(aws bedrock-agentcore-control create-agent-runtime --region "$REGION" \
  --agent-runtime-name "$RUNTIME_NAME" \
  --agent-runtime-artifact "{\"codeConfiguration\":{\"code\":{\"s3\":{\"bucket\":\"$BUCKET\",\"prefix\":\"agent.zip\"}},\"runtime\":\"PYTHON_3_12\",\"entryPoint\":[\"main.py\"]}}" \
  --role-arn "$ROLE_ARN" \
  --network-configuration '{"networkMode":"PUBLIC"}' \
  --protocol-configuration '{"serverProtocol":"HTTP"}')
echo "$CREATE"
RUNTIME_ID=$(echo "$CREATE" | python3 -c 'import json,sys;print(json.load(sys.stdin)["agentRuntimeId"])')
RUNTIME_ARN=$(echo "$CREATE" | python3 -c 'import json,sys;print(json.load(sys.stdin)["agentRuntimeArn"])')

log "5. wait for READY"
for i in $(seq 1 60); do
  STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" --query status --output text)
  echo "  $i: $STATUS"
  case "$STATUS" in READY) break;; *FAIL*|DELETING|DELETED) aws bedrock-agentcore-control get-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID"; exit 1;; esac
  sleep 10
done
[ "$STATUS" = "READY" ] || { echo "never reached READY"; exit 1; }

log "6. invoke"
SESSION="t061-spike-session-$(date +%s)-0123456789abcdef"   # >= 33 chars
aws bedrock-agentcore invoke-agent-runtime --region "$REGION" --cli-binary-format raw-in-base64-out \
  --agent-runtime-arn "$RUNTIME_ARN" \
  --runtime-session-id "$SESSION" \
  --content-type application/json --accept application/json \
  --payload '{"prompt":"hello from T061"}' "$WORK/response.json"
echo "--- response body ---"
cat "$WORK/response.json"; echo

log "7. result"
python3 - "$WORK/response.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body.get("echo", {}).get("prompt") == "hello from T061", body
print("SPIKE PASSED: runtime deployed from a code zip, answered /invocations, echoed the payload")
print("python inside the runtime:", body.get("python"))
PY
