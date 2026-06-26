#!/usr/bin/env bash
# Run the front-door STUB locally against the local Boswell collector and send one
# request, so we can confirm the stub emits its own OTel span (service.name
# trainer-agent-frontdoor-stub, attribute stub.faking=true) into Honeycomb team
# modernity, env `local`. Graceful shutdown (SIGINT) so BatchSpanProcessor flushes.
#
# Prereq: the local collector is running (scripts/start-collector.sh) and .env has
# the OTEL_* export config.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env safely — values can contain spaces (e.g. "Bearer <token>"), so we
# can't `source` it. Export each non-comment KEY=VALUE with the value preserved.
while IFS='=' read -r key val; do
  [ -z "$key" ] && continue
  case "$key" in \#*) continue ;; esac
  export "$key=$val"
done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env)
# Distinguish the stub's spans from the real agent's in the shared env.
export OTEL_SERVICE_NAME="trainer-agent-frontdoor-stub"
export STUB_BEARER="stub-token"
export PORT="8089"
SID="stub-trace-smoke-session-0001-needs-33-plus-chars"

echo "== start stub on :$PORT (exporting to $OTEL_EXPORTER_OTLP_TRACES_ENDPOINT)"
( cd frontdoor && exec uv run --with opentelemetry-sdk --with opentelemetry-exporter-otlp-proto-http \
    python3 stub.py ) &
STUB_PID=$!
trap 'kill -INT "$STUB_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do curl -sf "http://localhost:$PORT/ping" >/dev/null 2>&1 && break; sleep 0.25; done

echo "== send a 'please open the PR' request (expect status done)"
curl -s -XPOST "http://localhost:$PORT/" \
  -H "Authorization: Bearer $STUB_BEARER" -H 'Content-Type: application/json' \
  -d "{\"message\":\"please open the PR\",\"session_id\":\"$SID\"}"
echo

echo "== shutting down (flush spans)"
kill -INT "$STUB_PID" 2>/dev/null || true
wait "$STUB_PID" 2>/dev/null || true
trap - EXIT
echo "== done. Look for service.name=trainer-agent-frontdoor-stub in Honeycomb (team modernity, env local)."
