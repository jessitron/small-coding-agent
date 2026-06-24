#!/usr/bin/env bash
# Layer 5 cloud smoke (see notes/local-testing-advice.md): invoke the DEPLOYED
# AgentCore runtime end-to-end. Confirms wiring (IAM, networking, the dispatcher
# in front of the agent) — not logic, which we prove locally. Fails loud.
set -euo pipefail
cd "$(dirname "$0")/.."

AWS_PROFILE="${AWS_PROFILE:-sandbox}"; export AWS_PROFILE
# Pin region explicitly (this machine's env defaults to us-east-1; we deploy to us-west-2).
REGION="us-west-2"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
RUNTIME_NAME="${RUNTIME_NAME:-trainer_agent}"

RUNTIME_ARN="${RUNTIME_ARN:-$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeArn | [0]" --output text)}"
echo "== runtime: $RUNTIME_ARN"

# AgentCore requires runtimeSessionId >= 33 chars. Keep it stable per "session".
SESSION_ID="${SESSION_ID:-trainer-agent-cloud-smoke-session-0001}"
OUT="$(mktemp)"

echo "== invoke  {\"message\":\"hello from the cloud smoke\"}"
aws bedrock-agentcore invoke-agent-runtime --region "$REGION" \
  --cli-binary-format raw-in-base64-out \
  --agent-runtime-arn "$RUNTIME_ARN" \
  --runtime-session-id "$SESSION_ID" \
  --content-type "application/json" \
  --accept "application/json" \
  --payload '{"message":"hello from the cloud smoke"}' \
  "$OUT" >/tmp/invoke-meta.json

echo "== response:"
cat "$OUT"; echo

if grep -q '"reply": "hi"' "$OUT"; then
  echo "PASS"
else
  echo "FAIL: unexpected reply"; cat /tmp/invoke-meta.json; exit 1
fi
