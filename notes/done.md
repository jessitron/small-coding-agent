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

- **Telemetry via Boswell — local wired** ← Safe Harbor (see the agent in Honeycomb)
  - Reuse cyndibot's **Boswell** collector instead of our own (decision below).
    `src/agent/observability.py` emits an `agent.invocation` span per invoke →
    `BatchSpanProcessor` → OTLP. `service.name=trainer-agent`.
  - Local: `scripts/start-collector.sh` (delegates to cyndibot's `./run`); `.env`
    points OTLP at `localhost:4318`. Verified: the span reaches the collector.
  - Prod wiring **ready but not deployed** in `deploy.sh` (Boswell Lambda URL +
    token fetched at deploy time). Held until the Honeycomb ingest incident clears.
  - **Not yet confirmed in Honeycomb** (team `modernity`, env `local`): ingest
    incident + no `modernity` MCP in-session. See `notes/telemetry.md`.

- **Telemetry — prod deployed + egress confirmed** ← Safe Harbor (after incident recovered)
  - Local: flush dropped 3.3s→0.2s post-recovery, clean egress → Honeycomb accepts it.
  - Prod: deployed runtime rev 2 with OTEL_* env; cloud-smoke span was received,
    transformed, and exported by the Boswell Lambda with no errors (CloudWatch).
  - Both pipes proven end-to-end. Only the eyes-on-trace in the Honeycomb UI
    (team `modernity`) remains — a manual look, no `modernity` MCP in-session.

- **Eyeball a trace in Honeycomb** ← Safe Harbor ✅ Safe Harbor reached
  - Confirmed via the `honeycomb-modernity` MCP: `agent.invocation` span in both
    envs (`local` + `cynditaylor-com-bot`), `service.name=trainer-agent`,
    `agent.status=chatting`, `collector.boswell=washere` (proves the Boswell path).

- **Authed web front door — Lambda + public bearer Function URL** ← mountain: Deployed & wired up
  - `frontdoor/handler.py`: thin arm64/128MB Lambda behind a **public Function URL**.
    Validates a shared **bearer** (Secrets Manager, constant-time compare), then
    proxies to `InvokeAgentRuntime` via SigV4, returning the agent's reply. Telemetry
    via `SimpleSpanProcessor` (freeze-proof, no background thread); stamps the
    hard-coded Lambda cost *rate* on `frontdoor.invoke` (dollars derived in Honeycomb
    as rate × duration). `service.name=trainer-agent-frontdoor`.
  - `scripts/deploy-frontdoor.sh` (idempotent infra record): secret → IAM role →
    arm64 zip → Lambda → Function URL. `scripts/frontdoor-smoke.sh` (bearer happy
    path + 401 negative). All resources in `notes/infrastructure.md`.
  - **End-to-end trace propagation proven**: `scripts/propagation-test.sh` (a test
    client that starts a root span and calls the front door with `traceparent`
    injected) produced **one trace spanning three services** in Honeycomb —
    `trainer-agent-test-client → trainer-agent-frontdoor → trainer-agent`
    (trace `c6eb1ec7…`).
  - **Two gotchas, both fixed (see infrastructure.md):** (1) a public `AuthType=NONE`
    Function URL needs a *second* permission (`lambda:InvokeFunction` via
    `--invoked-via-function-url`) or it 403s silently with no logs; (2) AgentCore
    forwards only the `baggage` header to the container — NOT the `traceParent`
    param — so trace context to the agent rides in the **payload**, not headers.

## 2026-06-25

- **GitHub auth for the agent runtime (JES-106)** ← mountain: First PR from a script
  - Fine-grained PAT in Secrets Manager (`trainer-agent/github-pat`); execution
    role granted `GetSecretValue` (`GitHubPATSecretRead`, scoped to the secret).
  - `src/agent/github_auth.py`: fetch PAT (env-first → Secrets Manager) and wire
    git via a credential helper that reads `$GITHUB_TOKEN` — token never on disk,
    in logs, or on a span; `gh` reads `$GH_TOKEN`. `.env` is the local fallback.
  - `scripts/github-auth-smoke.py` (forces the Secrets Manager path, asserts the
    token isn't written to git config) — verified PASS. boto3 → direct dep.
  - Carved out: `git`/`gh` *binaries* install with their first consumers (clone =
    JES-107, `gh` = JES-110/111). The auth code is done and shared by all three.
