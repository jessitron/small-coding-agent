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

> **Status:** the deployed agent is still the "hi" stub (Mountain 1). Everything
> in this section from *Session lifecycle* onward is the **Mountain 2** design —
> the real loop. See `notes/decisions.md` (2026-06-25) for the decisions behind it.

### Session lifecycle (what happens per session vs. per turn)

**On the first invoke of a session:**

1. **Clone the target repo.** `git clone jessitron/mtg-deck-shuffler` into the
   session workspace dir (custom span; failure → `status: error`).
2. **Load the brief.** Read **`trainer-agent/instructions.md`** from the clone —
   the app's standing instructions for what it wants of the agent. This is *not*
   in this repo: the app owns "what is wanted of us," reviewed on the app's own
   schedule. Missing/empty → honest `status: error`. Helper scripts the
   instructions reference live alongside it (`trainer-agent/cards.sh`, etc.) and
   the agent runs them on demand via its `shell` tool.

**On every invoke (including the first):** the agent reasons over three inputs —
(1) the repo instructions, (2) the user's `message`, (3) the current **game
state** (the `state` field, below) — then acts with its coding tools and replies.

**The session protocol — `seq` makes context-loss honest.** AgentCore keeps the
microVM warm with session affinity, so turn 2+ lands in the same VM with the
clone and conversation intact. But VMs time out. Each request carries `seq`, a
1-based count of user messages in the session; the agent persists how many turns
it has handled and **expects `seq == turns_seen + 1`**. A mismatch means the VM is
fresh / the session expired and **the game state is gone** — the agent can't
safely continue, so it returns `status: error` with a `reply` telling the user to
start a **new conversation** (new `session_id`) and marks the span
(`agent.context_lost=true`, `agent.seq_expected`, `agent.seq_received`). This is
the concrete mechanism behind the SEAMAP "honest about session loss" promise.

### Invoke contract (agent ⇄ other app)

> Mountain 1 (deployed) request is just `{ "message": "..." }`. The fields below
> (`seq`, `state`) are the **v2.0 contract** that lands with Mountain 2; they
> bump `INTERFACE.md` to 2.0 *when they ship* (see the version note at the end of
> this doc). The front door passes `seq`/`state` straight through in the payload;
> only the agent has the conversation state to enforce the `seq` check.

Request payload (from the other app):

```json
{
  "message": "user's chat message",
  "seq": 1,
  "state": { "...app-defined game state..." }
}
```

- **`message`** — the user's text for this turn.
- **`seq`** — 1-based count of user messages in this session (1 on the first
  message). The agent checks it against turns it has handled; a mismatch is a
  context-loss `error` (see *Session lifecycle*).
- **`state`** — the current **game state**, an **opaque app-defined** object. The
  wire contract doesn't fix its shape; `trainer-agent/instructions.md` in the
  target repo defines what's in it and how to use it. Keeps the contract stable
  while the meaning lives with the app.

`runtimeSessionId` is carried by AgentCore, not in the body.

Response:

```json
{
  "reply": "text to show in chat",
  "status": "chatting|coding|asking|done|error",
  "pr_url": "https://github.com/.../pull/123"
}
```

`pr_url` is present only once the PR exists. A context-loss mismatch returns
`status: error` with a `reply` that tells the user to start a new conversation.

### State

State is keyed by `session_id` and lives **server-side**:

- **Conversation**: a Strands session/conversation store persisted to the
  session's workspace dir (so the other app need not resend history).
- **Turn counter**: `turns_seen` for this session, persisted alongside the
  conversation — what the `seq` check compares against.
- **Working tree**: the repo is `git clone`d once per session into a workspace
  dir and reused on later invokes; `trainer-agent/instructions.md` is read from
  it on the first invoke.

Upgrade path: move conversation to **AgentCore Memory** (blessed path; also good
dogfooding of the customer experience).

### Tools

The agent gets the usual coding tools plus two custom tools, one for each
direction of collaboration. *This repo documents **how to use the tools**; the
target repo's `trainer-agent/instructions.md` documents **what's wanted of us**.*

- Strands built-ins: `file_read`, `editor`, `shell` — `shell` scoped to the
  workspace directory (also how the agent runs the repo's helper scripts).
- Custom `open_pr`: wraps `git push` + `gh pr create`, returns the PR URL, stamps
  `pr.url` on the current span. (agent → app: here's the change.)
- Custom `request_app_change`: files a **GitHub issue on
  `jessitron/mtg-deck-shuffler`** (`gh issue create`) when the agent needs its
  *inputs* improved — e.g. "include the deck's strategy in `state`." Reuses the
  GitHub PAT already present for PRs (no new secret/infra). (agent → app: here's
  what I need to do better.) This is the reverse of `INTERFACE.md`'s collaboration
  channel, where the app files **Linear** requests against this repo.

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

## Interface version

When the Mountain 2 loop lands, the wire contract gains required `seq` + `state`
and a new consumer obligation (`trainer-agent/instructions.md` must exist) — a
breaking change, so `INTERFACE.md` goes **1.0 → 2.0**. The spec and the running
service bump in lockstep (the 2026-06-24 versioning decision), so `INTERFACE.md`
is **not** edited ahead of the code; this doc holds the v2.0 design until it ships.

## Open questions / not yet decided

- Exact deploy mechanism (starter toolkit CodeBuild vs. own Dockerfile). JESS: I like Dockerfiles
- Whether to adopt AgentCore Memory now or after v1. JESS: after v1
- ~~Where the agent's instructions live & how it learns what the app wants.~~
  **RESOLVED 2026-06-25**: `trainer-agent/instructions.md` in the target repo;
  the app owns the brief. See `notes/decisions.md`.
- ~~How the agent requests changes to its own inputs.~~ **RESOLVED 2026-06-25**:
  a `request_app_change` tool files a GitHub issue on the app repo.
- ~~How session/context loss is surfaced.~~ **RESOLVED 2026-06-25**: the `seq`
  protocol — mismatch → `status: error` + marked span.
- ~~How the other app authenticates to InvokeAgentRuntime (IAM).~~ **RESOLVED
  2026-06-24**: a front-door Lambda behind a **public Function URL** validates a
  shared **bearer** secret, then proxies to `InvokeAgentRuntime` via SigV4. Not
  AgentCore's native authorizer (wants OIDC/JWT, not a static secret), not API
  Gateway (29s timeout). See `notes/decisions.md` + `notes/infrastructure.md`.
