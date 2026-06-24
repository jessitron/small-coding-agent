#!/usr/bin/env bash
# Layer 2 smoke (see notes/local-testing-advice.md): run the agent in-process
# (no container) and verify the AgentCore HTTP surface — /ping and /invocations.
# Fast, no image build. Fails loud.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8080}"

echo "==> starting agent in-process (uv run agent) on :$PORT"
uv run agent &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 20); do
  curl -sf "http://localhost:$PORT/ping" >/dev/null 2>&1 && break
  sleep 0.5
done

echo "==> GET /ping"
curl -fsS "http://localhost:$PORT/ping"; echo

echo "==> POST /invocations  {\"message\":\"hello\"}"
reply=$(curl -fsS -XPOST "http://localhost:$PORT/invocations" \
  -H 'Content-Type: application/json' -d '{"message":"hello"}')
echo "$reply"

if echo "$reply" | grep -q '"reply": "hi"'; then
  echo "PASS"
else
  echo "FAIL: unexpected reply"; exit 1
fi
