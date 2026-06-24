# Decisions log

Running log of choices made with Jessitron, newest at the bottom.

## 2026-06-23 — initial design interview

- **Runtime**: Amazon Bedrock AgentCore Runtime.
- **Transport**: the _other_ app owns the chat UI and invokes AgentCore once per
  message (request/response; streaming not required — "not picky").
- **Stack**: Python + Strands Agents.
  - Rejected the **Claude Agent SDK**: its observability is poor — hooks fire at
    coarse boundaries and don't expose wtaf the agent is doing.
  - Chose Strands partly for **dogfooding**: it's the standard framework
    customers use, so building/instrumenting it ourselves mirrors their
    experience.
- **Observability bar**: must be able to see **raw LLM input/output on spans**
  (Strands does this via span events behind two env vars). System prompt can
  live in trace-correlated **logs** (trace_id/span_id) — that's acceptable too.
- **Target repo**: `jessitron/mtg-deck-shuffler`.
- **GitHub auth**: fine-grained **PAT** (kept in a secret, not the image).
- **Control flow**: one agent loop; may ask clarifying questions mid-coding.

## 2026-06-24 — transport & tracing clarifications

- **No websockets anywhere**: the entire path (backend → Lambda → agent) is
  synchronous HTTP request/response.
- **Conversation history lives in the MTG Deck Shuffler backend**, not in an
  agent-side store. Supersedes the earlier "conversation state in the session
  workspace dir" plan; the client resends history each invoke, so the agent
  doesn't need to persist it across a cold VM.
- **One trace, rooted in the backend**: the trace starts in the other app's
  backend and the agent's spans join it via propagated trace context (backend →
  Lambda → AgentCore) — the agent is *not* the trace root.
