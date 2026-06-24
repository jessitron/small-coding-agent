# small-coding-agent — architecture

A single-purpose coding agent that runs on **Amazon Bedrock AgentCore Runtime**.
It chats with a human (over a websocket owned by *another* app), figures out a
coding task, implements it on a branch of **one** repo
(`jessitron/mtg-deck-shuffler`), opens a PR, and sends the PR link back over chat.

## Outer shape

```
chat UI ──ws──> other app ──InvokeAgentRuntime(runtimeSessionId, {message})──> AgentCore Runtime
                   ▲                                                              │
                   └──────────── {reply, status, pr_url?} ◀──────────────────────┘
```

- The **other app** owns the websocket to the user and the chat UI. It calls
  AgentCore's invoke endpoint **once per user message**, passing a stable
  `runtimeSessionId`.
- Our agent is request/response (no streaming required). AgentCore keeps the
  session's microVM warm and gives it session affinity, so disk + memory persist
  across invokes within a session.

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
{ "reply": "text to show in chat", "status": "chatting|coding|asking|done|error", "pr_url": "https://github.com/.../pull/123" }
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
- One trace per invoke; tie the trace to the AgentCore `session_id`.

## Open questions / not yet decided

- Exact deploy mechanism (starter toolkit CodeBuild vs. own Dockerfile).
- Whether to adopt AgentCore Memory now or after v1.
- How the other app authenticates to InvokeAgentRuntime (IAM).
