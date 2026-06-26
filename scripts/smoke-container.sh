#!/usr/bin/env bash
# Layer 3 smoke (see notes/local-testing-advice.md): build the arm64 image the
# way AgentCore needs it, run it locally, and verify the same HTTP surface
# (/ping, /invocations). Catches packaging bugs — entrypoint, arch, env,
# request/response shape — in one `docker run` instead of a deploy. Fails loud.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-trainer-agent:local}"
NAME="${NAME:-trainer-agent-smoke}"
PORT="${PORT:-8080}"

echo "==> building $IMAGE (linux/arm64)"
docker build --platform linux/arm64 -t "$IMAGE" .

docker rm -f "$NAME" >/dev/null 2>&1 || true

# Mount AWS creds read-only so this same pattern works once the agent needs
# Bedrock / Secrets Manager. The "hi" scaffold does not exercise them yet.
echo "==> running container $NAME"
docker run -d --name "$NAME" --platform linux/arm64 \
  -p "$PORT:8080" \
  -v "$HOME/.aws:/root/.aws:ro" \
  -e AWS_PROFILE="${AWS_PROFILE:-sandbox}" \
  -e AWS_REGION="${AWS_REGION:-us-west-2}" \
  "$IMAGE" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 30); do
  curl -sf "http://localhost:$PORT/ping" >/dev/null 2>&1 && break
  sleep 0.5
done

echo "==> GET /ping"
curl -fsS "http://localhost:$PORT/ping"; echo

# No session_id -> honest status:error; this checks the packaged HTTP surface
# (entrypoint, arch, imports incl. strands + git, contract-shaped JSON) without
# needing Bedrock. The real model loop is verified by the cloud smoke.
echo "==> POST /invocations  {\"message\":\"hello\"}  (no session_id -> honest error)"
reply=$(curl -fsS -XPOST "http://localhost:$PORT/invocations" \
  -H 'Content-Type: application/json' -d '{"message":"hello"}')
echo "$reply"

if echo "$reply" | grep -q '"status"' && echo "$reply" | grep -q '"reply"'; then
  echo "PASS"
else
  echo "FAIL: response not contract-shaped {reply,status}"; docker logs "$NAME"; exit 1
fi
