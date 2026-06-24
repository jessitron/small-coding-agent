# small-coding-agent

A single-purpose coding agent on Amazon Bedrock AgentCore Runtime. It chats with
a human via another app (synchronous HTTP request/response), implements a coding
task on `jessitron/mtg-deck-shuffler`, and opens a PR.

## Seamap

This repo's seamap — the chart and the tracking adapter — lives in `SEAMAP.md`. Orient, capture,
and log proactively; use `drop-buoy` to capture work without derailing. Open work is in `TODO.md`.

## Notes for future me
- `design/architecture.md` — the system design and the invoke contract.
- `notes/decisions.md` — running log of decisions and *why* (read this first).
- `notes/infrastructure.md` — everything we touch in AWS (profile `jessitron-sandbox` =
  `AWS_PROFILE=sandbox` on this computer; account `414852377253`, `us-west-2`).
- `notes/done.md` — completed-landings log.

## Running locally
`uv run agent` starts the AgentCore server on :8080. Invoke with
`curl -XPOST localhost:8080/invocations -d '{"message":"hi"}'`; health at `/ping`.

## Conventions
- Stack: Python + Strands Agents + `bedrock-agentcore`. Observability is
  first-class: standard OTel to Honeycomb, raw LLM I/O captured on spans.
- Keep durable notes in `notes/` (in git), not in memories — Jessitron works
  across multiple computers.
