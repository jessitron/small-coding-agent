#!/usr/bin/env bash
# Start the local Boswell OTel collector (see notes/telemetry.md).
#
# DEPENDENCY ON A NEIGHBORING REPO: Boswell is defined in the cyndibot repo
# (cynditaylor-com-bot). We do NOT duplicate it here — we start the exact same
# container (same collector/config.yaml, forwarding to the Honeycomb "local"
# env) via that repo's ./run. This is a deliberate, documented dependency.
#
# Override CYNDIBOT_REPO if the repo lives elsewhere on this machine.
set -euo pipefail

CYNDIBOT_REPO="${CYNDIBOT_REPO:-/Users/jessitron/code/jessitron/cynditaylor-com-bot}"

if [ ! -x "$CYNDIBOT_REPO/run" ]; then
  echo "FAIL: '$CYNDIBOT_REPO/run' not found or not executable." >&2
  echo "      Set CYNDIBOT_REPO to the path of the cynditaylor-com-bot repo." >&2
  exit 1
fi

echo "== starting Boswell local collector via $CYNDIBOT_REPO/run"
"$CYNDIBOT_REPO/run"
echo "== Trainer Agent exports to http://localhost:4318/v1/traces (OTEL_* in .env)"
echo "== collector logs: docker logs -f cynditaylor-collector"
