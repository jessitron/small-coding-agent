# small-coding-agent — architecture

A single-purpose coding agent that runs on **Amazon Bedrock AgentCore Runtime**.
It chats with a human (through _another_ app, over synchronous HTTP), figures out
a coding task, implements it on a branch of **one** repo
(`jessitron/mtg-deck-shuffler`), opens a PR, and sends the PR link back over chat.

## Outer shape

```
chat UI ──http──> other app ──InvokeAgentRuntime(runtimeSessionId, {message})──> AgentCore Runtime
                     ▲                                                              │
                     └──────────── {reply, status, pr_url?} ◀──────────────────────┘
```

- The **other app** owns the chat UI. It calls AgentCore's invoke endpoint
  **once per user message** (synchronous HTTP request/response), passing a stable
  `runtimeSessionId`.
- The whole path — backend → Lambda → agent — is synchronous and joins **one
  trace** that starts in the other app's backend (see Observability). No
  streaming required. AgentCore keeps the session's microVM warm and gives it
  session affinity, so disk + memory persist across invokes within a session.
- Sessions are expected to be short-lived. It is acceptable to fail if AgentCore's VM times out between chat messages, although let's make it clear to the user and telemetry when that happens.

## The agent

- **Python + [Strands Agents](https://strandsagents.com/)**, deployed with the
  `bedrock-agentcore` SDK (`BedrockAgentCoreApp` + `@app.entrypoint`).
- **One agent loop.** No separate chat/code modes. The agent gathers
  requirements, confirms, implements on a branch, opens a PR. If it needs
  information at any point — including mid-coding — it returns a question instead
  of finishing; the next invoke resumes with the working tree intact.

### Invoke contract (agent ⇄ other app)

Request payload (from the other app):

```json
{ "message": "user's chat message" }
```

`runtimeSessionId` is carried by AgentCore, not in the body.

Response:

```json
{
  "reply": "text to show in chat",
  "status": "chatting|coding|asking|done|error",
  "pr_url": "https://github.com/.../pull/123"
}
```

`pr_url` is present only once the PR exists.

### State

State is keyed by `session_id` and lives **server-side**:

- **Conversation**: a Strands session/conversation store persisted to the
  session's workspace dir (so the other app need not resend history).
- **Working tree**: the repo is `git clone`d once per session into a workspace
  dir and reused on later invokes.

Upgrade path: move conversation to **AgentCore Memory** (blessed path; also good
dogfooding of the customer experience).

### Tools

- Strands built-ins: `file_read`, `editor`, `shell` — `shell` scoped to the
  workspace directory.
- Custom `open_pr` tool: wraps `git push` + `gh pr create`, returns the PR URL,
  and stamps `pr.url` on the current span.

### GitHub auth

- Fine-grained **PAT**, stored in **AWS Secrets Manager**, fetched at runtime.
  Never baked into the image. Locally: a gitignored `.env`.
- Target repo: `jessitron/mtg-deck-shuffler`.

## Observability (first-class)

This agent exists partly so we live what Honeycomb customers live: a standard
framework (Strands) emitting standard OTel to Honeycomb.

- Strands `StrandsTelemetry` → OTLP → Honeycomb. Spans for the event loop, each
  model invocation (model id, token usage, stop reason), and each tool call
  (name, input, output, duration).
- **Raw LLM I/O on spans** via span events
  (`gen_ai.user.message` / `gen_ai.assistant.message` / `gen_ai.choice`), enabled
  with `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` and
  `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`.
- **System prompt**: not on the model span by default
  (strands-agents/sdk-python#822). We capture it via a trace-correlated log
  record (logs carry `trace_id`/`span_id`), so it's reachable from the trace.
- Custom spans for the `git clone` and `open_pr` steps.
- One trace per invoke, and it's **not** rooted at the agent: the trace starts
  in the other app's backend and the agent's spans join it via propagated trace
  context (app → front-door Lambda → AgentCore). Tie the trace to the AgentCore
  `session_id`. **Propagation mechanism** (see `notes/telemetry.md`): app→Lambda
  is W3C `traceparent` over HTTP; Lambda→agent rides in the invoke **payload**
  (`traceparent`/`tracestate`), because AgentCore forwards only `baggage` to the
  container, not the `InvokeAgentRuntime` `traceParent` param.

## Open questions / not yet decided

- Exact deploy mechanism (starter toolkit CodeBuild vs. own Dockerfile). JESS: I like Dockerfiles
- Whether to adopt AgentCore Memory now or after v1. JESS: after v1
- ~~How the other app authenticates to InvokeAgentRuntime (IAM).~~ **RESOLVED
  2026-06-24**: a front-door Lambda behind a **public Function URL** validates a
  shared **bearer** secret, then proxies to `InvokeAgentRuntime` via SigV4. Not
  AgentCore's native authorizer (wants OIDC/JWT, not a static secret), not API
  Gateway (29s timeout). See `notes/decisions.md` + `notes/infrastructure.md`.
