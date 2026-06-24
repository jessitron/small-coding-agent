# Done log

Completed landings, newest at the bottom. (In-repo tracking; see `SEAMAP.md` §Tracking.)

## 2026-06-24

- **Scaffold the Python project + minimal "hi" agent** ← mountain: Deployed & wired up
  - uv-managed project (`pyproject.toml`, package `src/agent`), deps
    `bedrock-agentcore` + `strands-agents` (strands 1.44.0).
  - `src/agent/main.py`: `BedrockAgentCoreApp` + `@app.entrypoint invoke()` that
    follows our invoke contract (`message` in → `{reply, status}` out) and
    replies "hi". Console script: `uv run agent`.
  - Verified locally: server on :8080, `GET /ping` healthy, `POST /invocations`
    with `{"message": "hello"}` → `{"reply": "hi", "status": "chatting"}`.

- **Dockerfile + local-testing harness** ← mountain: Deployed & wired up
  - `Dockerfile`: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, two-stage
    `uv sync` (deps layer cached separately from app), serves :8080. Built
    `linux/arm64` (AgentCore's required arch; native on Apple Silicon). Platform
    is passed at build time, not hardcoded in `FROM`. `.dockerignore` keeps
    secrets/notes/workspace out of the image.
  - `scripts/` testing harness, mapped to `notes/local-testing-advice.md`:
    - `smoke-local.sh` — Layer 2: run in-process, assert `/ping` + `/invocations`.
    - `smoke-container.sh` — Layer 3: build arm64, `docker run`, assert same
      surface. Mounts `~/.aws` read-only (pattern ready for Bedrock/Secrets;
      not exercised by "hi" yet).
  - Verified: image is `arm64/linux`; both smoke scripts PASS (reply "hi").

- **Deploy to Bedrock AgentCore Runtime** ← mountain: Deployed & wired up ✅ Mountain 1 reached
  - `scripts/deploy.sh` (idempotent, source of truth): build arm64 → push to ECR
    → ensure IAM execution role (`scripts/aws/*.json`) → create AgentCore runtime
    (`networkMode=PUBLIC`, `serverProtocol=HTTP`) → wait READY.
  - `scripts/cloud-smoke.sh` (Layer 5): `invoke-agent-runtime` end-to-end.
  - Live in **us-west-2**: runtime `trainer_agent-VyiY9TFdtC`. Cloud smoke PASS —
    `{"message":"..."}` → `{"reply":"hi"}`. All resources in `notes/infrastructure.md`.
  - **Gotcha:** the shell's `AWS_DEFAULT_REGION=us-east-1` overrode the profile's
    us-west-2 on the first run, creating resources in the wrong region and failing
    role validation (trust `SourceArn` pinned to us-west-2). Fix: scripts pin
    `export AWS_REGION=us-west-2` rather than inheriting it.
