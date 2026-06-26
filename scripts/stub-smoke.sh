#!/usr/bin/env bash
# Build + run the front-door STUB image locally and assert it enforces the same
# contract as the real front door (shared frontdoor/contract.py) and returns the
# canned statuses. This is the test the mtg-deck-shuffler app's CI would lean on.
# Fails loud.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-trainer-agent-frontdoor-stub:local}"
PORT="${PORT:-8088}"
BEARER="stub-token"
NAME="frontdoor-stub-smoke"
SID="stub-smoke-session-0001-needs-to-be-33-plus-chars"

echo "== build $IMAGE"
docker build -q -f frontdoor/Dockerfile.stub -t "$IMAGE" frontdoor >/dev/null

echo "== run on :$PORT"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --rm --name "$NAME" -p "$PORT:8080" -e STUB_BEARER="$BEARER" "$IMAGE" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

URL="http://localhost:$PORT/"
for _ in $(seq 1 20); do curl -sf "http://localhost:$PORT/ping" >/dev/null 2>&1 && break; sleep 0.3; done

fail() { echo "FAIL: $1"; exit 1; }
# helper: POST, echo "<http_code> <body>"
post() { curl -s -o /tmp/stub-body -w '%{http_code}' "$@"; echo " $(cat /tmp/stub-body)"; }

echo "== valid request -> 200 chatting + version header"
hdrs="$(curl -s -D - -o /tmp/stub-body -XPOST "$URL" \
  -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d "{\"message\":\"hello\",\"session_id\":\"$SID\"}")"
echo "$hdrs" | grep -qi "x-trainer-agent-interface-version" || fail "missing version header"
grep -q '"status": "chatting"' /tmp/stub-body || fail "expected chatting; got $(cat /tmp/stub-body)"

echo "== bad bearer -> 401"
code="$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$URL" \
  -H "Authorization: Bearer wrong" -H 'Content-Type: application/json' \
  -d "{\"message\":\"hi\",\"session_id\":\"$SID\"}")"
[ "$code" = "401" ] || fail "expected 401, got $code"

echo "== short session_id -> 400"
code="$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$URL" \
  -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d '{"message":"hi","session_id":"too-short"}')"
[ "$code" = "400" ] || fail "expected 400, got $code"

echo "== invalid JSON -> 400"
code="$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$URL" \
  -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  --data-raw 'not json')"
[ "$code" = "400" ] || fail "expected 400, got $code"

echo "== message 'open the PR' -> done + pr_url"
curl -s -XPOST "$URL" -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d "{\"message\":\"please open the PR\",\"session_id\":\"$SID\"}" >/tmp/stub-body
grep -q '"status": "done"' /tmp/stub-body || fail "expected done; got $(cat /tmp/stub-body)"
grep -q '"pr_url"' /tmp/stub-body || fail "expected pr_url; got $(cat /tmp/stub-body)"

# Lost-session simulation (v2.0 seq): a fresh session expects seq 1; a gap is a
# lost session -> error, exactly like the real agent. Use a fresh session_id so
# the counter starts at 0.
SID2="stub-smoke-seq-session-0002-needs-to-be-33-plus-chars"
echo "== seq=1 on a fresh session -> 200 chatting"
curl -s -XPOST "$URL" -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d "{\"message\":\"hello\",\"session_id\":\"$SID2\",\"seq\":1}" >/tmp/stub-body
grep -q '"status": "chatting"' /tmp/stub-body || fail "expected chatting; got $(cat /tmp/stub-body)"

echo "== seq=3 (gap) -> error, lost context"
curl -s -XPOST "$URL" -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d "{\"message\":\"hello\",\"session_id\":\"$SID2\",\"seq\":3}" >/tmp/stub-body
grep -q '"status": "error"' /tmp/stub-body || fail "expected error; got $(cat /tmp/stub-body)"
grep -qi 'lost the context' /tmp/stub-body || fail "expected lost-context reply; got $(cat /tmp/stub-body)"

echo "== seq=2 (correct next, counter didn't advance on the error) -> 200 chatting"
curl -s -XPOST "$URL" -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d "{\"message\":\"hello\",\"session_id\":\"$SID2\",\"seq\":2}" >/tmp/stub-body
grep -q '"status": "chatting"' /tmp/stub-body || fail "expected chatting; got $(cat /tmp/stub-body)"

echo "PASS"
