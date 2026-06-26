# small-coding-agent

A single-purpose coding agent on Amazon Bedrock AgentCore Runtime. It chats with
a human via another app (synchronous HTTP request/response), implements a coding
task on `jessitron/mtg-deck-shuffler`, and opens a PR.

## Seamap

This repo's seamap — the chart and the tracking adapter — lives in `SEAMAP.md`. Orient, capture,
and log proactively; use `drop-buoy` to capture work without derailing. Work is tracked in Linear
(project `small-coding-agent`, team `jessitron`).

### Filing tickets to the app (`mtg-deck-shuffler`)

We're free to file Linear issues for the app this agent serves. Coordinates (Linear,
team `jessitron`, same workspace):
- **project:** `MTG Deck Shuffler` (id `5046fea4-bc3c-4065-9234-3f70ca7fe0c6`)
- **milestone:** attach to **`The Trainer`** (id `c35f234d-2e03-48e3-80a7-4a349a90f9ba`) — the
  active milestone for the chat→PR loop.
- **provenance:** end the issue description with `(- claude from small-coding-agent)`.

So: `save_issue team:"jessitron", project:"MTG Deck Shuffler", milestone:"The Trainer",
title:"…", description:"…\n\n(- claude from small-coding-agent)"`. Search for a near-duplicate
first; update it instead of filing a second.

## Notes for future me
- `INTERFACE.md` (repo root) — **the canonical interface spec**: the single file
  consumers copy into their repo. Defines three interfaces — conceptual (what the
  agent is for), collaboration (request changes via Linear), and technical (the
  HTTP contract). Source of truth; keep it and the running service versioned in
  lockstep. Contract changes come in as Linear requests, not local edits.
- `design/architecture.md` — the system design and the invoke contract.
- `notes/decisions.md` — running log of decisions and *why* (read this first).
- `notes/infrastructure.md` — everything we touch in AWS (profile `jessitron-sandbox` =
  `AWS_PROFILE=sandbox` on this computer; account `414852377253`, `us-west-2`).
- `notes/done.md` — completed-landings log.

## Running locally
`uv run agent` starts the AgentCore server on :8080. Invoke with
`curl -XPOST localhost:8080/invocations -d '{"message":"hi"}'`; health at `/ping`.

## Local testing (push bugs down — see `notes/local-testing-advice.md`)
Test at the lowest layer that reproduces a bug. Named, executable scripts:
- `scripts/smoke-local.sh` — Layer 2: in-process, assert `/ping` + `/invocations`.
- `scripts/smoke-container.sh` — Layer 3: build the arm64 image, run it, assert.
The image must be `linux/arm64` (AgentCore's arch); always pass `--platform linux/arm64`.

## Deploying (AWS)
`scripts/deploy.sh` builds+pushes to ECR and creates/updates the AgentCore
runtime (idempotent); `scripts/cloud-smoke.sh` invokes the deployed runtime.
**Region is pinned to us-west-2 in the scripts** — do NOT inherit the shell's
`AWS_DEFAULT_REGION` (this machine is us-east-1). All AWS resources are recorded
in `notes/infrastructure.md`.

**Deploy is part of the task — don't ask, just ship (pre-authorized).** The
running service IS the deliverable; an undeployed change is inert. So a change
isn't done until it's live:
- **stub change** (`frontdoor/`) → commit → `AWS_PROFILE=sandbox scripts/publish-stub.sh`
  (sandbox ECR, so mtg-deck-shuffler's next pull gets it).
- **agent change** (`src/agent/`, deps, Dockerfile) → commit → `scripts/deploy.sh`
  → `scripts/cloud-smoke.sh` to confirm the deployed runtime answers.
Run the relevant smoke (`stub-smoke.sh` / `cloud-smoke.sh`) after, and report the
landed result. Both deploys are pre-authorized — treat them like commits, not
like outward-facing actions to confirm first. (Publishing/deploying needs network
the sandbox lacks — run those commands with the sandbox disabled.)

## The test fake / stub (`frontdoor/stub.py`)
The "test fake" mtg-deck-shuffler runs as a sidecar. It enforces the real request
contract (`frontdoor/contract.py`, shared) but returns canned replies — no AWS, no
real agent, no PR. Canned `status` is driven by the message text (see the module
docstring). **It IS instrumented with OpenTelemetry** (deps: `opentelemetry-sdk`,
`opentelemetry-exporter-otlp-proto-http`, in `frontdoor/requirements-stub.txt`).
Each request emits a `frontdoor-stub.invocation` span carrying **`stub.faking=true`**
(so it's unmistakable in Honeycomb that this is the fake), plus `agent.message`,
`agent.status`, `agent.reply`, `pr.url`, and a "faking the trainer agent…" span event.
It joins the caller's W3C trace from the request headers, mirroring the real front
door. Export uses standard `OTEL_*` env vars; **no endpoint configured → no-op tracer**,
so it still runs (and `scripts/stub-smoke.sh` passes) without a collector. Service
name defaults to `trainer-agent-frontdoor-stub` (→ its own Honeycomb dataset).
Verify span emission against the local collector with `scripts/stub-trace-smoke.sh`.

## Telemetry (see `notes/telemetry.md`)
Traces go through **Boswell** (the OTel collector in the neighboring cyndibot
repo) to Honeycomb **team `modernity`** — local→env `local`, prod→env
`cynditaylor-com-bot` (shared with cyndibot; filter `service.name=trainer-agent`).
**Verify traces in team `modernity`, not the Demo team the Honeycomb MCP shows.**
`scripts/start-collector.sh` starts the local collector (depends on the cyndibot repo).

## Conventions
- Stack: Python + Strands Agents + `bedrock-agentcore`. Observability is
  first-class: standard OTel to Honeycomb, raw LLM I/O captured on spans.
- Keep durable notes in `notes/` (in git), not in memories — Jessitron works
  across multiple computers.
