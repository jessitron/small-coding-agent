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
