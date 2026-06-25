# small-coding-agent

A single-purpose coding agent on Amazon Bedrock AgentCore Runtime. It chats with
a human via another app (synchronous HTTP request/response), implements a coding
task on `jessitron/mtg-deck-shuffler`, and opens a PR.

## Seamap

This repo's seamap — the chart and the tracking adapter — lives in `SEAMAP.md`. Orient, capture,
and log proactively; use `drop-buoy` to capture work without derailing. Work is tracked in Linear
(project `small-coding-agent`, team `jessitron`).

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
