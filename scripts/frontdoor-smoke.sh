#!/usr/bin/env bash
# Smoke the DEPLOYED front door: POST to the Function URL with the bearer token
# and assert the agent's reply comes back. Confirms auth + the Lambda->AgentCore
# proxy wiring end to end. Fails loud.
set -euo pipefail
cd "$(dirname "$0")/.."

AWS_PROFILE="${AWS_PROFILE:-sandbox}"; export AWS_PROFILE
REGION="us-west-2"; export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
LAMBDA_NAME="trainer-agent-frontdoor"
SECRET_NAME="trainer-agent/frontdoor-bearer"

FUNCTION_URL="$(aws lambda get-function-url-config --function-name "$LAMBDA_NAME" --region "$REGION" \
  --query 'FunctionUrl' --output text)"
BEARER="$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --region "$REGION" \
  --query 'SecretString' --output text)"
# AgentCore requires runtimeSessionId >= 33 chars.
SESSION_ID="${SESSION_ID:-trainer-agent-frontdoor-smoke-session-0001}"

echo "== POST $FUNCTION_URL"
reply="$(curl -fsS -XPOST "$FUNCTION_URL" \
  -H "Authorization: Bearer $BEARER" \
  -H 'Content-Type: application/json' \
  -d "{\"message\":\"hello from the frontdoor smoke\",\"session_id\":\"$SESSION_ID\"}")"
echo "== response: $reply"

if echo "$reply" | grep -q '"reply": "hi"'; then
  echo "PASS"
else
  echo "FAIL: unexpected reply"; exit 1
fi

# Also confirm auth actually rejects a bad token (should be 401, not 200).
echo "== negative check: bad bearer should 401"
code="$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$FUNCTION_URL" \
  -H "Authorization: Bearer not-the-token" \
  -H 'Content-Type: application/json' \
  -d "{\"message\":\"nope\",\"session_id\":\"$SESSION_ID\"}")"
if [ "$code" = "401" ]; then
  echo "PASS (got 401)"
else
  echo "FAIL: expected 401, got $code"; exit 1
fi
