#!/usr/bin/env bash
# Deploy the Trainer Agent to Amazon Bedrock AgentCore Runtime.
#
# This script IS the infrastructure record (see notes/infrastructure.md and the
# SEAMAP enabling constraint: every AWS command is documented + re-runnable so we
# can tear it down and recreate it). Idempotent: each resource is reused if it
# already exists.
#
# Path: own Dockerfile -> ECR -> AgentCore Runtime (not the starter-toolkit
# CodeBuild path). Requires AWS_PROFILE=sandbox.
set -euo pipefail
cd "$(dirname "$0")/.."

AWS_PROFILE="${AWS_PROFILE:-sandbox}"; export AWS_PROFILE
# Pin the region explicitly — do NOT inherit AWS_REGION/AWS_DEFAULT_REGION from the
# environment (this machine defaults to us-east-1, which silently put resources in
# the wrong region once). Export both so every aws call agrees.
REGION="us-west-2"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACCOUNT="414852377253"

ECR_REPO="trainer-agent"
ROLE_NAME="trainer-agent-agentcore-runtime"
RUNTIME_NAME="trainer_agent"   # pattern [a-zA-Z][a-zA-Z0-9_]{0,47} — underscores, no hyphens

ECR_URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
GIT_SHA="$(git rev-parse --short HEAD)"
IMAGE_TAG="${ECR_URI}:${GIT_SHA}"
IMAGE_LATEST="${ECR_URI}:latest"

echo "== account=$ACCOUNT region=$REGION profile=$AWS_PROFILE sha=$GIT_SHA"

# 1. ECR repository ----------------------------------------------------------
if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
  echo "== ECR repo $ECR_REPO exists"
else
  echo "== creating ECR repo $ECR_REPO"
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" \
    --image-scanning-configuration scanOnPush=true >/dev/null
fi

# 2. Build (arm64) + push ----------------------------------------------------
echo "== docker login to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo "== build $IMAGE_TAG (linux/arm64) and push"
docker build --platform linux/arm64 -t "$IMAGE_TAG" -t "$IMAGE_LATEST" .
docker push "$IMAGE_TAG"
docker push "$IMAGE_LATEST"

# 3. IAM execution role ------------------------------------------------------
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "== IAM role $ROLE_NAME exists"
else
  echo "== creating IAM role $ROLE_NAME"
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document file://scripts/aws/trust-policy.json \
    --description "Execution role for the Trainer Agent AgentCore runtime" >/dev/null
fi
echo "== putting inline permissions policy"
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name "trainer-agent-runtime-permissions" \
  --policy-document file://scripts/aws/permissions-policy.json
ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"
echo "== role arn: $ROLE_ARN"

# 4. Telemetry env — route prod traces through the shared Boswell collector ---
# Same Boswell Lambda cyndibot uses (see notes/telemetry.md). The Function URL is
# public; the ingest token is fetched from the Lambda's config at deploy time so
# it never lives in a committed file. Our traces land in the shared Honeycomb env
# (cynditaylor-com-bot), separated by service.name=trainer-agent.
BOSWELL_TRACES_URL="https://45exz5ki5veyvldhaojdynf3ty0pqnno.lambda-url.us-west-2.on.aws/v1/traces"
BOSWELL_TOKEN="$(aws lambda get-function-configuration --function-name boswell --region "$REGION" \
  --query 'Environment.Variables.INGEST_BEARER_TOKEN' --output text 2>/dev/null || echo '')"
ENV_ARGS=()
if [ -n "$BOSWELL_TOKEN" ] && [ "$BOSWELL_TOKEN" != "None" ]; then
  ENV_JSON="$(printf '{"OTEL_SERVICE_NAME":"trainer-agent","OTEL_EXPORTER_OTLP_PROTOCOL":"http/protobuf","OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":"%s","OTEL_EXPORTER_OTLP_HEADERS":"authorization=Bearer %s"}' \
    "$BOSWELL_TRACES_URL" "$BOSWELL_TOKEN")"
  ENV_ARGS=(--environment-variables "$ENV_JSON")
  echo "== telemetry: routing prod traces through Boswell ($BOSWELL_TRACES_URL)"
else
  echo "== WARN: could not fetch Boswell ingest token; deploying WITHOUT telemetry env"
fi

# 5. AgentCore runtime (create or update) ------------------------------------
EXISTING_ID="$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeId | [0]" \
  --output text 2>/dev/null || echo "None")"

if [ "$EXISTING_ID" = "None" ] || [ -z "$EXISTING_ID" ]; then
  echo "== creating AgentCore runtime $RUNTIME_NAME"
  # IAM role can take a few seconds to be assumable; retry create.
  for attempt in 1 2 3 4 5 6; do
    if aws bedrock-agentcore-control create-agent-runtime --region "$REGION" \
        --agent-runtime-name "$RUNTIME_NAME" \
        --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"${IMAGE_TAG}\"}}" \
        --role-arn "$ROLE_ARN" \
        --network-configuration '{"networkMode":"PUBLIC"}' \
        --protocol-configuration '{"serverProtocol":"HTTP"}' \
        --description "Trainer Agent — trains mtg-deck-shuffler; says hi (scaffold)" \
        ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} \
        >/tmp/agentcore-create.json 2>/tmp/agentcore-create.err; then
      cat /tmp/agentcore-create.json
      break
    fi
    echo "   create attempt $attempt failed (role may not be assumable yet); retrying in 10s"
    cat /tmp/agentcore-create.err
    sleep 10
  done
else
  echo "== AgentCore runtime $RUNTIME_NAME exists ($EXISTING_ID); updating to $IMAGE_TAG"
  aws bedrock-agentcore-control update-agent-runtime --region "$REGION" \
    --agent-runtime-id "$EXISTING_ID" \
    --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"${IMAGE_TAG}\"}}" \
    --role-arn "$ROLE_ARN" \
    --network-configuration '{"networkMode":"PUBLIC"}' \
    --protocol-configuration '{"serverProtocol":"HTTP"}' \
    ${ENV_ARGS[@]+"${ENV_ARGS[@]}"}
fi

# 6. Wait for READY ----------------------------------------------------------
RUNTIME_ID="$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeId | [0]" --output text)"
RUNTIME_ARN="$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeArn | [0]" --output text)"
echo "== runtime id: $RUNTIME_ID"
echo "== runtime arn: $RUNTIME_ARN"

echo "== waiting for runtime to be READY"
for _ in $(seq 1 30); do
  STATUS="$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
    --agent-runtime-id "$RUNTIME_ID" --query 'status' --output text 2>/dev/null || echo UNKNOWN)"
  echo "   status=$STATUS"
  [ "$STATUS" = "READY" ] && break
  case "$STATUS" in CREATE_FAILED|UPDATE_FAILED|DELETING) echo "runtime in $STATUS — aborting"; exit 1;; esac
  sleep 10
done

echo
echo "== DONE."
echo "ECR image:    $IMAGE_TAG"
echo "Role ARN:     $ROLE_ARN"
echo "Runtime ID:   $RUNTIME_ID"
echo "Runtime ARN:  $RUNTIME_ARN"
echo
echo "Smoke it:  RUNTIME_ARN=$RUNTIME_ARN ./scripts/cloud-smoke.sh"
