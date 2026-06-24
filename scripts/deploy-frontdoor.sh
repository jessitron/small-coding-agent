#!/usr/bin/env bash
# Deploy the Trainer Agent FRONT DOOR: a thin authenticated Lambda + public
# Function URL in front of the AgentCore runtime. The app POSTs JSON with a
# bearer token; the Lambda validates it and proxies to InvokeAgentRuntime
# (SigV4 via its own role), propagating trace context.
#
# Like scripts/deploy.sh, this script IS the infrastructure record (see
# notes/infrastructure.md) and is idempotent/re-runnable: each resource is reused
# if it already exists. Requires AWS_PROFILE=sandbox.
#
# Resources: Secrets Manager secret (bearer) -> IAM role -> Lambda (zip) ->
# Function URL. Smoke with scripts/frontdoor-smoke.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

AWS_PROFILE="${AWS_PROFILE:-sandbox}"; export AWS_PROFILE
# Pin region explicitly — do NOT inherit AWS_REGION/AWS_DEFAULT_REGION (this
# machine defaults to us-east-1; the runtime lives in us-west-2).
REGION="us-west-2"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACCOUNT="414852377253"

RUNTIME_NAME="trainer_agent"
LAMBDA_NAME="trainer-agent-frontdoor"
ROLE_NAME="trainer-agent-frontdoor-lambda"
SECRET_NAME="trainer-agent/frontdoor-bearer"

echo "== account=$ACCOUNT region=$REGION profile=$AWS_PROFILE lambda=$LAMBDA_NAME"

# 1. Resolve the AgentCore runtime ARN (created by scripts/deploy.sh) ----------
RUNTIME_ARN="$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeArn | [0]" \
  --output text 2>/dev/null || echo "None")"
if [ "$RUNTIME_ARN" = "None" ] || [ -z "$RUNTIME_ARN" ]; then
  echo "!! runtime '$RUNTIME_NAME' not found — run scripts/deploy.sh first"; exit 1
fi
echo "== runtime arn: $RUNTIME_ARN"

# 2. Bearer secret (create with a random value if absent) ---------------------
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "== secret $SECRET_NAME exists"
else
  echo "== creating secret $SECRET_NAME (random bearer token)"
  aws secretsmanager create-secret --name "$SECRET_NAME" --region "$REGION" \
    --description "Shared bearer token the app presents to the Trainer Agent front door" \
    --secret-string "$(openssl rand -hex 32)" >/dev/null
fi
SECRET_ARN="$(aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" \
  --query 'ARN' --output text)"
echo "== secret arn: $SECRET_ARN"

# 3. IAM role: trust + basic-execution (logs) + inline (invoke runtime, read secret)
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "== IAM role $ROLE_NAME exists"
else
  echo "== creating IAM role $ROLE_NAME"
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document file://scripts/aws/frontdoor-trust-policy.json \
    --description "Execution role for the Trainer Agent front-door Lambda" >/dev/null
fi
aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Inline policy needs the dynamic runtime + secret ARNs, so generate it here.
POLICY_FILE="$(mktemp)"
cat >"$POLICY_FILE" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeTheTrainerAgentRuntime",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:InvokeAgentRuntime",
      "Resource": ["${RUNTIME_ARN}", "${RUNTIME_ARN}/*"]
    },
    {
      "Sid": "ReadTheBearerSecret",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_ARN}"
    }
  ]
}
JSON
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name "trainer-agent-frontdoor-permissions" \
  --policy-document "file://$POLICY_FILE"
rm -f "$POLICY_FILE"
ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"
echo "== role arn: $ROLE_ARN"

# 4. Build the deployment zip (linux/arm64 wheels for python3.13) --------------
BUILD_DIR="frontdoor/build"
ZIP="$ROOT/frontdoor/frontdoor.zip"
echo "== building zip (arm64 / py3.13 wheels)"
rm -rf "$BUILD_DIR" "$ZIP"; mkdir -p "$BUILD_DIR"
uv pip install --quiet --target "$BUILD_DIR" \
  --python-platform aarch64-unknown-linux-gnu \
  --python-version 3.13 \
  --only-binary :all: \
  -r frontdoor/requirements.txt
cp frontdoor/handler.py frontdoor/contract.py "$BUILD_DIR/"
( cd "$BUILD_DIR" && zip -qr "$ZIP" . )
echo "== zip: $ZIP ($(du -h "$ZIP" | cut -f1))"

# 5. Telemetry env — route traces through the shared Boswell collector ---------
# Same Boswell Lambda the agent uses (notes/telemetry.md); traces land in the
# shared Honeycomb env (cynditaylor-com-bot), separated by service.name.
BOSWELL_TRACES_URL="https://45exz5ki5veyvldhaojdynf3ty0pqnno.lambda-url.us-west-2.on.aws/v1/traces"
BOSWELL_TOKEN="$(aws lambda get-function-configuration --function-name boswell --region "$REGION" \
  --query 'Environment.Variables.INGEST_BEARER_TOKEN' --output text 2>/dev/null || echo '')"
ENV_FILE="$(mktemp)"
if [ -n "$BOSWELL_TOKEN" ] && [ "$BOSWELL_TOKEN" != "None" ]; then
  printf '{"Variables":{"AGENT_RUNTIME_ARN":"%s","BEARER_SECRET_ID":"%s","OTEL_SERVICE_NAME":"trainer-agent-frontdoor","OTEL_EXPORTER_OTLP_PROTOCOL":"http/protobuf","OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":"%s","OTEL_EXPORTER_OTLP_HEADERS":"authorization=Bearer %s"}}' \
    "$RUNTIME_ARN" "$SECRET_ARN" "$BOSWELL_TRACES_URL" "$BOSWELL_TOKEN" >"$ENV_FILE"
  echo "== telemetry: routing frontdoor traces through Boswell"
else
  printf '{"Variables":{"AGENT_RUNTIME_ARN":"%s","BEARER_SECRET_ID":"%s"}}' \
    "$RUNTIME_ARN" "$SECRET_ARN" >"$ENV_FILE"
  echo "== WARN: no Boswell token; deploying WITHOUT telemetry env"
fi

# 6. Lambda function (create or update) ----------------------------------------
if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "== Lambda $LAMBDA_NAME exists; updating code + config"
  aws lambda update-function-code --function-name "$LAMBDA_NAME" --region "$REGION" \
    --zip-file "fileb://$ZIP" --architectures arm64 >/dev/null
  aws lambda wait function-updated --function-name "$LAMBDA_NAME" --region "$REGION"
  aws lambda update-function-configuration --function-name "$LAMBDA_NAME" --region "$REGION" \
    --runtime python3.13 --handler handler.lambda_handler \
    --role "$ROLE_ARN" --timeout 300 --memory-size 128 \
    --environment "file://$ENV_FILE" >/dev/null
  aws lambda wait function-updated --function-name "$LAMBDA_NAME" --region "$REGION"
else
  echo "== creating Lambda $LAMBDA_NAME"
  # The role may take a few seconds to become assumable; retry.
  for attempt in 1 2 3 4 5 6; do
    if aws lambda create-function --function-name "$LAMBDA_NAME" --region "$REGION" \
        --runtime python3.13 --architectures arm64 \
        --role "$ROLE_ARN" --handler handler.lambda_handler \
        --timeout 300 --memory-size 128 \
        --zip-file "fileb://$ZIP" \
        --environment "file://$ENV_FILE" >/dev/null 2>/tmp/frontdoor-create.err; then
      break
    fi
    echo "   create attempt $attempt failed (role may not be assumable yet); retry in 10s"
    cat /tmp/frontdoor-create.err
    sleep 10
  done
  aws lambda wait function-active --function-name "$LAMBDA_NAME" --region "$REGION"
fi
rm -f "$ENV_FILE"

# 7. Function URL (public; the Lambda validates the bearer itself) -------------
if aws lambda get-function-url-config --function-name "$LAMBDA_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "== Function URL exists"
else
  echo "== creating Function URL (auth NONE)"
  aws lambda create-function-url-config --function-name "$LAMBDA_NAME" --region "$REGION" \
    --auth-type NONE >/dev/null
fi
# Public invoke permissions for the Function URL (idempotent). A public (NONE)
# Function URL needs BOTH statements as of Oct 2025 — `InvokeFunctionUrl` alone
# gets a silent 403 AccessDeniedException at the URL gate with no Lambda logs.
# See https://www.honeycomb.io/blog/running-opentelemetry-collector-lambda
aws lambda add-permission --function-name "$LAMBDA_NAME" --region "$REGION" \
  --statement-id frontdoor-public-url --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
aws lambda add-permission --function-name "$LAMBDA_NAME" --region "$REGION" \
  --statement-id frontdoor-public-invoke --action lambda:InvokeFunction \
  --principal '*' --invoked-via-function-url >/dev/null 2>&1 || true

FUNCTION_URL="$(aws lambda get-function-url-config --function-name "$LAMBDA_NAME" --region "$REGION" \
  --query 'FunctionUrl' --output text)"

echo
echo "== DONE."
echo "Lambda:        $LAMBDA_NAME"
echo "Role ARN:      $ROLE_ARN"
echo "Secret:        $SECRET_NAME ($SECRET_ARN)"
echo "Function URL:  $FUNCTION_URL"
echo
echo "Smoke it:  ./scripts/frontdoor-smoke.sh"
echo "Test trace propagation:  ./scripts/propagation-test.sh"
