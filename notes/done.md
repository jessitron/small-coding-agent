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
