#!/usr/bin/env bash
# Trace-propagation end-to-end test. Wires the test client (scripts/propagation_test.py)
# to export to the SAME Boswell collector as prod, fetches the Function URL +
# bearer, then runs the client. The client starts a root span and calls the front
# door with traceparent injected; success means ONE trace spans three services:
#   trainer-agent-test-client -> trainer-agent-frontdoor -> trainer-agent
set -euo pipefail
cd "$(dirname "$0")/.."

AWS_PROFILE="${AWS_PROFILE:-sandbox}"; export AWS_PROFILE
REGION="us-west-2"; export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
LAMBDA_NAME="trainer-agent-frontdoor"
SECRET_NAME="trainer-agent/frontdoor-bearer"

# Export the client's spans through the shared Boswell collector (prod path), so
# they land in the same Honeycomb env as the frontdoor + agent spans.
BOSWELL_TRACES_URL="https://45exz5ki5veyvldhaojdynf3ty0pqnno.lambda-url.us-west-2.on.aws/v1/traces"
BOSWELL_TOKEN="$(aws lambda get-function-configuration --function-name boswell --region "$REGION" \
  --query 'Environment.Variables.INGEST_BEARER_TOKEN' --output text)"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="$BOSWELL_TRACES_URL"
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer ${BOSWELL_TOKEN}"

export FRONTDOOR_URL="$(aws lambda get-function-url-config --function-name "$LAMBDA_NAME" --region "$REGION" \
  --query 'FunctionUrl' --output text)"
export FRONTDOOR_BEARER="$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --region "$REGION" \
  --query 'SecretString' --output text)"
export SESSION_ID="${SESSION_ID:-trainer-agent-propagation-test-session-0001}"

echo "== front door: $FRONTDOOR_URL"
uv run python scripts/propagation_test.py
