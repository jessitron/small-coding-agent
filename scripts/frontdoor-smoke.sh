#!/usr/bin/env bash
# Layer 5b cloud smoke (see notes/local-testing-advice.md): the REAL app path —
# POST the Function URL with the bearer, THROUGH the front-door Lambda to the
# runtime. This is the canonical end-to-end "does it work". Also checks what only
# the front door can break: bearer auth (200 vs 401) and the interface-version
# header. To isolate the runtime alone, use scripts/cloud-smoke.sh (L5a). Fails loud.
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
HDRS="$(mktemp)"
reply="$(curl -fsS -D "$HDRS" -XPOST "$FUNCTION_URL" \
  -H "Authorization: Bearer $BEARER" \
  -H 'Content-Type: application/json' \
  -H 'X-Trainer-Agent-Interface-Version: 2.0' \
  -d "{\"message\":\"hello from the frontdoor smoke\",\"session_id\":\"$SESSION_ID\",\"seq\":1,\"state\":{}}")"
echo "== response: $reply"

# Contract-shaped {reply,status} proves the auth + Lambda->AgentCore proxy works.
# (Until the app adds trainer-agent/instructions.md the status is "error".)
if echo "$reply" | grep -q '"status"' && echo "$reply" | grep -q '"reply"'; then
  echo "PASS (contract-shaped reply)"
else
  echo "FAIL: response not contract-shaped {reply,status}"; exit 1
fi

# Confirm the front door advertises interface version 2.0.
if grep -qi '^x-trainer-agent-interface-version: 2.0' "$HDRS"; then
  echo "PASS (advertises interface 2.0)"
else
  echo "FAIL: expected version header 2.0"; grep -i interface-version "$HDRS" || true; exit 1
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
