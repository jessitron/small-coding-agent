#!/usr/bin/env bash
# Build + publish the front-door STUB image to PRIVATE ECR (us-west-2), so
# mtg-deck-shuffler can pull and run it locally / in CI for integration testing.
# Idempotent infra record (see notes/infrastructure.md). Requires AWS_PROFILE=sandbox.
#
# To just run it locally without publishing, use scripts/stub-smoke.sh (builds +
# runs the container) — you don't need this script for local-only use.
set -euo pipefail
cd "$(dirname "$0")/.."

AWS_PROFILE="${AWS_PROFILE:-sandbox}"; export AWS_PROFILE
REGION="us-west-2"; export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACCOUNT="414852377253"

ECR_REPO="trainer-agent-frontdoor-stub"
ECR_URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
GIT_SHA="$(git rev-parse --short HEAD)"

echo "== account=$ACCOUNT region=$REGION repo=$ECR_REPO sha=$GIT_SHA"

# 1. Private ECR repository ----------------------------------------------------
if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
  echo "== ECR repo $ECR_REPO exists"
else
  echo "== creating private ECR repo $ECR_REPO"
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" \
    --image-scanning-configuration scanOnPush=true >/dev/null
fi

# 2. Login + build (multi-arch) + push -----------------------------------------
echo "== docker login to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo "== buildx build + push (linux/amd64,linux/arm64)"
docker buildx build --platform linux/amd64,linux/arm64 \
  -f frontdoor/Dockerfile.stub \
  -t "${ECR_URI}:${GIT_SHA}" -t "${ECR_URI}:latest" \
  --push frontdoor

echo
echo "== DONE. Stub image published (private):"
echo "   ${ECR_URI}:latest   (and :${GIT_SHA})"
echo
echo "Pull + run it (needs AWS access to this account):"
echo "   aws ecr get-login-password --profile sandbox --region us-west-2 \\"
echo "     | docker login --username AWS --password-stdin ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
echo "   docker run -p 8080:8080 -e STUB_BEARER=stub-token ${ECR_URI}:latest"
