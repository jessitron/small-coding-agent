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
- **One trace, rooted in the backend**: the trace starts in the other app's
  backend and the agent's spans join it via propagated trace context (backend →
  Lambda → AgentCore) — the agent is *not* the trace root.

## 2026-06-24 — telemetry collector: reuse cyndibot's Boswell

- **Reuse Boswell, don't run our own collector.** Boswell is the OTel collector
  in the neighboring cyndibot repo. Rejected running a collector *inside* the
  AgentCore microVM because of the freeze problem (the in-VM collector's buffer
  freezes between invokes). Reuse over extract: cheaper, and cyndibot already
  operates it.
  - **local** → Boswell collector container (`localhost:4318`), started from here
    via cyndibot's `./run` (documented cross-repo dependency).
  - **prod** → the Boswell **Lambda**, same as cyndibot.
- **Accepted caveat**: prod traces land in cyndibot's Honeycomb env
  (`cynditaylor-com-bot`, team `modernity`), separated by `service.name`. Chosen
  over standing up a separate collector/env. ("ohwell")
- **Deferred**: extracting Boswell into a shared component — captured as a
  follow-up, not done now. See `notes/telemetry.md` for the full wiring.
