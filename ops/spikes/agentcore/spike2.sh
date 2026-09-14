#!/usr/bin/env bash
# T061 extension: the three questions R-613a left open, from inside one runtime.
# One runtime, three invocations. Same teardown-on-exit and sweep as spike.sh.
#
# Usage: AWS_PROFILE=cloudpulse-dev ops/spikes/agentcore/spike2.sh
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
SUFFIX="t061spike2"
# Third run of this spike found claude-3-5-haiku EOL ("This model version has
# reached the end of its life"). Only Haiku 4.5 is ACTIVE, and only via an
# inference profile -- so the id is the profile, and the role needs the
# underlying foundation model in every region the profile routes to.
MODEL_ID="${SPIKE_MODEL_ID:-global.amazon.nova-2-lite-v1:0}"
FOUNDATION_MODEL="${MODEL_ID#*.}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="cloudpulse-${SUFFIX}-${ACCOUNT}"
ROLE="cloudpulse-${SUFFIX}-runtime"
SECRET="cloudpulse/${SUFFIX}/marker"
RUNTIME_NAME="cloudpulse_${SUFFIX}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
RUNTIME_ID=""

log() { printf '\n== %s\n' "$*"; }

cleanup() {
  set +e
  log "teardown"
  [ -n "$RUNTIME_ID" ] && aws bedrock-agentcore-control delete-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" >/dev/null && echo "deleted runtime $RUNTIME_ID"
  aws s3 rm "s3://$BUCKET" --recursive >/dev/null 2>&1
  aws s3api delete-bucket --bucket "$BUCKET" 2>/dev/null && echo "deleted bucket $BUCKET"
  aws secretsmanager delete-secret --region "$REGION" --secret-id "$SECRET" --force-delete-without-recovery >/dev/null 2>&1 && echo "deleted secret $SECRET"
  aws iam delete-role-policy --role-name "$ROLE" --policy-name runtime 2>/dev/null
  aws iam delete-role --role-name "$ROLE" 2>/dev/null && echo "deleted role $ROLE"
  for lg in $(aws logs describe-log-groups --region "$REGION" --query "logGroups[?contains(logGroupName, '$SUFFIX')].logGroupName" --output text); do
    aws logs delete-log-group --region "$REGION" --log-group-name "$lg" && echo "deleted log group $lg"
  done
  rm -rf "$WORK"
  log "post-teardown sweep"
  aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" --query "agentRuntimes[?contains(agentRuntimeName, '$SUFFIX')].agentRuntimeName" --output text
  aws s3api list-buckets --query "Buckets[?contains(Name, '$SUFFIX')].Name" --output text
  aws iam list-roles --query "Roles[?contains(RoleName, '$SUFFIX')].RoleName" --output text
  aws secretsmanager list-secrets --region "$REGION" --query "SecretList[?contains(Name, '$SUFFIX')].Name" --output text
  aws logs describe-log-groups --region "$REGION" --query "logGroups[?contains(logGroupName, '$SUFFIX')].logGroupName" --output text
  echo "(five empty lines above = clean)"
}
trap cleanup EXIT

log "1. package + bucket + secret"
# entryPoint is main.py: the probe agent is packaged under that name. boto3 is
# vendored because the managed runtime does not ship it (first run of this
# spike: ModuleNotFoundError) -- pure Python, so no platform flag is needed.
mkdir -p "$WORK/src" && cp "$HERE/main2.py" "$WORK/src/main.py"
python3 -m pip install --quiet --disable-pip-version-check --no-compile --target "$WORK/src" boto3
# The runtime refuses an artifact carrying bytecode from another Python
# ("Python cache files that are incompatible with the target runtime",
# second run of this spike, local pip being 3.14). Strip every cache dir; the
# deploy workflow's `cp -r app build/` would carry the same caches otherwise.
find "$WORK/src" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$WORK/src" -name "*.pyc" -delete
(cd "$WORK/src" && zip -qr ../agent.zip .)
ls -l "$WORK/agent.zip"
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
aws s3 cp "$WORK/agent.zip" "s3://$BUCKET/agent.zip" >/dev/null
SECRET_ARN=$(aws secretsmanager create-secret --region "$REGION" --name "$SECRET" --secret-string '{"marker":"read-from-inside-agentcore"}' --query ARN --output text)
echo "$SECRET_ARN"

log "2. execution role (logs, s3, bedrock:InvokeModel on $MODEL_ID, secretsmanager on the marker)"
cat > "$WORK/trust.json" <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"$ACCOUNT"}}}]}
JSON
cat > "$WORK/policy.json" <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents","logs:DescribeLogGroups","logs:DescribeLogStreams"],"Resource":"*"},
 {"Effect":"Allow","Action":["s3:GetObject"],"Resource":"arn:aws:s3:::$BUCKET/*"},
 {"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],"Resource":["arn:aws:bedrock:*::foundation-model/$FOUNDATION_MODEL","arn:aws:bedrock:*:$ACCOUNT:inference-profile/$MODEL_ID"]},
 {"Effect":"Allow","Action":["secretsmanager:GetSecretValue"],"Resource":"$SECRET_ARN"}
]}
JSON
ROLE_ARN=$(aws iam create-role --role-name "$ROLE" --assume-role-policy-document "file://$WORK/trust.json" --query Role.Arn --output text)
aws iam put-role-policy --role-name "$ROLE" --policy-name runtime --policy-document "file://$WORK/policy.json"
echo "$ROLE_ARN"; sleep 10

log "3. create-agent-runtime"
CREATE=$(aws bedrock-agentcore-control create-agent-runtime --region "$REGION" \
  --agent-runtime-name "$RUNTIME_NAME" \
  --agent-runtime-artifact "{\"codeConfiguration\":{\"code\":{\"s3\":{\"bucket\":\"$BUCKET\",\"prefix\":\"agent.zip\"}},\"runtime\":\"PYTHON_3_12\",\"entryPoint\":[\"main.py\"]}}" \
  --role-arn "$ROLE_ARN" \
  --network-configuration '{"networkMode":"PUBLIC"}' \
  --protocol-configuration '{"serverProtocol":"HTTP"}' \
  --environment-variables "{\"SPIKE_MODEL_ID\":\"$MODEL_ID\",\"SPIKE_SECRET_ID\":\"$SECRET_ARN\"}")
RUNTIME_ID=$(echo "$CREATE" | python3 -c 'import json,sys;print(json.load(sys.stdin)["agentRuntimeId"])')
RUNTIME_ARN=$(echo "$CREATE" | python3 -c 'import json,sys;print(json.load(sys.stdin)["agentRuntimeArn"])')
echo "$RUNTIME_ARN"

log "4. wait for READY"
for i in $(seq 1 60); do
  STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" --query status --output text)
  echo "  $i: $STATUS"; [ "$STATUS" = "READY" ] && break
  case "$STATUS" in *FAIL*) aws bedrock-agentcore-control get-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID"; exit 1;; esac
  sleep 10
done

log "5. three probes"
for test in egress credentials model; do
  SESSION="t061-spike2-$test-$(date +%s)-0123456789abcdef"
  aws bedrock-agentcore invoke-agent-runtime --region "$REGION" --cli-binary-format raw-in-base64-out \
    --agent-runtime-arn "$RUNTIME_ARN" --runtime-session-id "$SESSION" \
    --content-type application/json --accept application/json \
    --payload "{\"test\":\"$test\"}" "$WORK/$test.json" >/dev/null
  echo "--- $test ---"; python3 -m json.tool "$WORK/$test.json"
done

log "6. verdicts"
python3 - "$WORK" <<'PY'
import json, sys, pathlib
work = pathlib.Path(sys.argv[1])
for name in ("egress", "credentials", "model"):
    body = json.loads((work / f"{name}.json").read_text())
    print(f"{name:12s} {'PASS' if body.get('ok') else 'FAIL'}  {body.get('error', '')}")
PY
