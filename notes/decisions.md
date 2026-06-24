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

## 2026-06-24 — front door: Lambda + public bearer Function URL

- **A Lambda fronts the runtime** so the app uses a plain `Authorization: Bearer`
  over a public HTTPS URL instead of signing SigV4. Rejected AgentCore's native
  `--authorizer-configuration` (it wants OIDC/JWT, not the static shared secret
  Jessitron wanted for one app). Rejected API Gateway (29s timeout would kill long
  coding turns). Chose a **Lambda Function URL** (up to the 15-min Lambda timeout).
- **Accepted the blocking-proxy cost.** A synchronous Lambda bills while it waits
  on the agent. Jessitron flagged this as smelly; we measured it at **<1¢ per
  coding invoke** (arm64, 128MB) and postponed the async-callback alternative
  (buoyed in TODO.md). Min memory + arm64 to keep it cheap.
- **Lambda cost as observability, not code.** The handler stamps the hard-coded
  price *rate* (`lambda.cost.rate_gb_second`, `lambda.cost.rate_per_request`,
  `lambda.memory_gb`) on its span; the dollar cost is a **calculated field in
  Honeycomb** (`rate × duration`). Lets us re-price without redeploying, and keeps
  arithmetic out of the hot path. (Jessitron's call.)
- **Lambda telemetry uses `SimpleSpanProcessor`, not Batch.** Lambda freezes the
  env on return, suspending any background export thread; synchronous export has
  no thread to freeze. (The agent keeps Batch+flush — it emits many spans/turn.)
- **Trace context to the agent rides in the payload, not headers** — forced by the
  discovery that AgentCore forwards only `baggage`, not the `traceParent` param
  (see infrastructure.md gotcha). Open follow-up: is there a standard mechanism?
  (TODO.md, for Jess's OTel knowledge.)
- **What turned out NOT to be true**: an early 403 looked like an org guardrail
  blocking public Function URLs. It wasn't — it was the missing second permission
  statement (Oct-2025 dual-permission requirement). Jessitron caught it via the
  Honeycomb collector-on-Lambda blog. Lesson: verify before concluding "blocked."
